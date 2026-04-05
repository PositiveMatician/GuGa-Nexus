import os
import sys
import subprocess
import urllib.request
import shutil
import platform
import textwrap

# ── Linux guard ───────────────────────────────────────────────────────────────
if platform.system() != "Linux":
    print("❌  This setup only runs on Linux.")
    print(f"    Current OS: {platform.system()}")
    sys.exit(1)

# ── Colour helpers ────────────────────────────────────────────────────────────
RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
GREEN  = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"

def step(msg):  print(f"\n  {BOLD}{CYAN}→{RESET}  {msg}")
def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"\n  {RED}✗  ERROR:{RESET} {msg}\n"); sys.exit(1)
def dim(msg):   print(f"  {DIM}{msg}{RESET}")
def ask(msg):   return input(f"  {msg}").strip()

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.expanduser("~/.guga")
if not os.path.exists(CONFIG_DIR):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception:
        pass

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
def ensure_env_exists(mode: str, os_notif: str, force: bool = False):
    step("Writing configuration…")

    env_file = os.path.join(CONFIG_DIR, ".env")
    defaults = {
        "MODE":                   mode,
        "PORT":                   "6769",
        "ENABLE_OS_NOTIFICATIONS": os_notif,
        "ALERTER_SERVER_URL":     "http://localhost:6769/send",
        "GUGA_VERBOSE":           "false",
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
            if force and k in ["MODE", "ENABLE_OS_NOTIFICATIONS"]:
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
        dim("Start the server manually with: python3 -m guga.daemon")
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
        ExecStart={gunicorn_path} --worker-class eventlet -w 1 {daemon_module} --bind 0.0.0.0:6769 --log-level error
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
        dim("Start the server manually with: python3 -m guga.daemon")
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
    import subprocess, re, time
    start = time.time()
    url_pattern = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com", flags=re.IGNORECASE)
    
    while time.time() - start < timeout:
        try:
            log = subprocess.check_output(
                ["journalctl", "-u", "guga", "-n", "80", "--no-pager"],
                text=True, 
                stderr=subprocess.DEVNULL
            )
            
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

def run_system_installer(qr_only=False, setup_only=False):
    env_path = os.path.join(CONFIG_DIR, ".env")
    
    if qr_only:
        import subprocess
        try:
            result = subprocess.run(["systemctl", "is-active", "guga"], capture_output=True, text=True)
            if result.stdout.strip() != "active":
                print(f"\n  {BOLD}{RED}Error:{RESET} {DIM}The 'guga' service is not running.{RESET}")
                print(f"  {DIM}Please start the daemon first:{RESET} {BOLD}sudo systemctl start guga{RESET}\n")
                sys.exit(1)
        except Exception:
            pass

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

    if os.path.exists(env_path) and "--reconfigure" not in sys.argv:
        warn(".env already exists — skipping questions  (use guga --install-service --reconfigure to change)")
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

    ok(f"Mode: {BOLD}{mode.upper()}{RESET}")
    ok(f"OS notifications: {BOLD}{os_notif}{RESET}")

    install_linux_packages()
    if mode == "public":
        download_cloudflared()
    ensure_env_exists(mode, os_notif, force=False)
    setup_man_page()
    install_systemd_service()
    
    print()
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print(f"  {GREEN}{BOLD}  GuGa Nexus is installed and running{RESET}")
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print()
    if mode == "public":
        print(f"  {DIM}Cloudflare Tunnel is starting up in the background...{RESET}")
        print(f"  {DIM}Run this command in a few seconds to pair your device:{RESET}")
    else:
        print(f"  {DIM}Run this command to pair your device:{RESET}")
    print(f"    {BOLD}guga --qr{RESET}\n")

def run_system_uninstaller():
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

    # 1. Service Status
    is_active = False
    try:
        # Check if systemctl exists
        if shutil.which("systemctl"):
            result = subprocess.run(["systemctl", "is-active", "guga"], capture_output=True, text=True)
            is_active = (result.stdout.strip() == "active")
        else:
            # Fallback if no systemd
            is_active = False
    except Exception:
        pass

    status_str = f"{GREEN}Active{RESET}" if is_active else f"{RED}Inactive{RESET}"
    print(f"  {DIM}service{RESET}   {BOLD}{status_str}{RESET}")

    if is_active:
        # 2. URL
        url = get_current_url()
        print(f"  {DIM}address{RESET}   {BOLD}{url if url else 'Detecting...'}{RESET}")

        # 3. Clients (query server)
        clients_count = "?"
        try:
            import urllib.request, json
            with urllib.request.urlopen("http://localhost:6769/ping", timeout=2) as r:
                data = json.load(r)
                clients_count = data.get("clients", 0)
        except Exception:
            pass
        print(f"  {DIM}clients{RESET}   {BOLD}{clients_count} connected{RESET}")
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
