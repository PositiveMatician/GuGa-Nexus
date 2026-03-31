import os
import sys
import subprocess
import platform
import urllib.request
import shutil

def install_requirements():
    print("[SETUP] Installing Python dependencies...")
    req_file = "requirements.txt"
    if os.path.exists(req_file):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
            print("[SETUP] Dependencies installed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to install dependencies: {e}")
    else:
        print("[SKIP] No requirements.txt found.")

def download_cloudflared():
    print("[SETUP] Checking for cloudflared binary...")
    
    # 1. Check if installed globally
    if shutil.which("cloudflared"):
        print("[SETUP] cloudflared is already installed globally.")
        return

    # 2. Determine OS and Architecture
    os_name = platform.system().lower()
    arch = platform.machine().lower()

    # Normalize architecture names
    if arch in ["x86_64", "amd64"]:
        arch_suffix = "amd64"
    elif arch in ["arm64", "aarch64"]:
        arch_suffix = "arm64"
    else:
        print(f"[ERROR] Unsupported architecture: {arch}")
        return

    # 3. Determine filename and destination
    if os_name == "windows":
        filename = f"cloudflared-windows-{arch_suffix}.exe"
        dest = "cloudflared.exe"
    elif os_name == "darwin":
        filename = f"cloudflared-darwin-amd64.tgz" # MacOS uses different distribution usually, but this is the binary name core logic
        # Actually cloudflared release naming for mac is cloudflared-darwin-amd64.tgz or similar? 
        # No, they have raw binaries too: cloudflared-darwin-amd64
        filename = f"cloudflared-darwin-amd64"
        dest = "cloudflared"
    elif os_name == "linux":
        filename = f"cloudflared-linux-{arch_suffix}"
        dest = "cloudflared"
    else:
        print(f"[ERROR] Unsupported OS: {os_name}")
        return

    # 4. Check if already present locally
    if os.path.exists(dest):
        print(f"[SETUP] Local {dest} already exists.")
        return

    # 5. Download
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{filename}"
    print(f"[SETUP] Downloading {filename} from Cloudflare...")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"[SETUP] Download complete: {dest}")
        
        # 6. Make executable (non-Windows)
        if os_name != "windows":
            os.chmod(dest, 0o755)
            print("[SETUP] Binary permissions set to executable.")
            
    except Exception as e:
        print(f"[ERROR] Download failed: {e}")

def ensure_env_exists():
    env_file = ".env"
    if not os.path.exists(env_file):
        print("[SETUP] Creating default .env file...")
        default_content = (
            "ENABLE_OS_NOTIFICATIONS=True\n"
            "MODE=lan\n"
            "PORT=6769\n"
        )
        try:
            with open(env_file, "w") as f:
                f.write(default_content)
            print("[SETUP] .env file created successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to create .env file: {e}")
    else:
        print("[SKIP] .env file already exists.")

if __name__ == "__main__":
    print("\n" + "="*40)
    print("      GuGa Assistant Server Setup")
    print("="*40 + "\n")
    
    install_requirements()
    download_cloudflared()
    ensure_env_exists()
    
    print("\n" + "="*40)
    print("  SUCCESS: Environment is ready!")
    print("  Run the server with: python server.py")
    print("="*40 + "\n")
