<p align="center">
  <img src="https://raw.githubusercontent.com/PositiveMatician/GuGa-Nexus/latest/app-stable/app/src/main/assets/logo.png" width="128" height="128" />
</p>

<h1 align="center">GuGa Nexus</h1>

<p align="center">
  Send your Linux terminal and OS notifications straight to your Android.<br/>
  No cloud. No subscription. No port forwarding.
</p>

<p align="center">
  <a href="https://pypi.org/project/GuGa/">
    <img src="https://img.shields.io/pypi/v/GuGa.svg" alt="PyPI Version" />
  </a>
  <img src="https://img.shields.io/badge/platform-Linux-lightgrey" alt="Platform" />
  <img src="https://img.shields.io/badge/encryption-AES--256--GCM-green" alt="Encryption" />
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License" />
</p>

🔗 [View the full Open Source Repository on GitHub](https://github.com/PositiveMatician/GuGa-Nexus)

---

**GuGa Nexus** is a minimalist, privacy-focused ecosystem that bridges your Linux machine and your Android device. It uses end-to-end AES-256-GCM encryption and works strictly over your own local network or a direct Cloudflare Tunnel—never storing your data on a third-party server.

- **Waiting for a long script to finish?** Get notified the moment it's done.
- **Training a model overnight?** Wake up to the final accuracy line in your notification.
- **SSHed into a remote server?** GuGa reaches your phone over the internet seamlessly.

---

## Installation

GuGa is distributed strictly as a standard Python module via PyPI.

1. **Install the package:**
2. **Initialize the background daemon:**
```bash
guga --install-service
```
*(This interactive setup will cleanly provision your systemd daemon and configure your network routing. Afterwards, your QR code will be generated).*

3. **Reconfiguring:**
If you ever need to change your connection mode or notification settings later, simply run:
```bash
guga --install-service --reconfigure
```
*(This will re-run the interactive setup and update your background daemon).*

4. **Install the Android App:**
Download the `stable` Android APK from the [GitHub Releases Page](https://github.com/PositiveMatician/GuGa-Nexus/releases) and scan the QR code printed in your terminal!

---

## 🚀 Examples & Usage

Once deployed, the `guga` command-line utility is globally available on your terminal. It's designed to automatically detect whether you want to send a plain text notification, or if you want it to execute and watch a long-running process on your behalf.

### 1. Plain Notifications (Message Mode)
Send simple text updates directly to your Android device.

```bash
# Push a simple message
guga "Build finished successfully ✅"

# You can also stream output into it via stdin!
echo "Database migration complete" | guga
```

### 2. Process Watching (Run Mode)
Put `guga` in front of any command. It will execute the command natively while streaming the output to your terminal just as normal. Once the command finishes, it will instantly notify your phone with the **Elapsed Time**, **Exit Status**, and the **Last Console Line**.

```bash
# Get notified when training finishes
guga python train_model.py --epochs 100

# Compile code and get notified if it succeeded or crashed
guga make build-project

# Add custom labels to your notifications for clarity
guga -r ./deploy.sh --title "Production Server"
```

---

## Post-Install Utilities

If you need to view your pairing credentials or manage your background daemon after installation, GuGa provides several utility commands:

```bash
guga --qr                             # Show the pairing QR code
guga --show-pin                       # Show the secure Zero-Trust PIN
guga --install-service --reconfigure  # Re-run the interactive setup
guga --version                        # Show the current version
guga --uninstall                      # Remove all GuGa system components
```

To control the Linux backend server explicitly:
```bash
sudo systemctl start guga       # Start the server daemon
sudo systemctl stop guga        # Stop the server daemon
journalctl -u guga -f           # View live server connection logs
```

---

## Core Features & Architecture

* **Terminal Tracking:** Push notifications to Android via the `guga` global CLI.
* **System OS Monitoring:** Automatically intercepts DBus to forward your native Linux desktop notifications straight to your phone.
* **Zero-Trust Coupling:** Cryptographically secure pairing logic relying strictly on visual QR transmission + 8-Digit PINs (No OAuth or cloud-accounts required).
* **Network Versatility:** Operates flawlessly in **LAN-only mode** strictly over local WiFi, or seamlessly hooks into Cloudflared to grant you **Internet-anywhere access** without needing to own a domain or configure port-forwarding.