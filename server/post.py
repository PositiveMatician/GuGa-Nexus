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
        "apt-get": ["dbus-x11", "python3-pip"],
        "dnf": ["dbus-x11", "python3-pip"],
        "yum": ["dbus-x11", "python3-pip"],
        "pacman": ["dbus", "python-pip"],
        "zypper": ["dbus-1-x11", "python3-pip"],
    }
    
    pkgs = package_map.get(cmd, ["dbus-x11", "python3-pip"])
    
    # Filter out already installed packages to avoid unnecessary sudo if possible
    to_install = []
    if not shutil.which("dbus-monitor"):
        to_install.append(pkgs[0])
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        to_install.append(pkgs[1])

    if not to_install:
        print("[SETUP] All system dependencies are already present.")
        return

    print(f"[SETUP] Detected {cmd}. Running: sudo {cmd} {' '.join(args)} {' '.join(to_install)}")
    try:
        subprocess.check_call(["sudo"] + [cmd] + args + to_install)
        print("[SETUP] System dependencies installed successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to install packages: {e}")
        print(f"Please try manually: sudo {cmd} {' '.join(args)} {' '.join(to_install)}")

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

def setup_man_page():
    """Install the guga man pages from the man/ folder."""
    man_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "man")
    if not os.path.isdir(man_dir):
        print(f"[SKIP] No {man_dir} found.")
        return

    print(f"[SETUP] Installing man pages from {man_dir}...")
    
    # Supported man sections (usually 1-8)
    for filename in os.listdir(man_dir):
        if not filename.endswith(tuple(f".{i}" for i in range(1, 9))):
            continue
            
        section = filename.split(".")[-1]
        dest_dir = f"/usr/local/share/man/man{section}"
        source_man = os.path.join(man_dir, filename)
        dest_man = os.path.join(dest_dir, filename)

        try:
            # Create directory if it doesn't exist
            subprocess.check_call(["sudo", "mkdir", "-p", dest_dir])
            # Copy the manual file
            subprocess.check_call(["sudo", "cp", source_man, dest_man])
            print(f"[SETUP] Installed {filename} to {dest_dir}")
        except Exception as e:
            print(f"[WARNING] Failed to install {filename}: {e}")

    # Update man database once at the end
    try:
        if shutil.which("mandb"):
            subprocess.check_call(["sudo", "mandb", "-q"])
        print(f"[SETUP] Man database updated successfully.")
    except Exception as e:
        print(f"[WARNING] Could not update man database: {e}")

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

def setup_guga_tool():
    """Configure guga_push.py permissions and create global symlink."""
    print("[SETUP] Configuring GuGa notification tool...")
    
    # Path to the source script
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guga_push.py")
    if not os.path.exists(script_path):
        print(f"[ERROR] guga_push.py not found at {script_path}")
        return

    # Make executable
    print(f"[SETUP] Setting executable permission for {script_path}")
    os.chmod(script_path, 0o755)

    # Global symlink
    link_path = "/usr/local/bin/guga"
    print(f"[SETUP] Attempting to create global symlink: {link_path} -> {script_path}")
    
    # Use sudo if necessary for /usr/local/bin
    try:
        # ln -sf to overwrite any existing link
        subprocess.check_call(["sudo", "ln", "-sf", script_path, link_path])
        print(f"[SETUP] Successfully linked 'guga' to {link_path}")
    except Exception as e:
        print(f"[WARNING] Failed to create global symlink (requires sudo): {e}")
        print(f"To do this manually, run: sudo ln -sf {script_path} {link_path}")

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
    setup_guga_tool()
    setup_man_page()
    
    print("\n" + "="*40)
    print("  SUCCESS: Environment is ready!")
    print("  Run the server with: python server.py")
    print("="*40 + "\n")
