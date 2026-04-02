import os
import sys
import subprocess
import urllib.request
import shutil
import platform

# Enforce Linux-only restriction
if platform.system() != "Linux":
    print("❌ ERROR: Setup script can only run on Linux.")
    print(f"Current OS: {platform.system()}")
    sys.exit(1)

def get_package_manager():
    """Detect the system's package manager."""
    managers = {
        "apt-get": ["apt-get", "install", "-y"],
        "dnf": ["dnf", "install", "-y"],
        "pacman": ["pacman", "-S", "--noconfirm"],
        "zypper": ["zypper", "install", "-y"],
        "yum": ["yum", "install", "-y"],
    }
    for cmd, args in managers.items():
        if shutil.which(cmd):
            return cmd, args
    return None, None

def install_linux_packages():
    """Install system-level dependencies (e.g., dbus-monitor)."""
    if shutil.which("dbus-monitor"):
        print("[SETUP] dbus-monitor is already installed.")
        return

    print("[SETUP] dbus-monitor not found. Attempting to install system dependencies...")
    cmd, args = get_package_manager()
    
    if not cmd:
        print("[WARNING] Could not detect package manager. Please install 'dbus-x11' (Ubuntu/Debian) or 'dbus-tools' manually.")
        return

    # Package name mapping
    package_map = {
        "apt-get": "dbus-x11",
        "dnf": "dbus-x11",
        "yum": "dbus-x11",
        "pacman": "dbus",
        "zypper": "dbus-1-x11",
    }
    
    pkg_name = package_map.get(cmd, "dbus-x11")
    
    print(f"[SETUP] Detected {cmd}. Running: sudo {cmd} {' '.join(args)} {pkg_name}")
    try:
        subprocess.check_call(["sudo"] + [cmd] + args + [pkg_name])
        print("[SETUP] System dependencies installed successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to install packages: {e}")
        print(f"Please try manually: sudo {cmd} {' '.join(args)} {pkg_name}")

def install_requirements():
    print("[SETUP] Installing Python dependencies...")
    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if os.path.exists(req_file):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
            print("[SETUP] Python dependencies installed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to install Python dependencies: {e}")
    else:
        print("[SKIP] No requirements.txt found.")

def download_cloudflared():
    print("[SETUP] Checking for cloudflared binary...")
    
    if shutil.which("cloudflared"):
        print("[SETUP] cloudflared is already installed globally.")
        return

    arch = platform.machine().lower()
    if arch in ["x86_64", "amd64"]:
        arch_suffix = "amd64"
    elif arch in ["arm64", "aarch64"]:
        arch_suffix = "arm64"
    else:
        print(f"[ERROR] Unsupported architecture: {arch}")
        return

    dest = "cloudflared"
    if os.path.exists(dest):
        print(f"[SETUP] Local {dest} already exists.")
        return

    filename = f"cloudflared-linux-{arch_suffix}"
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{filename}"
    
    print(f"[SETUP] Downloading {filename} from Cloudflare...")
    try:
        urllib.request.urlretrieve(url, dest)
        os.chmod(dest, 0o755)
        print(f"[SETUP] Download complete and permissions set.")
    except Exception as e:
        print(f"[ERROR] Download failed: {e}")

def ensure_env_exists():
    env_file = ".env"
    if not os.path.exists(env_file):
        print("[SETUP] Creating default .env file...")
        default_content = "ENABLE_OS_NOTIFICATIONS=True\nMODE=lan\nPORT=6769\n"
        with open(env_file, "w") as f:
            f.write(default_content)
        print("[SETUP] .env file created.")

if __name__ == "__main__":
    print("\n" + "="*40)
    print("      GuGu Server Setup")
    print("      (Linux Only Interface)")
    print("="*40 + "\n")
    
    install_linux_packages()
    install_requirements()
    download_cloudflared()
    ensure_env_exists()
    
    print("\n" + "="*40)
    print("  SUCCESS: Environment is ready!")
    print("  Run the server with: python server.py")
    print("="*40 + "\n")
