<p align="center">
  <img src="app-stable/app/src/main/assets/logo.png" width="128" height="128" />
</p>

<h1 align="center">GuGa Nexus</h1>

<p align="center">
  Send your Linux terminal and OS notifications straight to your Android.<br/>
  No cloud. No subscription. No port forwarding.
</p>

<p align="center">
  <a href="https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/v1.0.1">
    <img src="https://img.shields.io/badge/stable-v1.0.1-blue" alt="Stable Release" />
  </a>
  <a href="https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/nightly">
    <img src="https://img.shields.io/badge/nightly-beta-orange" alt="Nightly Build" />
  </a>
  <img src="https://img.shields.io/badge/platform-Linux-lightgrey" alt="Platform" />
  <img src="https://img.shields.io/badge/encryption-AES--256--GCM-green" alt="Encryption" />
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License" />
</p>

---

<!-- AI_SUMMARY_START
Project: GuGa Nexus
Type: Linux-to-Android notification bridge
Language: Python (server), Java (Android)
Key binary: server/guga_push.py — installed globally as `guga`
Server: Flask + Socket.IO + gunicorn + eventlet, runs as a systemd daemon
Encryption: AES-256-GCM end-to-end between server and Android app
Pairing: QR code + 8-digit PIN (Zero-Trust handshake)
Internet: Cloudflare Tunnel (ephemeral, no domain required)
Install: `pip install guga && guga --install-service` — fully automated, interactive
Primary use case: terminal job completion notifications, OS notification forwarding
AI_SUMMARY_END -->

## Jump to

| I want to… | Go to |
|---|---|
| Install everything and get running | [Installation](#installation) |
| Just send a terminal notification | [guga CLI](#guga--terminal-notifications-cli) |
| Understand what this does | [What is GuGa Nexus?](#what-is-guga-nexus) |
| See what features exist | [Features](#features) |
| Connect over the internet (not just LAN) | [Cloudflare Tunnel](#internet-access-via-cloudflare-tunnel) |
| Contribute or report a bug | [Contributing](#contributing) |

---

## What is GuGa Nexus?

GuGa Nexus is a minimalist, privacy-focused ecosystem that bridges your Linux machine and your Android device — without touching any third-party cloud infrastructure.

- **Waiting for a long script to finish?** Get notified the moment it's done.
- **Training a model overnight?** Wake up to the final accuracy line in your notification.
- **SSHed into a remote server?** GuGa reaches your phone over the internet via Cloudflare Tunnel — no domain, no VPS needed.

---

## Features

| Feature | Status |
|---|---|
| Terminal → Android push notifications via `guga` CLI | ✅ Stable |
| OS notification forwarding (D-Bus) | ✅ Stable |
| End-to-end encryption (AES-256-GCM) | ✅ Stable |
| Zero-Trust QR + PIN pairing | ✅ Stable |
| Internet access via Cloudflare Tunnel (no domain required) | ✅ Stable |
| Remote command execution from phone | ✅ Stable |
| Wake-word detection | 🔧 In development (beta) |
| Urgency-based notification filtering | 🗓️ Planned |

> **Urgency filtering (planned):** Critical alerts will be delivered instantly. Low-priority notifications will be bundled into a 20-second digest — so your phone isn't buzzing for every minor system event.

---

## Installation

<!-- AI_INSTALL_START
Prerequisites: Linux, Python 3, pip, sudo access
Installation mapping: `pip install guga` or `pip install .` from source
System configuration task: `guga --install-service`
What `--install-service` does automatically:
  - Detects distro and ensures native system DBus dependencies
  - Downloads cloudflared binary if internet mode is chosen
  - Writes ~/.guga/.env with user-chosen configuration
  - Creates a systemd service (guga.service) that starts on boot and restarts on crash
  - Installs the man page at /usr/local/share/man/man1/guga.1
  - Prints the pairing QR code immediately on completion
Reconfigure: `guga --install-service --reconfigure`
Reprint QR:  `guga --qr`
Reprint PIN: `guga --show-pin`
AI_INSTALL_END -->

### Requirements

- Linux (any distro with systemd)
- Python 3.7+
- `sudo` access (for systemd service and global CLI install)
- An Android device to sideload the APK

### 1. Install via pip

GuGa is distributed as a standard Python module. You can install it natively via pip, although cloning the repository is still completely supported!

**Standard installation:**
```bash
pip install guga
guga --install-service
```

**(Optional) Installing from source:**
```bash
git clone https://github.com/PositiveMatician/GuGa-Nexus.git
cd GuGa-Nexus/server
pip install .
guga --install-service
```

`--install-service` will ask two questions, then configure your system automatically:

```
How will you connect?
  1)  LAN only   — phone must be on the same Wi-Fi
  2)  Internet   — anywhere, via Cloudflare Tunnel (no domain needed)

Forward OS notifications to your phone? [y/N]
```

It then sets up a background systemd daemon in your OS and prints the pairing QR code. **You will not need to run it again** — the server correctly handles its own startup during boot.

### 2. Install the Android app

Sideload the APK onto your Android device:

- **[Stable (v1.0.1)](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/v1.0.1)** — recommended for daily use
- **[Nightly (beta)](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/nightly)** — experimental, includes wake-word work in progress

> ⚠️ Do not build from source unless you are contributing to the project.

### 3. Pair

1. Open the GuGa app → tap the **Settings arrow** (`>`)
2. Tap **SCAN QR** and scan the code printed in your terminal
3. Enter the **8-digit PIN** shown on screen to complete pairing
4. Status changes to **LIVE SYNC ACTIVE** — you're connected

> Enable **LIVE PERSISTENCE** in app settings to keep the connection alive in the background.

### Post-install commands

```bash
sudo systemctl start guga       # start the server
sudo systemctl stop guga        # stop the server
sudo systemctl status guga      # check if it's running
journalctl -u guga -f           # live server logs
guga --qr                       # reprint the pairing QR code
guga --show-pin                          # retrieve the latest pairing PIN
guga --install-service --reconfigure     # change mode or settings
```

---

## `guga` — Terminal Notifications CLI

<!-- AI_GUGA_CLI_START
Binary: /usr/local/bin/guga (symlink → server/guga_push.py)
Language: Python 3, stdlib only — no pip install needed
Server endpoint: POST http://localhost:6769/send
Payload: {"message": "string", "title": "optional string"}
Mode detection (automatic):
  - stdin piped, no args       → message mode
  - single non-executable arg  → message mode
  - first arg is in PATH or is a file → run mode
Explicit flags:
  -m / --message  force message mode (joins all args as a string, never executes)
  -r / --run      force run mode (shlex.splits single quoted string into tokens)
  --server PORT   custom server port (default: 6769)
  --silent        suppress guga's own stdout/stderr
  --title LABEL   label prepended to the Android notification
  --qr            show the pairing QR code natively from anywhere
  --show-pin      retrieve the most recent PIN from daemon logs
Run mode behaviour:
  - streams command stdout+stderr to terminal normally
  - on exit: sends notification with status (✅/❌), elapsed time, last output line
  - exit code mirrors the watched command (transparent in scripts/Makefiles)
  - Ctrl-C sends an ⚠️ interrupted notification
AI_GUGA_CLI_END -->

AI_GUGA_CLI_END -->

`guga` is installed globally via standard `pip`. No additional path configurations are strictly required.

### Usage

```bash
# Send a plain message
guga "Build finished ✅"

# Pipe from any command
echo "Deploy done" | guga

# Watch a command — notifies on completion with exit status, elapsed time, and last output line
guga python train.py --epochs 100
guga ./deploy.sh --prod
guga make build

# Force message mode (never executes, even if the string looks like a command)
guga -m "python train.py"

# Force run mode with a quoted string
guga -r "sleep 5"

# Label the notification by machine — useful when SSHed into multiple servers
guga -r ./job.sh --title "GPU Server"

# Suppress guga's own output in scripts and Makefiles
guga python train.py --silent

# Access pairing utilities from anywhere
guga --qr
guga --show-pin
```

When watching a command, your Android notification looks like:

```
✅ python train.py done — 2h 14m
Epoch 100/100 — accuracy: 0.9431
```

### Help

```bash
guga --help
man guga
```

---

## Project Structure

<!-- AI_STRUCTURE_START
GuGa-Nexus/
  app-stable/                       Android app source — stable (Java)
  app-dev/                          Android app source — beta, wake-word in progress
  server/
    server.py                       Main Flask/SocketIO server entry point
    setup.py                        Automated installer — run this first
    guga_push.py                    CLI tool, installed globally as `guga`
    guga.1                          Man page for guga
    os_notification_alerter.py      D-Bus listener — forwards OS notifications to server
    requirements.txt                Python dependencies
    .env                            Runtime config (auto-created by setup.py)
    cloudflared                     Cloudflare tunnel binary (downloaded by setup.py if needed)
    venv/                           Python venv (created by setup.py)
    trusted_devices.json            Paired device tokens (auto-created at runtime)
AI_STRUCTURE_END -->

```
GuGa-Nexus/
├── app-stable/    # Stable Android app
├── app-dev/       # Dev build — wake-word and experimental features
└── server/
    ├── server.py                    # Flask + Socket.IO backend
    ├── setup.py                     # Automated installer — run this first
    ├── guga_push.py                 # CLI tool, installed globally as `guga`
    ├── guga.1                       # Man page
    └── os_notification_alerter.py   # D-Bus listener for OS notifications
```

---

## OS Notification Forwarding

GuGa listens to your Linux desktop's D-Bus notification bus and forwards system notifications to your Android in real time — app alerts, calendar reminders, build system popups, anything your OS surfaces.

Enable it by answering `y` during `setup.py`. No further configuration needed.

> **Coming:** Urgency-based filtering — critical alerts instant, low-priority bundled into a 20-second digest.

---

## Internet Access via Cloudflare Tunnel

GuGa uses Cloudflare Tunnel to make your local server reachable over the internet with no infrastructure required.

**No domain. No port forwarding. No VPS.** Choose internet mode during `setup.py` and it handles the rest. The only caveat: if the server restarts, the tunnel gets a new URL and you'll need to re-scan the QR code.

```bash
guga --qr   # reprint the current pairing QR
```

---

## Security

<!-- AI_SECURITY_START
Transport: AES-256-GCM on all WebSocket messages
Pairing: Zero-Trust QR + 8-digit PIN handshake
Token storage: trusted_devices.json (hashed, never plaintext)
Token TTL: 30 days (app), 1 hour (browser)
/send route: restricted to 127.0.0.1 and ::1 — not callable remotely
/api/hello and /api/verify_pin: open but require matching PIN from pending_pairings
AI_SECURITY_END -->

- All communication encrypted with **AES-256-GCM**
- Initial pairing uses a **Zero-Trust QR + PIN handshake** — no credentials stored in plaintext
- The `/send` route only accepts **localhost connections** — cannot be reached remotely
- Session tokens expire after **30 days** (app) or **1 hour** (browser)

---

## License

MIT — free to use, fork, and contribute.

---

## Contributing

Issues, feature requests, and pull requests are welcome. If you're testing the beta build or have feedback on the urgency filtering roadmap, open a Discussion.