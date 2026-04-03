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
# 2. System packages (dbus-monitor, pip)
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
        "apt-get": ["dbus-x11", "python3-pip", "python3-venv"],
        "dnf":     ["dbus-x11", "python3-pip"],
        "yum":     ["dbus-x11", "python3-pip"],
        "pacman":  ["dbus", "python-pip"],
        "zypper":  ["dbus-1-x11", "python3-pip"],
    }

    pkgs = package_map.get(cmd, ["dbus-x11", "python3-pip", "python3-venv"])
    to_install = []
    if not shutil.which("dbus-monitor"):
        to_install.append(pkgs[0])
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        to_install.extend(pkgs[1:])

    if not to_install:
        ok("System dependencies already present")
        return

    dim(f"Running: sudo {cmd} {' '.join(args)} {' '.join(to_install)}")
    try:
        subprocess.check_call(["sudo", cmd] + args + to_install)
        ok("System dependencies installed")
    except Exception as e:
        warn(f"Failed to install packages: {e}")
        dim(f"Try manually: sudo {cmd} {' '.join(args)} {' '.join(to_install)}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Python venv + dependencies
# ─────────────────────────────────────────────────────────────────────────────
def install_requirements():
    step("Setting up Python virtual environment…")

    venv_dir = os.path.join(HERE, "venv")
    if not os.path.isdir(venv_dir):
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
        ok("Virtual environment created")
    else:
        ok("Virtual environment already exists")

    pip = os.path.join(venv_dir, "bin", "pip")

    req_file = os.path.join(HERE, "requirements.txt")
    if os.path.exists(req_file):
        dim("Installing from requirements.txt…")
        subprocess.check_call([pip, "install", "--quiet", "--upgrade", "pip"])
        subprocess.check_call([pip, "install", "--quiet", "-r", req_file])
    
    # Always ensure production-critical packages are present
    dim("Finalizing production stack…")
    subprocess.check_call([pip, "install", "--quiet", "gunicorn", "eventlet", "flask-socketio"])

    ok("Python dependencies ready")
    return venv_dir


# ─────────────────────────────────────────────────────────────────────────────
# 4. cloudflared
# ─────────────────────────────────────────────────────────────────────────────
def download_cloudflared():
    step("Checking for cloudflared…")

    if shutil.which("cloudflared"):
        ok("cloudflared already installed globally")
        return

    dest = os.path.join(HERE, "cloudflared")
    if os.path.exists(dest):
        ok("cloudflared already present in server directory")
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
# 5. .env configuration
# ─────────────────────────────────────────────────────────────────────────────
def ensure_env_exists(mode: str, os_notif: str):
    step("Writing configuration…")

    env_file = os.path.join(HERE, ".env")
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
        # Patch any missing keys without overwriting existing user values
        with open(env_file, "r") as f:
            content = f.read()
        existing_keys = [l.split("=")[0].strip() for l in content.splitlines() if "=" in l]
        missing = {k: v for k, v in defaults.items() if k not in existing_keys}
        if missing:
            with open(env_file, "a") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                for k, v in missing.items():
                    f.write(f"{k}={v}\n")
            ok(f".env updated  (added: {', '.join(missing.keys())})")
        else:
            ok(".env already up to date")


# ─────────────────────────────────────────────────────────────────────────────
# 6. guga CLI tool
# ─────────────────────────────────────────────────────────────────────────────
def setup_guga_tool():
    step("Installing guga CLI…")

    script_path = os.path.join(HERE, "guga_push.py")
    if not os.path.exists(script_path):
        warn("guga_push.py not found — skipping CLI install")
        return

    os.chmod(script_path, 0o755)

    link_path = "/usr/local/bin/guga"
    try:
        subprocess.check_call(["sudo", "ln", "-sf", script_path, link_path])
        ok(f"guga available as a global command")
    except Exception:
        warn("Could not create global symlink (no sudo?)")
        dim(f"Run manually: sudo ln -sf {script_path} {link_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Man page
# ─────────────────────────────────────────────────────────────────────────────
def setup_man_page():
    step("Installing man page…")

    # Accept guga.1 directly in the server dir or inside a man/ subfolder
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
# 8. systemd service
# ─────────────────────────────────────────────────────────────────────────────
def install_systemd_service(venv_dir: str):
    step("Installing systemd service…")

    if not shutil.which("systemctl"):
        warn("systemd not found — skipping service install")
        dim("Start the server manually with: python3 server.py")
        return

    gunicorn = os.path.join(venv_dir, "bin", "gunicorn")
    env_file  = os.path.join(HERE, ".env")
    try:
        current_user = subprocess.check_output(["logname"], text=True).strip()
    except Exception:
        current_user = os.environ.get("USER", "root")

    service = textwrap.dedent(f"""\
        [Unit]
        Description=GuGa Nexus Backend
        Documentation=https://github.com/PositiveMatician/GuGa-Nexus
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        User={current_user}
        WorkingDirectory={HERE}
        EnvironmentFile={env_file}
        Environment="PYTHONUNBUFFERED=1"
        ExecStart={gunicorn} --worker-class eventlet -w 1 server:app --bind 0.0.0.0:6769 --log-level error
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
        dim("Start the server manually with: python3 server.py")
        return

    # Start / restart the service
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


def get_cloudflare_url():
    try:
        import subprocess, re
        log = subprocess.check_output(
            ["journalctl", "-u", "guga", "-n", "80", "--no-pager"],
            text=True, 
            stderr=subprocess.DEVNULL
        )
        # findall returns a list. The last item is the most recent log entry.
        matches = re.findall(r"https://[-a-z0-9]+\.trycloudflare\.com", log, flags=re.IGNORECASE)
        url = matches[-1] if matches else None
    except (subprocess.CalledProcessError, FileNotFoundError, ImportError):
        url = None
    return url


# ─────────────────────────────────────────────────────────────────────────────
# 9. Print QR code
# ─────────────────────────────────────────────────────────────────────────────
def print_qr(mode: str):
    step("Generating pairing QR code…")
    print()
    try:
        import socket, time
        import qrcode as qrc

        port = "6769"

        if mode == "public":
            # Give the tunnel a moment, then read URL from service journal
            time.sleep(3)
            url = get_cloudflare_url()

            if not url:
                warn("Tunnel URL not ready yet. Re-run: python3 setup.py --qr")
                return
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            url = f"http://{local_ip}:{port}"

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


# ─────────────────────────────────────────────────────────────────────────────
# Interactive questions
# ─────────────────────────────────────────────────────────────────────────────
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
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # ── Banner ────────────────────────────────────────────────────────────────
    print()
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print(f"  {BOLD}  GuGa Nexus  —  Setup{RESET}")
    print(f"  {BOLD}{'─' * 40}{RESET}")

    # ── Questions (skip if --reconfigure not passed and .env already exists) ──
    env_path = os.path.join(HERE, ".env")
    qr_only  = "--qr" in sys.argv

    if qr_only:
        # Just reprint the QR for an already-running server
        existing_mode = "lan"
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("MODE="):
                    existing_mode = line.split("=", 1)[1].strip()
        print_qr(existing_mode)
        sys.exit(0)

    if os.path.exists(env_path) and "--reconfigure" not in sys.argv:
        warn(".env already exists — skipping questions  (use --reconfigure to change)")
        dim("Reading existing configuration…")
        mode = "lan"
        os_notif = "False"
        for line in open(env_path):
            if line.startswith("MODE="):      mode     = line.split("=",1)[1].strip()
            if line.startswith("ENABLE_OS_"): os_notif = line.split("=",1)[1].strip()
    else:
        mode     = ask_mode()
        os_notif = ask_os_notif()

    ok(f"Mode: {BOLD}{mode.upper()}{RESET}")
    ok(f"OS notifications: {BOLD}{os_notif}{RESET}")

    # ── Run setup steps ───────────────────────────────────────────────────────
    install_linux_packages()
    venv_dir = install_requirements()
    if mode == "public":
        download_cloudflared()
    ensure_env_exists(mode, os_notif)
    setup_guga_tool()
    setup_man_page()
    install_systemd_service(venv_dir)
    print_qr(mode)

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print(f"  {GREEN}{BOLD}  GuGa Nexus is installed and running{RESET}")
    print(f"  {BOLD}{'─' * 40}{RESET}")
    print()
    print(f"  {DIM}useful commands{RESET}")
    print(f"    {CYAN}guga \"message\"{RESET}              send a notification")
    print(f"    {CYAN}guga python train.py{RESET}        watch a command")
    print(f"    {CYAN}sudo systemctl stop guga{RESET}    stop the server")
    print(f"    {CYAN}sudo systemctl start guga{RESET}   start the server")
    print(f"    {CYAN}journalctl -u guga -f{RESET}       live logs")
    print(f"    {CYAN}python3 setup.py --qr{RESET}       reprint pairing QR")
    print()
