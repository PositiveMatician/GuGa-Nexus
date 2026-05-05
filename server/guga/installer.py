"""
GuGa Nexus — System Installer & Configurator
Version: 1.5.1

This module handles the initial setup of the GuGa system on Linux,
including dependency installation, systemd service generation,
and capability registration.
"""

import os
import sys
import subprocess
import urllib.request
import shutil
import platform
import textwrap
import json

from .db_utils import Database
from .lock_utils import FileLock
from dotenv import load_dotenv

env_path = os.path.join(os.environ.get("GUGA_CONFIG_DIR", os.path.expanduser("~/.guga")), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

db = Database()



# ── Colour helpers ────────────────────────────────────────────────────────────
RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
GREEN  = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"

def step(msg):  print(f"\n  {BOLD}{CYAN}→{RESET}  {msg}")
def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"\n  {RED}✗  ERROR:{RESET} {msg}\n"); sys.exit(1)
def dim(msg):   print(f"  {DIM}{msg}{RESET}")
PREFILLED_CHOICES = []
_choice_idx = 0

def ask(msg):
    global _choice_idx
    if _choice_idx < len(PREFILLED_CHOICES):
        val = PREFILLED_CHOICES[_choice_idx]
        _choice_idx += 1
        print(f"  {msg}{BOLD}{val}{RESET} {DIM}(auto){RESET}")
        return val
    return input(f"  {msg}").strip()


HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get("GUGA_CONFIG_DIR", os.path.expanduser("~/.guga"))
CAPABILITIES_FILE = os.path.join(CONFIG_DIR, "capabilities.json")
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

def is_root():
    return os.geteuid() == 0

def load_capabilities():
    return db.get_capabilities()

def save_capabilities(data):
    db.save_capabilities(data)

def migrate_capabilities_json():
    """Migrate capabilities.json to SQLite on first run."""
    if os.path.exists(CAPABILITIES_FILE):
        step("Migrating capabilities.json to db...")
        try:
            with open(CAPABILITIES_FILE, "r") as f:
                data = json.load(f)
                db.save_capabilities(data)
            os.rename(CAPABILITIES_FILE, CAPABILITIES_FILE + ".bak")
            ok("Migration complete")
        except Exception as e:
            warn(f"Migration failed: {e}")

migrate_capabilities_json()

if not os.path.exists(CONFIG_DIR):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception:
        pass

import json

# ─────────────────────────────────────────────────────────────────────────────
# 1. Package manager detection
# ─────────────────────────────────────────────────────────────────────────────
def get_package_manager():
    managers = {
        "apt-get": ["apt-get", "install", "-y"],
        "dnf":     ["dnf",     "install", "-y"],
        "pacman":  ["pacman",  "-S", "--noconfirm"],
        "zypper":  ["zypper",  "install", "-y"],
        "yum":     ["yum",     "install", "-y"],
    }
    for cmd, args in managers.items():
        if shutil.which(cmd):
            return cmd, args
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# 2. System packages (dbus-monitor)
# ─────────────────────────────────────────────────────────────────────────────
def install_linux_packages():
    step("Checking system dependencies…")

    if shutil.which("dbus-monitor"):
        ok("dbus-monitor already installed")
        return

    cmd, args = get_package_manager()
    if not cmd:
        warn("Could not detect package manager. Install 'dbus-x11' manually if needed.")
        return

    package_map = {
        "apt-get": ["dbus-x11"],
        "dnf":     ["dbus-x11"],
        "yum":     ["dbus-x11"],
        "pacman":  ["dbus"],
        "zypper":  ["dbus-1-x11"],
    }

    to_install = package_map.get(cmd, ["dbus-x11"])
    dim(f"Running: sudo {cmd} {' '.join(args)} {' '.join(to_install)}")
    try:
        subprocess.check_call(["sudo", cmd] + args + to_install)
        ok("System dependencies installed")
    except Exception as e:
        warn(f"Failed to install packages: {e}")
        dim(f"Try manually: sudo {cmd} {' '.join(args)} {' '.join(to_install)}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. cloudflared
# ─────────────────────────────────────────────────────────────────────────────
def download_cloudflared():
    step("Checking for cloudflared…")

    if shutil.which("cloudflared") and not os.path.exists(os.path.join(CONFIG_DIR, "cloudflared")):
        ok("cloudflared already installed globally")
        return

    dest = os.path.join(CONFIG_DIR, "cloudflared")
    if os.path.exists(dest):
        ok("cloudflared already present in user guga directory")
        return

    arch = platform.machine().lower()
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64", "armv7l": "arm"}
    arch_suffix = arch_map.get(arch)
    if not arch_suffix:
        warn(f"Unsupported architecture '{arch}' — skipping cloudflared download")
        return

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch_suffix}"
    dim(f"Downloading cloudflared ({arch_suffix})…")
    try:
        urllib.request.urlretrieve(url, dest)
        os.chmod(dest, 0o755)
        ok("cloudflared downloaded")
    except Exception as e:
        warn(f"Download failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. .env configuration
# ─────────────────────────────────────────────────────────────────────────────
def ensure_env_exists(mode: str, os_notif: str, force: bool = False, use_journalctl: bool = True):
    step("Writing configuration…")

    env_file = os.path.join(CONFIG_DIR, ".env")
    defaults = {
        "MODE":                   mode,
        "PORT":                   "6769",
        "ENABLE_OS_NOTIFICATIONS": os_notif,
        "ALERTER_SERVER_URL":     "http://localhost:6769/send",
        "GUGA_VERBOSE":           "false",
        "USE_JOURNALCTL":         "true" if use_journalctl else "false",
    }

    if not os.path.exists(env_file):
        with open(env_file, "w") as f:
            for k, v in defaults.items():
                f.write(f"{k}={v}\n")
        ok(f".env created")
    else:
        with open(env_file, "r") as f:
            lines = f.read().splitlines()

        updated = False
        new_lines = []
        for line in lines:
            if not line.strip() or not "=" in line:
                new_lines.append(line)
                continue
                
            k = line.split("=", 1)[0].strip()
            if force and k in ["MODE", "ENABLE_OS_NOTIFICATIONS", "USE_JOURNALCTL"]:
                if line.strip() != f"{k}={defaults[k]}":
                    new_lines.append(f"{k}={defaults[k]}")
                    updated = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        existing_keys = [l.split("=")[0].strip() for l in new_lines if "=" in l]
        missing = {k: v for k, v in defaults.items() if k not in existing_keys}
        
        for k, v in missing.items():
            new_lines.append(f"{k}={v}")
            updated = True
            
        if updated:
            with open(env_file, "w") as f:
                f.write("\n".join(new_lines) + "\n")
            if missing:
                ok(f".env updated  (added: {', '.join(missing.keys())})")
            else:
                ok(".env updated with new configuration")
        else:
            ok(".env already up to date")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Man page
# ─────────────────────────────────────────────────────────────────────────────
def setup_man_page():
    step("Installing man page…")

    candidates = [
        os.path.join(HERE, "guga.1"),
        os.path.join(HERE, "man", "guga.1"),
    ]
    source = next((p for p in candidates if os.path.exists(p)), None)

    if not source:
        warn("guga.1 not found — skipping man page")
        return

    dest_dir = "/usr/local/share/man/man1"
    try:
        subprocess.check_call(["sudo", "mkdir", "-p", dest_dir])
        subprocess.check_call(["sudo", "cp", source, os.path.join(dest_dir, "guga.1")])
        if shutil.which("mandb"):
            subprocess.check_call(["sudo", "mandb", "-q"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok("man page installed  (man guga)")
    except Exception as e:
        warn(f"Could not install man page: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. systemd service
# ─────────────────────────────────────────────────────────────────────────────
def install_systemd_service():
    step("Installing systemd service…")

    if not shutil.which("systemctl"):
        warn("systemd not found — skipping service install")
        dim("Start the server manually with: guga --start-server")
        return

    gunicorn_path = shutil.which("gunicorn") or sys.executable + " -m gunicorn"
    env_file  = os.path.join(CONFIG_DIR, ".env")
    
    try:
        current_user = subprocess.check_output(["logname"], text=True).strip()
    except Exception:
        current_user = os.environ.get("USER", "root")
        
    try:
        current_uid = subprocess.check_output(["id", "-u", current_user], text=True).strip()
    except Exception:
        current_uid = "1000"

    try:
        # Determine the site-packages or source path to the daemon module for gunicorn to find
        daemon_module = "guga.daemon:app"
    except Exception:
        daemon_module = "guga.daemon:app"

    service = textwrap.dedent(f"""\
        [Unit]
        Description=GuGa Nexus Backend
        Documentation=https://github.com/PositiveMatician/GuGa-Nexus
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        User={current_user}
        WorkingDirectory={CONFIG_DIR}
        EnvironmentFile={env_file}
        Environment="PYTHONUNBUFFERED=1"
        Environment="DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{current_uid}/bus"
        ExecStart={gunicorn_path} --worker-class uvicorn.workers.UvicornWorker -w 1 {daemon_module} --bind 0.0.0.0:6769 --log-level error
        Restart=on-failure
        RestartSec=5
        KillSignal=SIGTERM
        TimeoutStopSec=10

        [Install]
        WantedBy=multi-user.target
    """)

    service_path = "/etc/systemd/system/guga.service"
    try:
        proc = subprocess.run(["sudo", "tee", service_path],
                              input=service, text=True,
                              stdout=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError("tee failed")
        subprocess.check_call(["sudo", "systemctl", "daemon-reload"])
        subprocess.check_call(["sudo", "systemctl", "enable", "guga", "--quiet"])
        ok("systemd service installed and enabled on boot")
    except Exception as e:
        warn(f"Could not install systemd service: {e}")
        dim("Start the server manually with: guga --start-server")
        return

    try:
        subprocess.check_call(["sudo", "systemctl", "restart", "guga"])
        import time; time.sleep(2)
        result = subprocess.run(["systemctl", "is-active", "guga"],
                                capture_output=True, text=True)
        if result.stdout.strip() == "active":
            ok("Server started successfully")
        else:
            warn("Server may not have started — check with: journalctl -u guga -n 30")
    except Exception:
        warn("Could not start service — check with: journalctl -u guga -n 30")


def get_cloudflare_url(timeout=15):
    import subprocess, re, time, os, glob
    import urllib.request as _urllib_req
    start = time.time()
    url_pattern = re.compile(r"https://(?!api)[-a-z0-9]+\.trycloudflare\.com", flags=re.IGNORECASE)
    tag_pattern = re.compile(r"\[GUGA_URL\]\s*(https?://[^\s\033]+)")

    def _ping_url(url):
        """Return True if the GuGa server at this URL is reachable."""
        try:
            with _urllib_req.urlopen(f"{url}/ping", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def _get_url_from_cloudflared_metrics():
        """Query cloudflared's local metrics API for the live tunnel URL. Always accurate."""
        # cloudflared listens on 20241 by default for the free tunnel daemon
        for metrics_port in (20241, 2000):
            try:
                with _urllib_req.urlopen(f"http://localhost:{metrics_port}/metrics", timeout=2) as r:
                    for line in r.read().decode().splitlines():
                        if "userHostname" in line:
                            m = url_pattern.search(line)
                            if m:
                                return m.group(0)
            except Exception:
                continue
        return None

    # 0a. Query the live cloudflared metrics API — most authoritative source.
    # This is always current as long as cloudflared is running.
    cf_url = _get_url_from_cloudflared_metrics()
    if cf_url:
        return cf_url

    # 0b. Check for the explicit current_url file (fastest fallback when cloudflared metrics unavailable).
    # Validate with /ping to reject stale entries from ungraceful shutdowns.
    url_file = os.path.join(CONFIG_DIR, "current_url")
    if os.path.exists(url_file):
        try:
            # Only use it if it's "fresh" (modified in the last 10 minutes)
            if time.time() - os.path.getmtime(url_file) < 600:
                with open(url_file, "r") as f:
                    url = f.read().strip()
                if url and _ping_url(url):
                    return url
                elif url:
                    # Stale — remove so future calls skip it
                    try:
                        os.remove(url_file)
                    except Exception:
                        pass
        except Exception:
            pass

    while time.time() - start < timeout:
        # 1. Try journalctl (for background systemd service)
        use_journalctl = os.getenv("USE_JOURNALCTL", "true").lower() == "true"
        if use_journalctl and shutil.which("journalctl"):
            try:
                log = subprocess.check_output(
                    ["journalctl", "-u", "guga", "-n", "80", "--no-pager"],
                    text=True, 
                    stderr=subprocess.DEVNULL
                )
                
                # Try the new tag first
                tag_match = tag_pattern.search(log)
                if tag_match:
                    return tag_match.group(1)

                spawn_idx = log.rfind("spawning public tunnel")
                if spawn_idx != -1:
                    matches = url_pattern.findall(log[spawn_idx:])
                    if matches:
                        return matches[-1]
                else:
                    matches = url_pattern.findall(log)
                    if matches:
                        return matches[-1]
            except Exception:
                pass
            
        # 2. Try scanning local log files (for foreground or Colab/Docker background servers)
        log_dir = os.path.join(CONFIG_DIR, "logs")
        if os.path.exists(log_dir):
            # Sort by modification time, newest first
            log_files = sorted(glob.glob(os.path.join(log_dir, "*.log")), key=os.path.getmtime, reverse=True)
            for log_file in log_files[:3]: # Check last 3 logs
                try:
                    with open(log_file, "r") as f:
                        content = f.read()
                        # Tag search
                        tag_match = tag_pattern.search(content)
                        if tag_match:
                            return tag_match.group(1)
                        # Generic pattern search
                        matches = url_pattern.findall(content)
                        if matches:
                            return matches[-1]
                except Exception:
                    pass

        time.sleep(1)
        
    return None

def get_current_url():
    """Determine the current pairing URL based on configuration."""
    # Read mode from .env
    env_path = os.path.join(CONFIG_DIR, ".env")
    mode = "lan"
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("MODE="):
                    mode = line.split("=", 1)[1].strip()
                    break

    if mode == "public":
        return get_cloudflare_url()
    else:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            return f"http://{local_ip}:6769"
        except Exception:
            return "http://localhost:6769"

def print_qr(mode: str):
    step("Generating pairing QR code…")
    print()
    try:
        import qrcode as qrc
        url = get_current_url()

        if not url:
            warn("Tunnel URL not ready yet or service is not running. Wait a moment and re-run: guga --qr")
            return

        print(f"  {DIM}address →{RESET}  {BOLD}{url}{RESET}\n")
        qr = qrc.QRCode(version=None,
                        error_correction=qrc.constants.ERROR_CORRECT_L,
                        box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)

    except ImportError:
        warn("qrcode not installed yet — QR will show on next server start")
    except Exception as e:
        warn(f"Could not generate QR: {e}")


def ask_mode() -> str:
    print()
    print(f"  {BOLD}How will you connect?{RESET}")
    print()
    print(f"    {BOLD}1){RESET}  LAN only   — phone must be on the same Wi-Fi")
    print(f"    {BOLD}2){RESET}  Internet   — anywhere, via Cloudflare Tunnel (no domain needed)")
    print()
    choice = ask("Your choice [1/2]: ")
    return "public" if choice.strip() == "2" else "lan"

def ask_os_notif() -> str:
    print()
    print(f"  {BOLD}Forward OS notifications to your phone?{RESET}")
    dim("System alerts, app notifications — forwarded to Android in real time.")
    print()
    choice = ask("Enable? [y/N]: ")
    return "True" if choice.lower() == "y" else "False"


# ─────────────────────────────────────────────────────────────────────────────
# Proxy Logic Extracted from script
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 7. Stage Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

class Stage:
    def __init__(self, id, name, requires_sudo, action_fn, requirements_check=None, provides_capability=None):
        self.id = id
        self.name = name
        self.requires_sudo = requires_sudo
        self.action_fn = action_fn
        self.requirements_check = requirements_check
        self.provides_capability = provides_capability

    def run(self, state, force=False):
        if self.id in state["installed_stages"] and not force:
            ok(f"{self.name} already installed")
            return True

        step(f"Stage: {self.name}")

        if self.requires_sudo and not is_root():
            warn(f"Skipping {self.name} — requires sudo privileges.")
            dim("Rerun the installer with sudo to include this stage.")
            return False

        if self.requirements_check:
            met, reason = self.requirements_check()
            if not met:
                warn(f"Skipping {self.name} — requirements not met: {reason}")
                return False

        try:
            self.action_fn()
            if self.id not in state["installed_stages"]:
                state["installed_stages"].append(self.id)
            if self.provides_capability:
                state["capabilities"][self.provides_capability] = True
            ok(f"{self.name} completed")
            return True
        except Exception as e:
            fail(f"Stage {self.name} failed: {e}")
            return False

def check_systemd():
    if shutil.which("systemctl"):
        return True, ""
    return False, "systemd not found"

def check_man():
    candidates = [
        os.path.join(HERE, "guga.1"),
        os.path.join(HERE, "man", "guga.1"),
    ]
    if any(os.path.exists(p) for p in candidates):
        return True, ""
    return False, "man page source (guga.1) not found"

def register_skill_in_lockfile():
    """Registers the guga skill in skills-lock.json."""
    lockfile_path = os.path.join(REPO_ROOT, "skills-lock.json")
    
    skill_entry = {
        "source": "local",
        "sourceType": "local",
        "skillPath": "guga/SKILL.md"
    }

    data = {"version": 1, "skills": {}}
    
    if os.path.exists(lockfile_path):
        try:
            with open(lockfile_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            warn(f"Could not read skills-lock.json: {e}")

    if "skills" not in data:
        data["skills"] = {}

    data["skills"]["guga"] = skill_entry

    try:
        with open(lockfile_path, "w") as f:
            json.dump(data, f, indent=2)
        ok("Skill registered in skills-lock.json")
    except Exception as e:
        warn(f"Could not update skills-lock.json: {e}")

def install_skills():
    """Installs the GuGa skill to the .agents/skills directory."""
    step("Installing GuGa skill…")
    
    skills_dir = os.path.join(REPO_ROOT, ".agents", "skills")
    if not os.path.exists(skills_dir):
        try:
            os.makedirs(skills_dir, exist_ok=True)
            ok(f"Created skills directory: {skills_dir}")
        except Exception as e:
            fail(f"Could not create skills directory: {e}")

    source_skill = os.path.join(HERE, "FOR_AI_REFERENCE")
    dest_skill = os.path.join(skills_dir, "guga")

    if not os.path.exists(source_skill):
        warn(f"Source skill directory not found: {source_skill}")
        return

    try:
        if os.path.exists(dest_skill):
            shutil.rmtree(dest_skill)
        shutil.copytree(source_skill, dest_skill)
        ok(f"Skill installed to {dest_skill}")
        
        # New step: Register in lockfile
        register_skill_in_lockfile()
        
    except Exception as e:
        warn(f"Failed to install skill: {e}")

def run_system_installer(qr_only=False, setup_only=False, install_skills_flag=False):
    # ── Linux guard ───────────────────────────────────────────────────────────────
    if platform.system() != "Linux":
        print("❌  This setup only runs on Linux.")
        print(f"    Current OS: {platform.system()}")
        sys.exit(1)
    
    with FileLock("install"):
        env_path = os.path.join(CONFIG_DIR, ".env")
        
        if qr_only:
            existing_mode = "lan"
            if os.path.exists(env_path):
                for line in open(env_path):
                    if line.startswith("MODE="):
                        existing_mode = line.split("=", 1)[1].strip()
            print_qr(existing_mode)
            sys.exit(0)

        print()
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print(f"  {BOLD}  GuGa Nexus  —  Setup{RESET}")
        print(f"  {BOLD}{'─' * 40}{RESET}")

        state = load_capabilities()
        reconfigure = "--reconfigure" in sys.argv

        if install_skills_flag:
            install_skills()
            if not setup_only: # If only skills was requested, exit after
                save_capabilities(state)
                return

        if os.path.exists(env_path) and not reconfigure:
            warn(".env already exists — skipping basic configuration")
            dim("Reading existing configuration…")
            mode = "lan"
            os_notif = "False"
            for line in open(env_path):
                if line.startswith("MODE="):      mode     = line.split("=",1)[1].strip()
                if line.startswith("ENABLE_OS_"): os_notif = line.split("=",1)[1].strip()
        else:
            mode     = ask_mode()
            os_notif = ask_os_notif()
            ensure_env_exists(mode, os_notif, force=True)

        # Advanced Options
        print()
        print(f"  {BOLD}Advanced Options{RESET}")
        print(f"    {BOLD}1){RESET}  Standard Service (Background, Systemd)")
        print(f"    {BOLD}2){RESET}  Foreground Only  (Skip systemd setup)")
        print()
        adv_choice = ask("Your choice [1/2]: ")
        foreground_only = (adv_choice.strip() == "2")
        use_journalctl = not foreground_only

        stages = [
            Stage("system_packages", "System Dependencies", True, install_linux_packages),
            Stage("env_config", "Configuration", False, lambda: ensure_env_exists(mode, os_notif, force=reconfigure, use_journalctl=use_journalctl)),
            Stage("man_page", "Manual Page", True, setup_man_page, check_man),
        ]

        if mode == "public":
            stages.insert(1, Stage("cloudflared", "Cloudflare Tunnel", False, download_cloudflared))

        if not foreground_only:
            stages.append(Stage("systemd_service", "Systemd Service", True, install_systemd_service, check_systemd, "background_service"))
        else:
            # Explicitly remove systemd capability if it was there
            state["capabilities"].pop("background_service", None)
            if "systemd_service" in state["installed_stages"]:
                state["installed_stages"].remove("systemd_service")

        for s in stages:
            s.run(state, force=reconfigure)

        save_capabilities(state)

        print()
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print(f"  {GREEN}{BOLD}  GuGa Nexus setup complete{RESET}")
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print()
        
        if foreground_only:
            ok("Foreground mode selected: systemd service was NOT installed.")
            print(f"  {DIM}To start the server, run:{RESET}")
            print(f"    {BOLD}guga --start-server{RESET}\n")
        elif "background_service" in state["capabilities"]:
            ok("Server is running as a systemd service.")
        
        if mode == "public":
            print(f"  {DIM}Run this command in a few seconds to pair your device:{RESET}")
        else:
            print(f"  {DIM}Run this command to pair your device:{RESET}")
        print(f"    {BOLD}guga --qr{RESET}\n")

def run_system_uninstaller():
    with FileLock("install"):
        print()
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print(f"  {BOLD}  GuGa Nexus  —  Uninstallation{RESET}")
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print()

        # 1. Stop and Disable Service
        step("Stopping and disabling systemd service...")
        try:
            subprocess.run(["sudo", "systemctl", "stop", "guga"], stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "systemctl", "disable", "guga"], stderr=subprocess.DEVNULL)
            ok("Service stopped and disabled")
        except Exception as e:
            warn(f"Could not stop service: {e}")

        # 2. Remove Service File
        step("Removing systemd unit file...")
        service_path = "/etc/systemd/system/guga.service"
        try:
            # Check existence via sudo if necessary, but since we use sudo rm it's fine
            subprocess.run(["sudo", "rm", "-f", service_path], check=True)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            ok("Service file removed")
        except Exception as e:
            warn(f"Could not remove service file: {e}")

        # 3. Remove Man Page
        step("Removing man page...")
        man_path = "/usr/local/share/man/man1/guga.1"
        try:
            subprocess.run(["sudo", "rm", "-f", man_path], check=True)
            if shutil.which("mandb"):
                subprocess.run(["sudo", "mandb", "-q"], stderr=subprocess.DEVNULL)
            ok("Man page removed")
        except Exception as e:
            warn(f"Could not remove man page: {e}")

        # 4. Optional: Remove Config Directory
        print()
        choice = ask(f"  {BOLD}Remove all configuration and logs in {CONFIG_DIR}? [y/N]{RESET} ")
        if choice.lower() == "y":
            step(f"Removing {CONFIG_DIR}...")
            try:
                shutil.rmtree(CONFIG_DIR)
                ok("Configuration directory deleted")
            except Exception as e:
                warn(f"Could not remove config directory: {e}")
        else:
            dim("Keeping configuration directory")

        print()
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print(f"  {GREEN}{BOLD}  System components removed successfully{RESET}")
        print(f"  {BOLD}{'─' * 40}{RESET}")
        print()
        print(f"  {BOLD}Next step:{RESET}")
        print(f"  To completely remove the Python package, run:")
        print(f"  {BOLD}pip uninstall GuGa{RESET}")
        print()

def run_status():
    """Display a consolidated report of the GuGa service status."""
    print()
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print(f"  {BOLD}  GuGa Nexus  —  Status{RESET}")
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print()

    # 1. Determine Port — env var takes priority over .env file
    port = os.environ.get("PORT", "6769")
    env_path = os.path.join(CONFIG_DIR, ".env")
    if port == "6769" and os.path.exists(env_path):
        try:
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("PORT="):
                        port = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

    # 2. Check Service Status
    is_systemd_active = False
    try:
        if shutil.which("systemctl"):
            result = subprocess.run(["systemctl", "is-active", "guga"], capture_output=True, text=True)
            is_systemd_active = (result.stdout.strip() == "active")
    except Exception:
        pass

    # 3. Check if server is reachable
    server_alive = False
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://localhost:{port}/ping", timeout=1) as r:
            server_alive = (r.status == 200)
    except Exception:
        pass

    is_active = server_alive or is_systemd_active
    
    if is_systemd_active:
        status_str = f"{GREEN}Active{RESET}"
    elif server_alive:
        status_str = f"{GREEN}Active{RESET} {DIM}(manual){RESET}"
    else:
        status_str = f"{RED}Inactive{RESET}"

    print(f"  {DIM}service{RESET}   {BOLD}{status_str}{RESET}")

    if is_active:
        # 2. URL
        url = get_current_url()
        print(f"  {DIM}address{RESET}   {BOLD}{url if url else 'Detecting...'}{RESET}")

        # 3. Clients (query server)

        try:
            import urllib.request, json
            with urllib.request.urlopen(f"http://localhost:{port}/api/devices", timeout=2) as r:
                data = json.load(r)
                devices = data.get("devices", [])
                print(f"  {DIM}clients{RESET}   {BOLD}{len(devices)} connected{RESET}")
                for d in devices:
                    name = d.get("device_name", "Unknown")
                    tag = d.get("tag")
                    did = d.get("device_id", "")
                    short_id = did[:8] if did else "???"
                    tag_str = f" {CYAN}[{tag}]{RESET}" if tag else ""
                    print(f"            {DIM}•{RESET} {name} {DIM}({short_id}){RESET}{tag_str}")
        except Exception:
            print(f"  {DIM}clients{RESET}   {BOLD}? connected{RESET}")
    else:
        print(f"  {DIM}info{RESET}      {DIM}Service is stopped. Start with: {RESET}{BOLD}guga --install-service{RESET}")

    print()
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print()

def run_url():
    """Output only the raw pairing URL."""
    url = get_current_url()
    if url:
        print(url)
    else:
        # If tunnel not ready, don't print anything or print error to stderr
        print("Error: Tunnel URL not ready", file=sys.stderr)
        sys.exit(1)

def run_reload():
    """Reload (restart) the systemd service."""
    state = load_capabilities()
    if not state.get("capabilities", {}).get("background_service"):
        print(f"\n  {RED}✗  ERROR:{RESET} No background service installed.")
        print(f"  {DIM}Use {RESET}{BOLD}guga --install-service{RESET}{DIM} to set it up.{RESET}\n")
        sys.exit(1)
    
    step("Reloading GuGa Nexus service…")
    try:
        subprocess.check_call(["sudo", "systemctl", "restart", "guga"])
        ok("Service reloaded")
    except Exception as e:
        fail(f"Could not reload service: {e}")
