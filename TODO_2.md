# GuGa Nexus — Unified Task List

> [!CAUTION]
> **Identified Vulnerability**: Browser isolation is currently device-scoped via `localStorage`. Every new session ID should ideally be paired and trusted independently before being matched with a device ID to prevent unauthorized access from new tabs in shared environments.

This list combines the original roadmap requirements with unique codebase fixes and optimizations identified during development.

## 🟩 Achieved (Completed)

- [x] **Phase 20.1: Client-Generated PIN Flow** — App and Browser now originate the PIN; Server stages it in `pending_pairings`.
- [x] **Phase 20.1: Interactive Approval** — `guga --approve` and `guga --approve --watch` are fully functional in the CLI.
- [x] **Phase 21.1: `guga --reload`** — CLI can now restart the daemon and show the new QR/URL in one step.
- [x] **Phase 21.2: Status & URL Management** — `guga --status` and `guga --url` are implemented and provide real-time connection info.
- [x] **Phase 21.2: Uninstaller** — `guga --uninstall` handles service removal, man pages, and config cleanup.
- [x] **Private Command Replies** — Replies to chat commands are now sent only to the requesting session ID, not broadcasted to all.
- [x] **Title Alias** — `-f` and `--from` are correctly wired as aliases for `--title`.
- [x] **Core Dependencies** — `aiohttp`, `flask-socketio`, and `eventlet` are unified across `requirements.txt` and `pyproject.toml`.

---

## 🟦 Outstanding (To Do)

### High Priority: Stability & Security
- [ ] **Cloudflare Timeout** — Update `start_cloudflare_tunnel()` in `daemon.py` to time out after 30s instead of blocking indefinitely if the URL isn't found.
- [ ] **Alerta Log Rotation** — Implement `RotatingFileHandler` in `alerter.py` to prevent `~/.guga/alerter.log` from growing indefinitely.
- [ ] **Config Caching** — Cache `trusted_devices.json` in memory in `daemon.py` to avoid expensive disk I/O on every WebSocket event.
- [ ] **Phase 20.3: Security Toggle** — Implement `REQUIRE_PAIRING=false` in `.env` and installer to allow frictionless setup on trusted networks.

### Phase 20: Extension System
- [ ] **Phase 20.0: Extension Infrastructure** — Build `extension_loader.py` and move OS Notifications into `extensions/os-notifications/`.
- [ ] **Dynamic Dependency Loading** — Allow `pyproject.toml` to dynamically reference `requirements.txt` to avoid package duplication.

### Phase 21: Enhanced Interaction
- [ ] **Phase 21.3: Granular Phased Install** — Refactor `installer.py` into the 9-phase check/skip flow (Detect Sudo, Check Systemd, check Venv, etc.).
- [ ] **Phase 21.4: Real Chat Shell** — Replace the `process_command` placeholder with actual subprocess execution (requires `FEATURE_CHAT_SHELL` security flag).
- [ ] **Phase 21.4: `--ask-user`** — Implement the blocking CLI prompt that waits for a response from the phone.

### Phase 22-24: Connectivity & Features
- [ ] **Phase 22: `guga --listen`** — Create the CLI-exclusive receiver so Linux machines can receive notifications from other GuGa servers.
- [ ] **Phase 23: Permanent Tunnels** — Add support for `cloudflare-named` (permanent URLs) and `frp` (self-hosted privacy mode).
- [ ] **Phase 23: `--awake`** — Add the `systemd-inhibit` wrapper to prevent sleep during long-running watched jobs.
- [ ] **Phase 24: `guga --screenshot`** — Add desktop screen capture forwarding to the phone.

---

## ⚠️ Known Implementation Bugs
- [ ] **Platform Guard Placement**: `installer.py` currently exits at import time on non-Linux systems. Move this check inside the function to allow cross-platform testing/doc building.
- [ ] **Version Drift**: `pyproject.toml` and `guga/__init__.py` versions must be manually synced. Need to move to `importlib.metadata` for single-source-of-truth.