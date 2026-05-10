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

GuGa is distributed via PyPI for Linux and via Git for the Windows beta.

### Linux
```bash
pip install guga
guga --install-service
```

### Windows (Beta)
Requires [Git](https://git-scm.com/download/win).
```powershell
pip install git+https://github.com/PositiveMatician/GuGa-Nexus.git@windows#subdirectory=server
# Run in Administrator terminal:
guga --install-service
```

*(This interactive setup will cleanly provision your background service (systemd or Windows Service) and configure network routing).*

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

# Send to a specific tagged device (e.g. "nexus")
guga --send-to nexus "Build complete"
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

## Post-Install Utilities

If you need to view your pairing credentials or manage your background daemon after installation, GuGa provides several utility commands:

```bash
guga --qr                             # Show the pairing QR code
guga --rename-device                  # Assign a custom tag to a device
guga --approve                        # Interactively approve pairing requests
guga --approve -A                     # Approve all pending requests non-interactively
guga --blocked                        # List blocked devices
guga --unblock [DEVICE_ID]            # Remove a device from the blocklist
guga --revoke [DEVICE_ID]             # Revoke a trusted device's access
guga --install-service --reconfigure  # Re-run the interactive setup
guga --status                         # Show service status and connections
guga --url                            # Show raw pairing URL (scriptable)
guga --version                        # Show the current version
guga --uninstall                      # Remove all GuGa system components
```

### 🤖 AI Agent Integration (MCP)
GuGa provides a built-in **Model Context Protocol (MCP)** server, allowing AI agents like Claude Desktop or Antigravity to send notifications and ask you questions directly on your phone.

#### Local AI (Antigravity / Claude Desktop) — Recommended Setup
Run this once to automatically configure the MCP entry in `~/.gemini/antigravity/mcp_config.json`:
```bash
guga --install-mcp
```
This auto-detects the correct Python interpreter (prefers your active virtualenv), verifies all required packages are installed, and writes the entry. Preview without writing:
```bash
guga --install-mcp --dry-run
```
To remove the entry later:
```bash
guga --uninstall-mcp
```

If you prefer to configure manually, the entry uses **stdio transport** (not SSE/url):
```json
{
  "mcpServers": {
    "guga": {
      "command": "/path/to/venv/bin/python3",
      "args": ["-m", "guga.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/server"
      }
    }
  }
}
```
> [!IMPORTANT]
> Antigravity's MCP client only supports **stdio** (`command`/`args`) transport, not SSE (`url`). Always use the `command` form.

After installing, click **Refresh** in the Antigravity MCP panel.

#### Remote AI (Custom Tools / GPT Actions / SSE)
For remote access (e.g., calling your GuGa tools from a Custom GPT or a remote server), use the **SSE Transport** with JWT security.

1. **Start the server in Public Mode**:
   Ensure your GuGa server is exposed via Cloudflare Tunnel:
   ```bash
   MODE=public guga --start-server
   ```
2. **Generate a JWT Access Token**:
   Tokens are signed using a persistent secret in `~/.guga/.env`. Generate one for your remote tool:
   ```bash
   guga --mcp-token
   ```
3. **Configure your Remote Tool**:
   - **SSE Endpoint**: `https://<your-tunnel-url>.trycloudflare.com/mcp/sse`
   - **Method**: `GET` (for SSE stream) and `POST` (for sending JSON-RPC messages to `/mcp/messages`).
   - **Authentication**: All requests must include the `Authorization` header:
     ```http
     Authorization: Bearer <your-generated-token>
     ```
   - **Note**: The token is also accepted via a query parameter `?token=<token>` for clients that struggle with headers on SSE.

> [!SECURITY]
> Your JWT secret is unique to your machine. Anyone with the token can send notifications or ask questions to your phone. Keep your Cloudflare URL and token secure.

> [!NOTE]
> **Browser client isolation:** Browser clients authenticate using a `device_id` + `token` pair stored in the browser's localStorage. Any tab (on the same origin or otherwise) that obtains these two values can connect as that device — there is no per-session or per-tab re-verification. This is an acceptable trade-off for a personal tool, but it means your token is the only secret protecting access. Do not share your server URL with untrusted parties, and use `guga --revoke` to rotate credentials if you suspect exposure.

---

## ⚠️ Known Issues

### Cloudflare Free Tunnel — SSE Streaming Buffered

**Affected:** Remote MCP SSE access via `trycloudflare.com` free tunnels.  
**Symptom:** The MCP client (e.g. Claude.ai custom connector) gets a `200 OK` with `Content-Type: text/event-stream` but receives **no data** — the connection hangs and eventually times out.  
**Not affected:** Local stdio MCP (`guga --mcp`), LAN access, Android app, browser dashboard — all work normally.

#### Root Cause

Cloudflare's free tunnel service (`trycloudflare.com`) buffers HTTP response bodies before forwarding them to the client. Server-Sent Events rely on a persistent, flushed stream — the first `event: endpoint` frame must arrive immediately. Cloudflare holds this frame until the connection closes, which breaks the MCP handshake.

The standard nginx workaround (`X-Accel-Buffering: no`) and the Cloudflare-specific header (`CF-No-Buffer: true`) are both sent by GuGa, but **`CF-No-Buffer` only disables buffering on paid Cloudflare zones** — it has no effect on the free `trycloudflare.com` tunnel service.

#### Workarounds

**Option A — Use ngrok instead of Cloudflare (recommended for SSE)**

ngrok's free tier streams SSE correctly. Replace the Cloudflare tunnel:
```bash
# Install ngrok: https://ngrok.com/download
ngrok http 6769
# Use the https://xxxx.ngrok-free.app URL as your MCP endpoint
```
Then connect your remote tool to:
```
https://xxxx.ngrok-free.app/mcp/sse?token=<your-jwt>
```

**Option B — Paid Cloudflare (if you own a zone)**

If you have a Cloudflare account with a registered domain, assign it to the tunnel via `cloudflared tunnel route dns`. On a proper Cloudflare zone, `CF-No-Buffer: true` takes effect and SSE streams correctly.

**Option C — Local stdio MCP only**

For personal AI assistants running on the same machine (Antigravity, Claude Desktop), the **stdio transport** is both simpler and more reliable than SSE:
```bash
guga --install-mcp   # writes the correct stdio entry to mcp_config.json
```
No tunnel, no token, no buffering issues.

**Option D — Future: Streamable HTTP transport (planned)**

The MCP spec now supports a `streamable-http` transport that uses standard HTTP POST/response pairs instead of a persistent SSE stream. This is Cloudflare-compatible and will be added to GuGa in a future release as the preferred remote transport.

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