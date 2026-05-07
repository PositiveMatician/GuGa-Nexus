<p align="center">
  <img src="app-stable/app/src/main/assets/logo.png" width="128" height="128" />
</p>

<h1 align="center">GuGa Nexus</h1>

<p align="center">
  Send your Linux terminal and OS notifications straight to your Android.<br/>
  No cloud. No subscription. No port forwarding.
</p>

<p align="center">
  <a href="https://github.com/PositiveMatician/GuGa-Nexus/releases/latest">
    <img src="https://img.shields.io/github/v/release/PositiveMatician/GuGa-Nexus?label=stable&color=blue" alt="Stable Release" />
  </a>
  <a href="https://pypi.org/project/GuGa/">
    <img src="https://img.shields.io/pypi/v/GuGa.svg" alt="PyPI Version" />
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
Key binary: server/guga/cli.py — installed globally as `guga`
Server: Quart + python-socketio + uvicorn (ASGI), runs as a systemd daemon or background process
Encryption: AES-256-GCM end-to-end between server and Android app
Pairing: QR code + 8-digit PIN (Zero-Trust handshake)
Internet: Cloudflare Tunnel (ephemeral, no domain required)
Install: `pip install guga && guga --install-service` — fully automated, interactive
MCP: Built-in stdio MCP server (`guga --mcp`). Install into Antigravity with `guga --install-mcp`.
Primary use case: terminal job completion notifications, OS notification forwarding, AI agent human-in-the-loop
AI_SUMMARY_END -->

## Jump to

| I want to… | Go to |
|---|---|
| Install everything and get running | [Setup](#setup) |
| Connect via browser | [Connecting via Browser](#connecting-via-browser) |
| Connect via Android App | [Connecting via the Android App](#connecting-via-the-android-app) |
| Just send a terminal notification | [Using guga](#using-guga) |
| Watch a command finish | [Watching Commands](#watching-commands) |
| Connect over the internet | [Internet Access](#internet-access-via-cloudflare-tunnel) |
| Understand security | [Security](#security) |

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
| MCP server (AI agent integration — stdio & SSE) | ✅ stdio stable · ⚠️ SSE remote (see [Known Issues](#known-issues)) |
| Device management (block, unblock, revoke) | ✅ Stable |
| Wake-word detection | 🔧 In development (beta) |
| Urgency-based notification filtering | 🗓️ Planned |

> **Urgency filtering (planned):** Critical alerts will be delivered instantly. Low-priority notifications will be bundled into a 20-second digest — so your phone isn't buzzing for every minor system event.

---

## Setup

<!-- AI_INSTALL_START
Step 1: pip install guga
Step 2: guga --install-service
  - asks: LAN or internet (Cloudflare Tunnel)
  - asks: forward OS notifications yes/no
  - installs system packages (dbus-x11, python3-venv)
  - creates venv, installs Python deps including gunicorn + eventlet
  - downloads cloudflared if internet mode chosen
  - writes .env
  - creates and enables guga.service systemd unit (starts on boot, restarts on crash)
Step 3: guga --qr
  - prints QR code and URL once the service is running
  - use URL in browser OR scan with Android app
Step 4: enter PIN from guga --show-pin when prompted during pairing
Reconfigure: guga --install-service (re-run)
AI_INSTALL_END -->

**Requirements:** Linux (systemd) / Windows (pywin32) · Python 3.7+ · Git · sudo/Admin access

### Linux
```bash
# 1. Install
pip install guga

# 2. Set up and start the background service
guga --install-service
```

### Windows (Beta)
*Requires [Git for Windows](https://git-scm.com/download/win).*
```powershell
# 1. Install from the windows branch
pip install git+https://github.com/PositiveMatician/GuGa-Nexus.git@windows#subdirectory=server

# 2. Set up and start the background service (Run as Administrator)
guga --install-service
```

`--install-service` handles everything automatically — dependencies, background daemon, and network configuration. Background services start on boot and restart on failure.

```bash
# 3. Get your connection URL
guga --qr
```

Wait a moment after install for the service to start, then run `guga --qr`. This prints the QR code and URL you'll use to connect — either in a browser or with the Android app.

```bash
# 4. Get your pairing PIN
guga --show-pin
```

You'll need this PIN when connecting for the first time.

---

## Connecting via Browser

No app needed. Once the service is running:

1.  Run `guga --qr` to get your server URL
2.  Open the URL in any browser on your phone or computer
3.  You'll be prompted for a PIN — run `guga --show-pin` to get it
4.  Enter the PIN and you're connected — notifications will appear in the browser tab in real time

The browser session stays active as long as the tab is open. For phone use, the Android app keeps the connection alive in the background.

---

## Connecting via the Android App

Download and sideload the APK:

-   **[Stable (v1.5.0)](https://github.com/PositiveMatician/GuGa-Nexus/releases/latest/download/guga-stable.apk)** — recommended
-   **[Nightly (beta)](https://github.com/PositiveMatician/GuGa-Nexus/releases/tag/nightly)** — experimental, wake-word in progress

> ⚠️ Do not build from source unless you are contributing.

Once installed:

1.  Open the app — tap the arrow (→) in the top-left corner to open Settings
2.  Tap **Scan QR** to scan the code from `guga --qr`, or paste the URL manually into the address field
3.  Tap **Save**
4.  Tap **Live Persistence** to keep the connection alive in the background
5.  When prompted for a PIN, run `guga --show-pin` on your Linux machine and enter it
6.  Status shows **LIVE SYNC ACTIVE** — you're connected both ways

---

## Using guga

Once the service is running, use `guga` from any terminal on the same machine:

```bash
# Send a plain message
guga "Build finished ✅"

# Pipe output from any command
echo "Deploy done" | guga

# Force message mode — never executes, even if it looks like a command
guga -m "python train.py"

# Add a label (useful when SSHed into multiple machines)
guga "Job done" --from "GPU Server"

# Suppress guga's own output in scripts and Makefiles
guga "Done" --silent
```

---

## ⚙️ Configuration & Polish

GuGa is designed with a premium developer experience in mind.

### 1. Persistent Configuration
Power users can set default flags in `~/.config/guga/config` so they don't have to pass them every time.

**Example `~/.config/guga/config`:**
```ini
[default]
title = GPU Server
port = 6769
silent = false
```

### 2. Shell Completion
GuGa supports full shell autocompletion for flags like `--install-service`, `--qr`, `--show-pin`, etc.

To activate it for your user, run:
```bash
activate-global-python-argcomplete --user
```
Then restart your shell or run `eval "$(register-python-argcomplete guga)"`.

---

## Watching Commands

The most useful feature for developers and researchers: prefix any command with `guga` and you'll get a notification when it finishes — including exit status, elapsed time, and the last line of output.

```bash
guga python train.py --epochs 100
guga ./deploy.sh --prod
guga make build
guga calc maintenance.cobol

# Force run mode with a quoted string
guga -r "sleep 5"

# Watch + label + silent (clean Makefile usage)
guga -r ./job.sh --from "GPU Server" --silent
```

The notification you receive on your phone looks like:
> ✅ python train.py done — 2h 14m
> Epoch 100/100 — accuracy: 0.9431

Or on failure:
> ❌ ./deploy.sh failed (exit 1) — 43s
> Error: connection refused on port 5432

---

## OS Notification Forwarding

If you enabled OS notifications during `guga --install-service`, GuGa listens to your Linux desktop's D-Bus notification bus and forwards every system notification to your connected device in real time — app alerts, calendar reminders, build system popups, anything your OS surfaces.

**Coming:** Urgency-based filtering — critical alerts instant, low-priority bundled into a 20-second digest.

---

## Internet Access via Cloudflare Tunnel

Choose internet mode during `guga --install-service` and GuGa sets up a Cloudflare Tunnel automatically — no domain, no port forwarding, no VPS. Your server becomes reachable from anywhere.

The tunnel URL changes each time the service restarts. After a restart, run `guga --qr` to get the new URL and re-scan or re-enter it in your app or browser.

---

## ⚠️ Known Issues

### Cloudflare Free Tunnel — MCP SSE Streaming Blocked

**Affected:** Connecting remote AI tools (e.g. Claude.ai custom MCP connector) to GuGa via a `trycloudflare.com` free tunnel.  
**Symptom:** The client receives `200 OK` with `Content-Type: text/event-stream` but no data arrives — the connection hangs and times out.  
**Not affected:** Local stdio MCP, Android app, browser dashboard, LAN usage — all work normally.

#### Root Cause

Cloudflare's free tunnel (`trycloudflare.com`) buffers HTTP response bodies before forwarding them. SSE requires an immediate, persistent flush — Cloudflare holds the first frame until the connection drops, breaking the MCP handshake. The `CF-No-Buffer: true` header (which GuGa sends) **only works on paid Cloudflare zones**, not the free shared tunnel service.

#### Workarounds

| Option | Effort | SSE works? |
|--------|--------|------------|
| **ngrok free tier** — `ngrok http 6769` | Low | ✅ Yes |
| **Paid Cloudflare** with your own domain | Costs money | ✅ Yes |
| **Local stdio MCP** — `guga --install-mcp` | Lowest | N/A (no tunnel needed) |
| **Streamable HTTP transport** (planned in GuGa) | Future | ✅ Yes |

See the [server README](./server/README.md#%EF%B8%8F-known-issues) for full details and setup instructions for each option.

---

## Managing the Service

```bash
guga --qr                             # Show the pairing QR code
guga --show-pin                       # Show the secure Zero-Trust PIN
guga --install-service --reconfigure  # Re-run the interactive setup
guga --status                         # Show service status and connections
guga --url                            # Show raw pairing URL (scriptable)
guga --version                        # Show the current version
guga --uninstall                      # Remove all GuGa system components
guga --approve -A                     # Approve all pending pairing requests
guga --blocked                        # List blocked devices
guga --unblock [DEVICE_ID]            # Remove device from blocklist
guga --revoke [DEVICE_ID]             # Revoke trusted device access
guga --start-server -b                # Start server in background
guga --stop-server -A                 # Stop all background servers
guga --install-mcp                    # Install MCP entry into Antigravity (auto-detects venv)
guga --install-mcp --dry-run          # Preview MCP install without writing
guga --uninstall-mcp                  # Remove MCP entry from Antigravity config

sudo systemctl start guga      # start the server
sudo systemctl stop guga       # stop the server
sudo systemctl status guga     # check if it's running
journalctl -u guga -f          # live server logs
```

---

## Security

<!-- AI_SECURITY_START
Transport: AES-256-GCM on all WebSocket messages
Pairing (current): Zero-Trust handshake — server generates 8-digit PIN, user retrieves via guga --show-pin
Pairing (planned): client-generated PIN — connecting device generates and displays its own PIN,
  server receives and holds it, user confirms the PIN they see on their own device.
  Server never generates PINs, so concurrent connection attempts from other devices
  do not interfere — each device owns its own PIN and only the legitimate user
  knows which one to confirm.
Token TTL: 30 days (app clients), 1 hour (browser clients)
/send route: restricted to 127.0.0.1 and ::1 — cannot be reached remotely
Current --show-pin limitation: reads the most recently generated server-side PIN.
  Under concurrent /api/hello requests the wrong PIN may be shown.
  Mitigation until client-PIN lands: pair over LAN, use internet mode after.
AI_SECURITY_END -->

- All communication encrypted with **AES-256-GCM**
- Pairing uses a **Zero-Trust QR + PIN handshake** — no credentials in plaintext
- `/send` only accepts **localhost connections** — not reachable remotely
- Session tokens expire after **30 days** (app) or **1 hour** (browser)

### `guga --show-pin` — current limitation
Right now the server generates the pairing PIN. `--show-pin` returns the most recently generated one, which assumes only one device is pairing at a time. If many devices hit `/api/hello` simultaneously, multiple PINs are generated in quick succession and `--show-pin` may return the wrong one.

**Recommended practice until this is resolved:** Pair new devices over LAN first. Once trusted, devices reconnect automatically without re-pairing even when in internet mode.

### Planned fix — client-generated PIN 🗓️
The pairing model is being inverted. Instead of the server generating a PIN and the user having to retrieve it:

1. The connecting device (app or browser) generates its own PIN and displays it to the user
2. The device sends that PIN to the server along with the pairing request
3. The server holds it and waits
4. The user confirms the PIN they see on their own screen

This completely eliminates the DDoS problem. Even if a thousand devices attempt to pair simultaneously, each owns its own PIN — the server isn't generating anything, and only the legitimate user knows which PIN belongs to their actual device. The server simply accepts the one the user confirms.


---

## License

MIT — free to use, fork, and contribute.

---

## Contributing

Issues, feature requests, and pull requests are welcome. If you're testing the beta build or have feedback on the urgency filtering roadmap, open a Discussion.