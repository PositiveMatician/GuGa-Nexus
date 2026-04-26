# GuGa Nexus — Development Roadmap

> Phases are written assuming the previous phase was completed successfully.
> The project remains a monolith until Phase 25.
> Last updated: April 2026

---

## Current State (pre-Phase 20)

- Single PyPI package `guga` with CLI and Flask server bundled together
- Server runs as a systemd daemon via `guga --install-service`
- Pairing: server generates 8-digit PIN, user retrieves via `guga --show-pin`
- CLI supports message mode and run mode — `--approve` not yet built
- Browser client and Android app both functional
- AES-256-GCM encryption end to end
- Cloudflare Tunnel for internet access — ephemeral URL changes on every restart
- OS notification forwarding via D-Bus (optional, set during install)
- Single monorepo, single package

---

## Phase 20.0 — Extension Infrastructure

### What we want to achieve

Build a lightweight extension system so users choose what they want during
installation rather than getting everything or nothing. The core ships lean —
server, basic send/receive, CLI — and extensions add capabilities on top.

This phase builds the loader and the install-time selection UI. It adds no
user-facing features itself. Every subsequent phase that adds optional
capability becomes "ship extension X and register it" rather than "modify
the monolith."

### The extension model

Each extension lives in `extensions/<id>/` and contains a `manifest.json`
declaring what it needs and provides, plus optional Python files.

```json
// extensions/os-notifications/manifest.json
{
  "id": "os-notifications",
  "name": "OS Notification Forwarding",
  "description": "Forwards Linux desktop notifications to your device via D-Bus",
  "system_deps": ["dbus-x11"],
  "pip_deps": [],
  "env_flags": { "ENABLE_OS_NOTIFICATIONS": "true" },
  "app_features": [],
  "server_module": "os_notification_alerter.py"
}
```

```json
// extensions/shell/manifest.json
{
  "id": "shell",
  "name": "Chat Shell",
  "description": "Run commands on your Linux machine from the app chat",
  "system_deps": [],
  "pip_deps": [],
  "env_flags": { "FEATURE_CHAT_SHELL": "true" },
  "app_features": ["chat_shell"],
  "server_module": null
}
```

### Installation experience

```
  GuGa Core installed.

  Available extensions:
  ─────────────────────────────────────────────────────
  1) OS Notification Forwarding    forward Linux desktop notifications
  2) Chat Shell                    run commands from your phone
  3) Interactive Input             forward prompts via PTY (installs pexpect)
  4) Screenshot                    capture and send screen to phone
  5) MCP Server                    use GuGa as an AI agent skill
  6) LAN Discovery                 auto-discover server on local network
  ─────────────────────────────────────────────────────
  Select extensions [1,2 / all / none]:
```

Each selected extension runs its own capability check before installing.

### Changes to the project

**New directory: `extensions/`**
- One subfolder per extension with `manifest.json`
- Existing OS notification feature migrated into `extensions/os-notifications/`

**New file: `extension_loader.py`**
- Reads all `manifest.json` files on startup
- Presents the selection menu during `--install-service`
- Per extension: runs capability checks, installs pip deps, installs system
  deps, writes env flags, registers server module
- Writes `installed_extensions.json` — the record of what is active

**CLI additions**
- `guga --list-extensions` — shows installed and available extensions
- `guga --add-extension <id>` — installs a single extension post-setup
- `guga --remove-extension <id>` — removes extension, cleans env flags
- After add/remove: prompts user to run `guga --reload` to apply

**Server startup**
- Reads `installed_extensions.json`, imports and registers active server modules
- Missing module logs a warning but does not crash the server

### How the project changes

The project becomes composable. A researcher who only wants job notifications
installs core only. A power user who wants everything selects all. Install time
is proportional to what the user actually needs. All future optional features
become extension registrations rather than changes to the monolith.

### Potential problems

- **Keep the loader dead simple** — no hot-reloading, no versioning, no
  dependency resolution between extensions. A manifest is a JSON file. The
  loader reads it, installs deps, writes flags. That is all it does.
- **Migration of existing features** — if `ENABLE_OS_NOTIFICATIONS=true` is
  already in `.env`, treat `os-notifications` as installed without re-running
  its setup.
- **`installed_extensions.json` drift** — if an extension is manually removed
  from the filesystem, the server warns on startup. Suggest
  `guga --list-extensions` to reconcile.

---

## Phase 20.1 — Client-Generated PIN + `guga --approve`

### What we want to achieve

Replace the server-generated PIN pairing model entirely. The server currently
generates the PIN which the user retrieves via `guga --show-pin`. This breaks
under concurrent connection attempts — `--show-pin` only returns the most
recent PIN, which may not belong to the user's device.

The new model: the connecting device generates its own PIN, displays it to the
user, and sends it to the server. The user approves or rejects pending requests
interactively via `guga --approve`.

### Changes to the project

**Server (`server.py`)**
- `POST /api/hello` no longer generates PINs — accepts `pin` and `device_name`
  from the client. Rejects requests without a `pin` with 400.
- New `GET /api/pending` — returns up to 5 pending pairing requests,
  localhost only
- New `POST /api/approve` — approves or rejects a specific device,
  localhost only
- Pending pairings expire after 5 minutes automatically
- 5 failed `verify_pin` attempts blocklists the device for 10 minutes
- `blocked_devices` dict added alongside `pending_pairings`

**CLI (`guga_push.py`)**
- `guga --show-pin` removed entirely
- `guga --approve` added — lists pending requests, handles A/R/number input
- `guga --approve --watch` added — polls in real time, prompts as requests arrive

**Android app**
- Generates PIN locally with `SecureRandom` before calling `/api/hello`
- Displays PIN prominently: "Show this PIN to your Linux machine"
- Sends `device_name` (Build.MODEL) in the request
- Shows waiting screen: "run `guga --approve` on your machine"

**Browser client**
- Generates PIN with `crypto.getRandomValues`
- Displays PIN in a clearly visible box during pairing
- Sends `device_name` derived from `navigator.userAgent`
- Auto-proceeds once approved — no manual PIN entry needed

### How the project changes

Pairing becomes significantly more intuitive. The user sees the PIN on their
own device. `guga --approve` gives a clear view of what is trying to connect.
The DDoS interference problem is eliminated. `--show-pin` disappears entirely.

### Potential problems

- **`--watch` mode terminal interaction** — keeping a prompt open while printing
  new requests requires careful stdout flushing. Test on multiple terminal
  emulators.
- **App waiting screen** — poll `POST /api/verify_pin` every 3 seconds until it
  succeeds. Do not hammer the server.
- **Browser UA parsing** — keep it simple. "Firefox on Linux" is enough.
- **Blocklist not persisted** — `blocked_devices` is in memory. Lost on restart.
  Acceptable for now.

---

## Phase 20.3 — Security Off Toggle

### What we want to achieve

Add a `REQUIRE_PAIRING=false` option in advanced settings during
`--install-service`. When disabled, any device that scans the QR code connects
immediately without the PIN flow. Designed for users on trusted networks who
find pairing friction unnecessary.

### Changes to the project

**`.env`**
- New variable: `REQUIRE_PAIRING=true` (default)

**`--install-service` advanced config**
- "Require pairing PIN for new devices? (recommended) [Y/n]"
- If no: sets `REQUIRE_PAIRING=false`, shows a clear warning

**Server (`server.py`)**
- If `REQUIRE_PAIRING=false`:
  - `POST /api/hello` immediately issues a session token, no PIN stored
  - `POST /api/verify_pin` returns success without checking anything
  - `GET /api/pending` returns empty
- Server prints a visible warning on every startup:
  ```
    ⚠  PAIRING DISABLED — any device can connect
       Recommended only on trusted networks
  ```
- Warning also logged to journald so it appears even when nobody is watching

**Encryption unchanged** — AES-256-GCM stays on regardless. This flag only
controls the handshake, not the transport security.

**Android app + browser**
- When server responds to `/api/hello` with a token directly (no `pin_required`),
  skip PIN display and proceed straight to connected state

### How the project changes

Frictionless setup for users on home networks. Scan QR, connected immediately.
Honest about the tradeoff — encryption stays on, pairing is what's disabled.

### Potential problems

- **`guga --approve` with pairing off** — should say "Pairing is disabled. All
  devices connect automatically." rather than showing an empty list.

---

## Phase 21.1 — `guga --reload`

### What we want to achieve

One command that restarts the server and immediately shows the new URL and QR
code. Currently the user needs `sudo systemctl restart guga` then `guga --qr`
separately. Also handles servers started with `--start-server` (Phase 21.2).

### Changes to the project

**CLI**
- `guga --reload` — detects systemd vs PID file, restarts appropriately,
  waits for the server to come up, then calls `guga --qr`
- If neither: tells the user the server is not running and suggests
  `guga --start-server`

### How the project changes

One command replaces a two-step process. Particularly useful after editing `.env`
settings or after cloudflared assigns a new ephemeral URL.

### Potential problems

- **Timing** — cloudflared takes time to establish the tunnel after restart.
  Poll every second for up to 30 seconds rather than using a fixed sleep.
- **Sudo** — `systemctl restart` may require sudo. Handle the same way as
  Phase 21.3's sudo detection.

---

## Phase 21.2 — `guga --start-server` + Unified `guga --stop`

### What we want to achieve

Two things built together since they are complementary:

**1. `guga --start-server`**
Start the Flask server directly without relying on systemd. Useful for systems
without systemd (WSL, Arch with runit, Docker), for debugging where the user
wants to see server output live, and for users who prefer not to run a daemon.

**2. Unified `guga --stop`**
A single stop command that detects whether the server is running under systemd
or via `--start-server` and stops it correctly. Built here, not patched later.

### Changes to the project

**CLI**
- `guga --start-server` — starts server in foreground. User sees all output,
  Ctrl+C stops it. Prints QR code and URL on start.
- `guga --stop` — detects running mode (systemd vs foreground process via
  port check) and stops accordingly. Prints what it did.
- No `--background` flag — that reinvents systemd. On non-systemd systems,
  document `nohup guga --start-server &` as the approach.

### How the project changes

GuGa works on any Linux system regardless of init system. WSL users benefit
immediately. `--stop` is clean from day one with no later cleanup needed.

### Potential problems

- **Port conflict** — if systemd service is already running on 6769,
  `--start-server` fails to bind. Detect this and tell the user clearly.
- **`--stop` detection** — check if port 6769 is bound and identify whether
  it's a systemd service or a foreground process. `ss -tlnp` or `lsof -i:6769`
  work for this.

---

## Phase 21.3 — Phased Install with Capability Checks + Sudo Detection

### What we want to achieve

Make `--install-service` and `--reconfigure` resilient to missing tools,
unsupported systems, and missing permissions. Each install phase checks its
prerequisites before attempting anything. The user is given a clear choice
when something cannot be done automatically.

### Changes to the project

**Install flow restructured into discrete phases**

```
Phase 1 — Detect sudo          (gates everything that needs it)
Phase 2 — System packages      (check: package manager exists?)
Phase 3 — Python venv          (check: python3 -m venv available?)
Phase 4 — Tunnel binary        (check: architecture supported? network reachable?)
Phase 5 — .env configuration   (always possible)
Phase 6 — systemd service      (check: systemctl exists? systemd is PID 1?)
Phase 7 — guga CLI symlink     (check: /usr/local/bin writable or sudo available?)
Phase 8 — man page             (check: man dir exists, sudo available?)
Phase 9 — Start server         (systemd or --start-server fallback)
```

**Sudo detection**
- `os.geteuid() == 0` at startup
- If not root but sudo available: invoke sudo per-phase only when needed,
  do a single `sudo -v` at the start to refresh the credential cache
- If no sudo: show which phases will be skipped, offer to continue

**Per-phase check + skip flow**
```
  → Phase 6: systemd service
    Checking systemd... not found (this system uses runit)
    Cannot create systemd service.
    Options:
      [S] Skip — I will start the server manually with guga --start-server
      [A] Abort install
    Your choice:
```

**Non-systemd path**
- Suggest `--start-server` and offer to add it to `~/.bashrc` or `~/.zshrc`

### How the project changes

GuGa runs on any Linux system — NixOS, Arch with runit, WSL, headless servers,
no-sudo environments — without surprising the user mid-install.

### Potential problems

- **Detecting systemd reliably** — check `os.path.exists("/run/systemd/system")`
  not just `shutil.which("systemctl")`. systemctl can be installed on non-systemd
  systems.
- **Phase 4 name** — now "Tunnel binary" not "cloudflared" because Phase 23
  adds multiple tunnel options. The phase checks whichever tunnel mode the user
  chose.

---

## Phase 21.4 — `--ask-user`, `guga -i`, Chat Shell

### What we want to achieve

Three levels of two-way interaction between the Linux machine and the phone,
registered as extensions from Phase 20.0:

1. `guga --ask-user "prompt"` — a script blocks and waits for the user to
   reply from the phone. Reply is printed to stdout so it can be captured.
2. `guga -i command` — any command with interactive prompts has those prompts
   forwarded to the phone. User replies feed back via PTY.
3. Chat shell — freeform text typed in the app runs as a shell command on the
   Linux machine and output is sent back as a notification bubble.

The server tells the app which features are enabled at pairing time so the app
can show or hide the chat UI accordingly.

### Changes to the project

**Extensions registered (Phase 20.0 system)**
- `extensions/ask-user/` — `FEATURE_ASK_USER=true`, no extra pip deps
- `extensions/interactive/` — `FEATURE_INTERACTIVE=true`, pip dep: `pexpect`
- `extensions/shell/` — `FEATURE_CHAT_SHELL=true`, no extra pip deps

**Server (`server.py`)**
- `/api/verify_pin` response extended with a `features` object:
  ```json
  { "status": "paired", "token": "...",
    "features": { "ask_user": false, "interactive": false, "chat_shell": false } }
  ```
- Features also sent on WebSocket connect so app stays in sync if config changes
- New endpoint `POST /api/ask` — receives a prompt + session_id + timeout,
  forwards to phone, blocks until reply or timeout
- New endpoint `POST /api/reply` — phone posts a reply, server routes to the
  waiting process via session_id
- `process_command` wired to real subprocess execution if `FEATURE_CHAT_SHELL`
  is on, otherwise returns a "chat disabled" message

**CLI**
- `guga --ask-user "message"` — sends prompt, polls `GET /api/reply/<session_id>`
  until reply or timeout, prints reply to stdout
- `guga -i command args` — spawns command under `pexpect`, forwards prompts
  to phone, feeds replies back into stdin

**Android app**
- Reads `features` from pairing response and stores it
- Chat input hidden entirely if all three features are false
- Input field greyed out between prompts if only `ask_user` is on
- Input field always active if `chat_shell` is on
- Re-reads features on reconnect

### How the project changes

The app stops being purely a notification receiver and becomes a proper
two-way interface. The existing chat UI, previously wired to "command not
found", has real purpose. Scripts can pause and wait for human decisions
without the user being at the terminal. This is the foundation for the Phase
26b MCP `ask_user` tool and Phase 27 vibe coding.

### Potential problems

- **IPC between server and CLI** — reply comes in via WebSocket to the server
  but needs to reach the blocking CLI process. Polling `GET /api/reply/<session>`
  is the simplest approach and avoids Unix socket complexity.
- **Concurrent ask-user calls** — queue them. Show one prompt at a time on the
  phone with the source script name so the user knows what they are replying to.
- **`pexpect` PTY on headless servers** — some programs detect they are not in
  a real TTY and disable interactive prompts. Document this limitation.
- **`FEATURE_CHAT_SHELL` security** — effectively gives the phone a shell on
  the machine. Warning during extension install must be explicit and impossible
  to miss. Never enabled by default.

---

## Phase 22 — `guga --listen` (CLI-Exclusive Receiver)

### What we want to achieve

Give the CLI the ability to receive notifications, not just send them.
This completes the producer/consumer symmetry of `guga-cli`:

```bash
guga "message"                    # produce — send to server
guga --listen https://server.url  # consume — receive from server
```

`--listen` is exclusive to `guga-cli`. `guga-server` never needs to listen to
itself — it is the hub, not an edge client.

### Changes to the project

**CLI (`guga_push.py`)**
- `guga --listen URL` — connects as a WebSocket client, goes through the full
  Phase 20.1 pairing flow (generates PIN, displays it, waits for `--approve`)
- Default: fires native desktop notification via `notify-send` for each message.
  Falls back to printing if `notify-send` is absent.
- `--watch` modifier: prints each notification to stdout, stays open until Ctrl+C,
  pipe-friendly

```bash
guga --listen https://xyz.trycloudflare.com --watch >> ~/guga.log
guga --listen https://xyz.trycloudflare.com --watch | while read line; do
    echo "$line" | mail -s "Alert" me@example.com
done
```

- New dependency: `websocket-client` (small, pure Python, no async required)

**No server changes** — the terminal client is just another trusted device.

### How the project changes

Three client types: app, browser, terminal. A developer can run `guga --listen`
on multiple GPU servers pointed at a central GuGa instance and see all
notifications in one terminal feed. The CLI becomes useful even without the
Android app.

### Potential problems

- **Encryption** — terminal client should be treated as an app client and
  receive full AES-256-GCM, not the plaintext path used for browsers.
- **Reconnection** — reconnect with exponential backoff. Print a status line
  on reconnect rather than silently failing.
- **`websocket-client` as new dep** — when Phase 25 splits packages, this goes
  into `guga-cli` dependencies only, not `guga-server`.

---

## Phase 23 — Stable Connection Modes + `--awake`

### What we want to achieve

The ephemeral Cloudflare tunnel URL is GuGa's biggest day-to-day friction point.
The phone loses connection every time the server restarts, requiring a re-scan.
This phase adds multiple ways to get a stable URL, grouped under a single
`TUNNEL_MODE` config variable. It also adds `--awake` for keeping machines
alive during long jobs.

### The connection problem and why Cloudflare's tunnel has a privacy tradeoff

Cloudflare acts as a reverse proxy — it decrypts the outer HTTP envelope at
its edge nodes before forwarding traffic through the tunnel. GuGa's AES-256-GCM
WebSocket encryption protects the message content, but Cloudflare sees connection
metadata. For privacy-conscious users, self-hosted alternatives eliminate this
entirely.

### Stable connection modes

```
TUNNEL_MODE=cloudflare-ephemeral   # current default — URL changes on restart
TUNNEL_MODE=cloudflare-named       # permanent Cloudflare tunnel — requires CF account + domain
TUNNEL_MODE=frp                    # self-hosted — requires VPS running frps
TUNNEL_MODE=tailscale              # VPN mesh — GuGa runs in LAN mode via Tailscale IP
TUNNEL_MODE=static                 # user provides URL — GuGa does nothing to establish it
```

**`--install-service` new question:**
```
How will you connect?
  1) Cloudflare Tunnel (ephemeral)      easy setup, URL changes on restart
  2) Cloudflare Tunnel (named)          permanent URL, requires CF account + domain
  3) frp (self-hosted, privacy-first)   permanent URL, requires a VPS
  4) Tailscale / Headscale              VPN mesh, LAN mode, no public exposure
  5) Static URL / own domain            I will manage the connection myself
```

---

**cloudflare-named**

Uses `cloudflared tunnel create` and `cloudflared tunnel route dns` to create
a permanent named tunnel tied to a domain. The `cloudflared` binary is already
managed by GuGa.

GuGa's installer:
1. Runs `cloudflared login` — opens browser, user authorises
2. Asks for tunnel name (default: `guga`) and subdomain (`guga.yourdomain.com`)
3. Runs `cloudflared tunnel create guga`
4. Runs `cloudflared tunnel route dns guga guga.yourdomain.com`
5. Writes tunnel name to `.env`
6. On every start, uses `cloudflared tunnel run guga` instead of `cloudflared tunnel --url`

For headless servers: supports API token as an alternative to browser login.
Ask during setup: "Headless server? Provide a Cloudflare API token instead."

---

**frp (recommended for privacy-first, fully self-hosted setup)**

frp consists of two binaries: `frps` (runs on VPS) and `frpc` (runs locally,
managed by GuGa exactly like cloudflared). The user runs `frps` on their VPS
permanently. GuGa manages `frpc`.

GuGa's installer for frp mode:
1. Downloads `frpc` binary for the correct architecture
2. Asks for: VPS IP/hostname, token (shared secret), subdomain
3. Writes `frpc.toml`:

```toml
serverAddr = "your.vps.ip"
serverPort = 7000
auth.token = "your_shared_secret"

[[proxies]]
name       = "guga"
type       = "https"
localPort  = 6769
customDomains = ["guga.yourdomain.me"]
```

4. Manages `frpc` as a service alongside the GuGa server

The domain never changes. No third party sees connection metadata. `guga --qr`
always shows the same URL.

VPS setup (user does this once, documented in README):
```bash
# On VPS
wget https://github.com/fatedier/frp/releases/latest/download/frp_linux_amd64.tar.gz
tar -xzf frp_linux_amd64.tar.gz
# Edit frps.toml: set auth.token
./frps -c frps.toml
```

Point your domain DNS A record at the VPS IP. GuGa handles the rest.

**rathole** — a Rust alternative to frp with identical config structure and
lower resource usage. Document as an advanced drop-in replacement — same config
format, different binary path. No installer support needed.

---

**tailscale**

GuGa runs in LAN mode using the Tailscale IP (`100.x.x.x`). GuGa's installer
detects if Tailscale is already running and offers to use its IP automatically.
If not installed, prints the Tailscale install instructions and exits — GuGa
does not manage the Tailscale installation.

No server code changes. The Tailscale IP is stable forever. The phone connects
via the Tailscale app on Android — both devices on the same Tailscale network.

---

**static**

User provides the URL directly. GuGa writes it to `.env` as `CUSTOM_URL` and
uses it everywhere — QR code, startup banner, `guga --qr`. GuGa does nothing
to establish the connection. Useful for users with an existing nginx/Caddy
reverse proxy, a home server behind a static IP, or any other custom setup.

---

**`guga --awake`**

Prevents the system from sleeping while a watched command is running. Wraps the
command in `systemd-inhibit --what=sleep` if available. Falls back gracefully
with a warning if unavailable.

```bash
guga --awake python train.py --epochs 100
guga --awake -r "long_job.sh" --title "GPU Server"
```

### Changes to the project

**`.env`**
- `TUNNEL_MODE` replaces separate `MODE` and `CUSTOM_DOMAIN` variables
- `TUNNEL_DOMAIN` — the permanent domain for cloudflare-named, frp, or static
- `FRP_SERVER_ADDR`, `FRP_SERVER_PORT`, `FRP_TOKEN` — frp connection details
- `CF_TUNNEL_NAME` — named Cloudflare tunnel name

**CLI**
- `guga --awake command args` — wraps in `systemd-inhibit` if available
- `guga --qr` — always shows `TUNNEL_DOMAIN` when a stable mode is configured

**Server startup banner**
- Shows the active tunnel mode and URL clearly
- Shows a privacy note when `cloudflare-ephemeral` or `cloudflare-named` is active:
  `ℹ  Cloudflare sees connection metadata. Use frp mode for full privacy.`

### How the project changes

GuGa works for every type of user: casual (ephemeral Cloudflare), domain owner
(named Cloudflare), privacy-focused self-hoster (frp), VPN user (Tailscale),
power user (static). The ephemeral-URL re-scan problem is eliminated for anyone
who takes five minutes to configure a stable mode. The privacy tradeoff is
disclosed honestly.

### Potential problems

- **`cloudflared login` opens a browser** — awkward on headless servers. The
  API token path must be documented and tested. Ask upfront during setup.
- **frp VPS setup is user responsibility** — GuGa only manages `frpc`. The
  user sets up `frps` on their VPS. Write clear, step-by-step README docs for
  this. Link to them from the installer output.
- **Tailscale detection** — `shutil.which("tailscale")` plus `tailscale status`
  to confirm it is running and get the IP. If Tailscale is installed but not
  running, tell the user rather than silently using the wrong IP.
- **`systemd-inhibit` scope** — if the child spawns subprocesses and exits
  early, the inhibit lock releases even if work is still happening. Document
  this edge case.

---

## Phase 24 — `guga --screenshot`

### What we want to achieve

Capture the current screen and send it as an image to all connected clients.
Standalone useful for sharing errors visually, and a building block for
Phase 27 vibe coding.

```bash
guga --screenshot
guga --screenshot --title "Error at 14:32"
```

### Changes to the project

**CLI**
- `guga --screenshot` — detects available capture tool (`scrot`, `gnome-screenshot`,
  `import` from ImageMagick), captures, resizes to max 1280px wide, JPEG-encodes
  at 80% quality (keeps payload under ~200KB), base64-encodes, POSTs to `/send`
  with `type: "image"` in the payload

**Server**
- `/send` extended to accept `type: "image"` with `data: base64string`
- Broadcasts image payload to all connected clients

**App + browser**
- Render inline image in the chat feed when `type: "image"` is received

### How the project changes

Enables visual debugging over the phone. Opens the door to the Phase 27
coding iteration loop. Also useful standalone — a researcher can screenshot
a crashed job and have the image arrive on their phone automatically.

### Potential problems

- **Headless servers** — check `$DISPLAY` or `$WAYLAND_DISPLAY` before
  attempting capture. Fail clearly rather than hang.
- **Image size** — full PNG screenshots can be several MB. Always compress
  to JPEG before sending.

---

## Phase 25 — PyPI Package Split (guga / guga-cli / guga-server)

> Monolith is split here. All previous phases are implemented as a single
> package. This phase reorganises without adding features.

### What we want to achieve

Split the single `guga` package into three:

- `guga-cli` — CLI only, no Flask, stdlib-only dependencies
- `guga-server` — Flask server only, no CLI command
- `guga` — meta-package that depends on both, installs everything

Add `--send-to URL` flag to `guga-cli` so it can POST to a remote server.
Add `GUGA_SERVER` environment variable as a persistent alternative.

### Changes to the project

- Monorepo restructured into `packages/guga-cli/`, `packages/guga-server/`,
  `packages/guga/`
- `guga-server --install-service` replaces `guga --install-service`
- `guga-server --status`, `--start`, `--stop`, `--reload`, `--logs` added
- Single `VERSION` file drives all three package versions
- GitHub Actions publishes all three — meta-package published last
- Docker use case: `pip install guga-cli` +
  `GUGA_SERVER=http://host.docker.internal:6769`

### How the project changes

Users installing on CI/Docker/remote servers install `guga-cli` only — no Flask,
no heavy deps, tiny footprint. Users running the server install `guga-server`.
Most users install `guga` and get everything.

### Potential problems

- **Shared code** — colour helpers, config resolution, URL detection are used by
  both CLI and server. Duplication of ~50 lines is the pragmatic choice. A
  `guga-core` private package adds publish complexity for little gain.
- **Version sync** — a pre-publish script checks all three `pyproject.toml`
  files match before the GitHub Action proceeds.
- **PyPI name availability** — register `guga-cli` and `guga-server` on PyPI
  as placeholders before Phase 25 to prevent squatting.
- **Existing users upgrading** — `pip install --upgrade guga` pulls in both
  subpackages. Test the upgrade path explicitly.

---

## Phase 26a — AI Integration: OpenAPI + llms.txt + tools.json

### What we want to achieve

Make GuGa discoverable and usable by AI tools and agents through standard
integration formats. Three static files, collectively covering almost every
AI tool in use today, with near-zero implementation effort.

### The three deliverables

**`openapi.yaml`** — standard OpenAPI 3.0 spec of GuGa's HTTP endpoints.
GPT custom actions, LangChain, AutoGen, CrewAI, Zapier AI, Make.com, n8n, and
dozens of others consume this automatically. Served at `/openapi.yaml` and
committed to repo root.

**`llms.txt`** — plain text file formatted for LLM consumption. When an AI is
asked "how do I use GuGa", it finds this file and has everything it needs.
Served at `/llms.txt` and committed to repo root so GitHub crawlers index it.

**`tools.json`** — function definitions in the format used by most agent
frameworks. Any framework that is not MCP-native but supports function
definitions imports this directly. Served at `/tools.json` and committed to
repo root.

### Changes to the project

**Server**
- `GET /openapi.yaml`, `GET /llms.txt`, `GET /tools.json` — static file routes,
  no auth required, no localhost restriction (they are discovery files)

**Repo root**
- All three files committed
- README updated with "AI Integration" section

### How the project changes

GuGa becomes findable and usable by the entire AI tooling ecosystem without
writing any agent-specific code. Highest-leverage phase in the roadmap relative
to effort.

### Potential problems

- **`/send` localhost restriction** — the OpenAPI spec describes `/send` but
  remote agents cannot call it unless the user has explicitly opened it. Add a
  clear note in the spec and `llms.txt`.
- **Keeping files in sync** — new routes need manual `openapi.yaml` updates.
  Add to GitHub Actions release checklist.

---

## Phase 26b — MCP Server

### What we want to achieve

Expose GuGa as a proper MCP (Model Context Protocol) server so Claude, Cursor,
Windsurf, and any MCP-compatible AI tool can call GuGa as a native skill. The
AI decides when to notify the user without being told to. More importantly, the
AI can pause mid-task, ask the user a question on their phone, wait for a reply,
and continue — without the user being at the terminal.

Builds on Phase 26a — tool definitions from `tools.json` reused as MCP schema.
Registered as a GuGa extension from Phase 20.0.

### Architecture — MCP talks directly to the server, not the CLI

```
AI tool (Claude / Cursor / any MCP client)
        ↓  MCP protocol
  mcp_server.py          port 6770, long-running
        ↓  HTTP (localhost)
  guga-server            port 6769
        ↓  WebSocket (encrypted)
  phone / browser / terminal
```

`mcp_server.py` is a thin HTTP client translating MCP tool calls into HTTP
requests to `guga-server`'s existing endpoints. It never touches `guga-cli`.
Works regardless of whether `guga-cli` is installed.

### Tools exposed

**`send_notification(message, title?)`**
Available: immediately. POSTs to `/send`.

**`ask_user(prompt, timeout_seconds?)`**
Available: only after Phase 21.4 (`/api/ask` endpoint) is implemented.
Sends a prompt to the phone, blocks until the user replies or timeout expires,
returns the reply as the tool result. Default timeout: 300 seconds.

The flow:
```
AI calls ask_user("Which environment? prod or staging")
        ↓
MCP server POSTs to /api/ask with prompt + session_id + timeout
        ↓
guga-server sends prompt to phone over WebSocket
        ↓
User sees prompt in app chat, types reply
        ↓
MCP server returns reply as tool result to the AI
        ↓
AI continues: "User said prod, proceeding..."
```

On timeout: MCP returns error to AI. Phone shows "⚠ This request timed out"
so the user knows their reply is no longer needed.

**`run_command(command)`**
Available: only if `FEATURE_CHAT_SHELL=true`. POSTs to `/api/command`.
Returns stdout/stderr. Significant security surface — never enabled by default.

**`get_status()`**
Available: immediately. GETs `/ping` and `/clients`.
Returns `{ alive: true, connected_clients: 2 }`.

### Tool availability

| Tool | Available from | Requires |
|---|---|---|
| `send_notification` | Phase 26b | Nothing extra |
| `get_status` | Phase 26b | Nothing extra |
| `ask_user` | Phase 26b + 21.4 | Phase 21.4 `/api/ask` endpoint |
| `run_command` | Phase 26b | `FEATURE_CHAT_SHELL=true` |

`mcp_server.py` checks `GET /api/features` on startup and only registers
tools that are actually available. An AI sees only tools it can call.

### New server endpoint: `GET /api/features`

Returns which features are enabled. Localhost only. Used by `mcp_server.py`
on startup.

```json
{ "chat_shell": false, "ask_user": true, "interactive": false, "mcp": true }
```

### Changes to the project

**New file: `mcp_server.py`** — long-running process, port 6770, uses official
`mcp` Python SDK.

**Extension manifest: `extensions/mcp/manifest.json`**
- `pip_deps`: `["mcp"]`
- `env_flags`: `{ "FEATURE_MCP": "true" }`
- Installed via `guga --add-extension mcp`

**systemd service: `guga-mcp.service`**
- Created by the MCP extension installer
- `guga --reload` restarts both `guga.service` and `guga-mcp.service`
- `guga --stop` stops both
- `guga-server --status` shows status of both

**How to add GuGa to Claude**
```
Claude.ai Settings → Connectors → Add MCP Server → http://localhost:6770
```

### How the project changes

GuGa becomes a genuine human-in-the-loop bridge for AI agents. `ask_user` is
the differentiating capability — no other notification tool lets an AI agent
pause, ask you something on your phone, and continue with your answer.

### Potential problems

- **`ask_user` timeout UX** — phone should show "⚠ Timed out" so user knows
  their reply is no longer needed.
- **Multiple simultaneous `ask_user` calls** — queue them, show one at a time
  with source label so the user knows which agent is asking.
- **MCP SDK API stability** — pin the version in the extension manifest.
- **Authentication** — add `MCP_SECRET` in `.env` as a required header.
  Localhost-only is the minimum.
- **`run_command` security** — explicit warning during extension install.

---

## Phase 27 — Mobile Vibe Coding Interface

### What we want to achieve

A complete mobile AI coding assistant backed by the Linux machine. User can
screenshot an error, send it to Claude via the GuGa chat interface, receive
fixed code on their phone, apply it, and re-run — all without being at the
terminal.

Builds on: Phase 21.4 (chat shell), Phase 24 (`--screenshot`), Phase 26b (MCP).

**The flow**
1. Error occurs on Linux machine
2. `guga --screenshot --title "Error"` sends the error screen to the phone
3. User sees it in the app, taps "Ask Claude"
4. App sends screenshot + context to Claude API
5. Claude returns fixed code
6. User taps "Apply and run"
7. App sends the fix back over the chat channel
8. Server applies it to the file and re-runs the script
9. Result notification arrives on the phone

### Changes to the project

**App**
- "Ask Claude" button on image messages — compose view pre-loaded with screenshot
- Claude API key stored in app settings (never sent to GuGa server)
- "Apply and run" button on code block responses

**Server**
- `/api/apply` — receives file path + new content, writes the file, runs it,
  streams output back
- `FEATURE_APPLY_CODE` flag — off by default, explicit warning during setup
- Restricted to a configurable allowed directory set at install time

**CLI**
- `guga --screenshot` already built in Phase 24 — reused here

### How the project changes

GuGa becomes a genuine remote development tool. The teacher use case is fully
addressed. Nothing else lets you do a coding iteration loop from your phone.

### Potential problems

- **File write safety** — `/api/apply` must reject paths outside the allowed
  directory. Never allow writing to system paths.
- **Code without context** — allow user to include the full file or recent
  terminal output when sending to Claude, not just the screenshot.
- **Claude API key** — stored locally on the phone. Make this clear in docs.

---

## Phase TimePass — Nice-to-Have Additions

> Not on the critical path. Pick whatever appeals when the core is stable.

---

### TP-1 — App Title Filtering

All messages are stored. Filtering only affects what is displayed — nothing
is ever discarded.

- Filter lives entirely in the app — no server changes
- Chip bar above the feed showing active filters
- User selects from titles the app has already seen, or types a custom one
- Multiple filters supported — messages matching any active filter are shown
- Non-matching messages go into a hidden "Filtered (N)" inbox
- Clearing all filters shows everything

---

### TP-2 — Hide Chat Field Toggle

User can hide the chat input field even when the server has chat enabled,
for a cleaner notification-only view.

- Server says chat is off → input hidden, no toggle
- Server says chat is on → input shown by default, small toggle icon available
- Preference persists across sessions

---

### TP-3 — Persistent Notification Server State

The Android persistent notification becomes a live status indicator.

| State | Text |
|---|---|
| Connected | `● Connected` |
| Connected, quiet | `● Connected — quiet for 2h` |
| Reconnecting | `↻ Reconnecting...` |
| Disconnected | `○ Disconnected — last seen 14m ago` |
| Unreachable | `✗ Server unreachable` |

App tracks last heartbeat timestamp, updates notification every 60 seconds.
No server changes needed.

---

### TP-4 — LAN Self-Discovery via mDNS

Server broadcasts `_guga._tcp.local.` via the `zeroconf` Python library.
App scans with Android `NsdManager`. User taps the discovered server to pair —
no QR scan or manual URL entry needed. Opt-in during `--install-service`.

LAN only. QR code stays as fallback for Cloudflare/frp/internet mode.
mDNS is blocked on some corporate networks — never make it the only option.

---

### TP-5 — AUR Package

`yay -S guga` works. `PKGBUILD` at `packaging/aur/PKGBUILD` points at the
PyPI package. Submit to AUR — community maintains after initial submission.
Add to GitHub Actions release checklist.

---

### TP-6 — apt PPA

`sudo apt install guga` via a Launchpad PPA. High effort — requires Launchpad
account, GPG signing key, `.deb` packaging, ongoing maintenance. Worth doing
once the project has a stable user base.

---

## Summary Table

| Phase | Title | Key addition | Breaks anything? |
|---|---|---|---|
| 20.0 | Extension infrastructure | Plugin system, `--list/add/remove-extension` | None |
| 20.1 | Client PIN + `--approve` | Secure pairing, `--approve` CLI | Removes `--show-pin` |
| 20.3 | Security off toggle | `REQUIRE_PAIRING=false` | None |
| 21.1 | `--reload` | Restart + new QR in one command | None |
| 21.2 | `--start-server` + `--stop` | Systemd-free start, unified stop | None |
| 21.3 | Phased install + sudo detection | Resilient installer | None |
| 21.4 | Interactive input forwarding | `--ask-user`, `guga -i`, chat shell | None |
| 22 | `guga --listen` | Terminal as notification receiver (CLI only) | None |
| 23 | Stable connection modes + `--awake` | frp, CF named, Tailscale, static, sleep prevention | None |
| 24 | `--screenshot` | Image sending to phone | None |
| 25 | PyPI split | `guga-cli`, `guga-server`, `--send-to` | Install paths change |
| 26a | OpenAPI + llms.txt + tools.json | AI tool discoverability | None |
| 26b | MCP server | GuGa as native Claude/Cursor skill | None |
| 27 | Mobile vibe coding | Phone-based AI coding loop | None |
| TimePass | Polish + reach | Filtering, mDNS, apt, status notif, hide chat | None |

---

## What was removed and why

| Removed | Reason |
|---|---|
| Phase 20.2 (feature flag infrastructure) | Redundant — Phase 20.0 handles flags via extension manifests; Phase 21.4 implements the actual features |
| `guga --stop-server` (Phase 21.2) / `--stop` cleanup (Phase 23) | Built as unified `guga --stop` in Phase 21.2 from the start |
| `guga --start-server --background` | Reinvents systemd daemon management badly. Document `nohup` instead. |
| AUR from Phase 24 | Duplicate of TimePass TP-5. Phase 24 is now just `--screenshot`. |
| Phase 21.0 label | Renumbered to Phase 21.4 — the correct sequential position |
| Phase 25 out-of-order body placement | Moved to correct position after Phase 24 |
