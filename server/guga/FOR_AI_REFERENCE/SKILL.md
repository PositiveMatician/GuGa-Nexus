---
name: guga
description: >
  GuGa Nexus — Android Notification & Remote Interaction Skill.
  Use this skill whenever the user mentions: notifying their phone, sending a message
  to their Android device, asking for user input during a long task, human-in-the-loop
  workflows, watching or wrapping a command, pinging when done, remote interaction,
  agentic approvals, or anything involving the `guga` CLI tool.
  Trigger phrases: "notify me", "tell me when done", "ask user", "send to phone",
  "wait for reply", "ping me", "human in the loop", "ask me on my phone",
  "let me know when", "wrap this command", "interactive install", "--ask-user",
  "guga send", "guga run", "guga status", "guga mcp", "--install-mcp",
  "list blocked devices", "unblock device", "revoke device access".
  Always use this skill if the user is orchestrating agentic tasks and wants
  to receive results or approve steps from their Android phone.
---

# GuGa Nexus Skill

GuGa Nexus bridges an AI agent on Linux with the user's Android device.
It sends push notifications, blocks to ask questions, wraps long-running commands,
and enables full human-in-the-loop agentic workflows.

---

## Step 0 — Always check server status first

```bash
guga --status
```

Look for:
- **address**: local or public URL (e.g. `https://...trycloudflare.com`)
- **connected devices**: note the `Tag` (e.g. `F`) for targeting

---

## The 8 Core Patterns

### Pattern 1 — Notify when done
```bash
guga "Task complete: model trained. Loss: 0.043" --send-to F
guga --from "GPU Server" "Training complete. Accuracy: 94.2%"
python train.py 2>&1 | tail -1 | guga --send-to F
```

### Pattern 2 — Ask user, wait for reply ⭐ (most important)
```bash
REPLY=$(guga --ask-user "Deploy to production?" --send-to F --delay 5m)

# With safe default on timeout:
REPLY=$(guga --ask-user "Continue risky migration?" --send-to F --delay 10m --default "no")
```
Always handle timeout (non-zero exit). Parse reply flexibly:
```bash
if echo "$REPLY" | grep -qi "yes\|y\|go\|sure\|ok"; then ...
```

### Pattern 3 — Full agentic loop (notify + ask + act + repeat)
See `references/agentic-loop.md` for the canonical multi-step script template.

### Pattern 4 — Watch a command, notify on completion
```bash
guga python train.py --epochs 100 --lr 0.001
guga --from "Build Server" ./build.sh --release
```

### Pattern 5 — Interactive remote execution (PTY mode)
Forwards interactive prompts (e.g. setup wizards) to the phone in real time:
```bash
guga -r -i --send-to F python3 interactive_setup.py
guga -r -i --expect "REGEX" --send-to F ansible-playbook deploy.yml
```

### Pattern 6 — Watch for specific output patterns
```bash
guga -r --look-for "ERROR|CRITICAL" ./long_script.sh
```

### Pattern 7 — Automated / non-interactive mode (`--choices`)
Pre-fill installer prompts to avoid blocking:
```bash
guga --start-server --background --choices "1,2,,y"
guga --approve --all --choices "y"
guga --install-service --choices "1,2,,y"
```

### Pattern 8 — Output Logging
Every `guga -r` or `guga -i` execution is automatically logged to `~/.guga/logs/{unique_message_id}.log`. 
The message ID in your notification matches the filename for easy lookup.

---

## MCP Integration (Antigravity)

One-shot installer — auto-detects venv, writes to `~/.gemini/antigravity/mcp_config.json`:
```bash
guga --install-mcp           # Install
guga --install-mcp --dry-run # Preview only
guga --uninstall-mcp         # Remove
```

Local MCP server (stdio, for Claude Desktop):
```bash
guga --mcp
```

Remote MCP via Cloudflare Tunnel (SSE):
```bash
MODE=public guga --start-server
guga --mcp-token             # Get JWT token
# Connect to: https://<tunnel-url>/mcp/sse  with Authorization: Bearer <token>
```

**Important:** Antigravity only supports `command` (stdio) transport — not `url`/SSE.

---

## CLI Quick Reference

| Command | Purpose |
|---|---|
| `guga "MSG"` | Notify all devices |
| `guga "MSG" --send-to TAG` | Notify specific device |
| `guga --from "LABEL" "MSG"` | Notify with title label |
| `echo "MSG" \| guga` | Pipe stdin as notification |
| `guga --ask-user "Q" --send-to TAG` | Ask user, block for reply |
| `guga --ask-user "Q" --send-to TAG --delay 5m` | Ask, block with 5-minute timeout |
| `guga --ask-user "Q" --send-to TAG --default "X"` | Ask with fallback on timeout |
| `guga CMD [ARGS]` | Run command, notify on finish |
| `guga -r --look-for "REGEX" CMD` | Notify on regex match in output |
| `guga -r -i --send-to TAG CMD` | Interactive PTY, forward prompts |
| `guga -r -i --expect "REGEX" CMD` | Custom regex for prompt detection |
| `guga --start-server -b` | Start server in background |
| `guga --stop-server -A` | Stop all background servers |
| `guga --approve` | Approve device pairing requests |
| `guga --approve -A` | Approve all pending pairings |
| `guga --status` | Server status & device list |
| `guga --blocked` | List blocked devices |
| `guga --unblock [ID]` | Unblock a device |
| `guga --revoke [ID]` | Revoke device access |
| `guga --qr` | Show pairing QR code |
| `guga --rename-device` | Assign short tag to device |
| `guga --install-service` | Install as systemd service |
| `guga --install-mcp` | Register MCP in Antigravity |
| `guga --install-mcp --dry-run` | Preview MCP install without writing |
| `guga --install-mcp --mcp-python PATH` | Install MCP using a specific Python |
| `guga --mcp` | Start local MCP server (stdio) |
| `guga --mcp-token` | JWT token for remote MCP |
| `guga --choices "1,2,,y"` | Pre-fill interactive prompts |
| `guga --version` | Show version |

---

## Key Rules for Agents

1. **Always `guga --status` first** — confirm server is up, get device tags.
2. **Mandatory success protocol** — after any significant milestone, push results with `guga` AND ask for next intent with `--ask-user`. Never finish silently.
3. **Always `--send-to TAG`** when targeting a specific device (e.g. `--send-to F`).
4. **Always set `--delay`** on `--ask-user` (e.g. `5m` or `10m`). Use `never` only for must-block prompts.
5. **Handle timeouts** — if `--ask-user` exits non-zero, abort and notify the user.
6. **Human-in-the-loop** — always ask before irreversible actions (deploy, delete, migrate).
7. **Parse replies flexibly** — use `grep -qi "yes\|y\|ok\|sure"`, not strict equality.
8. **Batch notifications** — don't send multiple in rapid succession.

---

## Reference Files

- `references/agentic-loop.md` — full multi-step agentic script template
- `references/http-api.md` — HTTP API and MCP tool definitions for programmatic use
