# GuGa — HTTP API & MCP Tool Definitions

Base URL: `http://localhost:6769`

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ping` | Health check → `{"status": "online"}` |
| GET | `/clients` | List connected Socket.IO session IDs |
| GET | `/llms.txt` | LLM reference file (plain text) |
| GET | `/tools.json` | OpenAI-compatible tool definitions |
| POST | `/send` | Broadcast to all devices (localhost-only) |
| POST | `/send/<session_id>` | Send to one device (localhost-only) |
| GET | `/api/devices` | List all paired devices (name, tag, id) |
| GET | `/api/pending` | List pending pairing requests |
| POST | `/api/approve` | Approve or reject a pairing request |
| POST | `/api/ask` | Synchronous ask to a device |
| POST | `/api/rename` | Assign a custom tag to a device |

## MCP Tools (via `guga --mcp`)

| Tool | Description |
|------|-------------|
| `send_notification` | Push a message to devices. Accepts `unique_message_id`. |
| `ask_user` | Prompt user on phone, block for reply. Supports `default`. |
| `list_devices` | Get status of paired clients. |
| `run_command` | Execute a command with logging and `look_for` support. |

## OpenAI-Compatible Tool Definitions

Import `http://localhost:6769/tools.json` into LangChain, AutoGen, CrewAI,
Semantic Kernel, or custom GPT Actions to get these functions:

- `guga_send` — Send notification
- `guga_ask_user` — Ask + wait for reply
- `guga_run_command` — Run command, notify on finish
- `guga_interactive_run` — PTY mode, forward prompts
- `guga_server_control` — Start/stop/approve
- `guga_manage_devices` — Block/unblock/revoke
- `guga_status` — Server + device info
- `guga_system_setup` — Install/uninstall/reconfigure

## Agent Guidelines (from tools.json)

1. Call `guga_status` first to confirm server is running and discover device tags.
2. Upon successful completion, MUST call `guga_send` (results) + `guga_ask_user` (next intent).
3. Always use `guga_send` when starting a long task and when it completes.
4. Always use `guga_ask_user` before irreversible actions.
5. Always set a `delay` on `guga_ask_user` — use `10m` for decisions.
6. Handle timeout — if `guga_ask_user` fails, abort and notify user.
7. Parse replies with flexible matching: `grep -qi 'yes\|y\|ok\|go\|sure'`
8. Do not send multiple notifications in rapid succession — batch them.
