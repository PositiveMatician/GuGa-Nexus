<p align="center">
  <img src="app-stable/app/src/main/assets/logo.png" width="128" height="128" />
</p>

<h1 align="center">GuGa Nexus</h1>

<p align="center">
  Send your Linux terminal and OS notifications straight to your Android. No cloud. No subscription. No port forwarding.
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

## What is GuGa Nexus?

GuGa Nexus is a minimalist, privacy-focused ecosystem that bridges your Linux machine and your Android device — without touching any third-party cloud infrastructure.

- **Stuck waiting for a long script to finish?** Get notified the moment it's done.
- **Training a model overnight?** Wake up to the final accuracy line in your notifications.
- **Running jobs on a remote server over SSH?** GuGa reaches your phone over the internet via Cloudflare Tunnel — no domain, no VPS needed.

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

## Project Structure

```
GuGa-Nexus/
├── app-stable/    # Stable Android app (recommended for most users)
├── app-dev/       # Dev build — experimental features including wake-word detection
└── server/        # Python/Flask backend that runs on your Linux machine
```

---

## Quick Start

### 1. 🖥️ Linux Server

```bash
cd server
python3 setup.py      # installs dependencies and system tools
python3 server.py     # starts the server
```

Once running, your terminal will display a **QR code**, an **8-digit PIN**, and a **Cloudflare Tunnel URL** for remote access.

### 2. 📲 Android App

Download and sideload the APK:

- **[Stable release (v1.0.1)](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/v1.0.1)** — recommended for daily use
- **[Nightly build (beta)](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/nightly)** — experimental, includes wake-word work in progress

> ⚠️ Do not build from source unless you are contributing to the project.

### 3. Pair

1. Open the GuGa app and tap the **Settings arrow** (`>`)
2. Tap **SCAN QR** and scan the code from your terminal, or enter the IP manually
3. Enter the **8-digit PIN** to complete the Zero-Trust handshake
4. Status changes to **LIVE SYNC ACTIVE** — you're connected

For background persistence, enable **LIVE PERSISTENCE** in settings.

---

## `guga` — Terminal Notifications CLI

`guga` is a lightweight CLI tool that sends notifications from your terminal to your Android. No extra dependencies beyond the standard library.

### Install

```bash
chmod +x server/guga_push.py
sudo ln -s "$(pwd)/server/guga_push.py" /usr/local/bin/guga
```

### Usage

```bash
# Send a plain message
guga "Build finished ✅"

# Pipe from any command
echo "Deploy done" | guga

# Watch a command — notifies with exit status, elapsed time, and last output line
guga python train.py --epochs 100
guga calc maintenance.cobol
guga ./deploy.sh

# Force message mode (never executes, even if arg looks like a command)
guga -m "python train.py"

# Force run mode with a quoted string
guga -r "sleep 5"

# Label notifications by machine (useful when SSHed into multiple servers)
guga -r ./job.sh --title "GPU Server"

# Suppress guga output in scripts
guga python train.py --silent
```

When watching a command, the notification you receive looks like:

```
✅ python train.py done — 2h 14m
Epoch 100/100 — accuracy: 0.9431
```

### Help

```bash
guga --help
man guga        # after installing the man page
tldr guga       # after installing the tldr page
```

**Install the man page:**
```bash
sudo cp server/man/guga.1 /usr/local/share/man/man1/guga.1
sudo mandb
```

---

## OS Notification Forwarding

GuGa automatically listens to your Linux desktop's notification bus (D-Bus) and forwards system notifications to your Android in real time — app alerts, calendar reminders, build system popups, anything your OS surfaces.

No configuration needed. It runs alongside the server automatically.

---

## Internet Access via Cloudflare Tunnel

GuGa uses Cloudflare Tunnel to make your local server reachable over the internet — so your phone can receive notifications even when you're away from home, or when you're SSHed into a remote machine.

**No domain purchase. No port forwarding. No VPS.** The only requirement is that the server stays running and the app paired — if the server restarts, you'll need to re-scan the QR code.

---

## Security

- All communication is encrypted with **AES-256-GCM**
- Initial pairing uses a **Zero-Trust** QR + PIN handshake — no credentials are ever stored in plaintext
- The `/send` route only accepts connections from **localhost**, so the server cannot be abused remotely

---

## License

MIT License — free to use, fork, and contribute.

---

## Contributing

Issues, feature requests, and pull requests are welcome. If you're testing the beta build or have feedback on the urgency filtering roadmap, open a Discussion.