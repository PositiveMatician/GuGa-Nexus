---
name: guga
description: >
  GuGa Nexus — Notification & Remote Interaction Skill.
  Enables the agent to send notifications to the user's Android device,
  monitor long-running terminal commands, and handle remote interactive prompts.
  Use guga to keep the user informed and to ask for their input from their phone
  while the agent continues working on the Linux machine.
  Triggers on phrases like: "notify me", "tell me when done", "ask user", "send to phone",
  "wait for reply", "ping me", "human in the loop", or any long-running task.
---

# GuGa Nexus Skill

GuGa bridges the AI agent running on Linux with the user's Android device.
Use it to send notifications, ask questions, and create human-in-the-loop workflows.

The user pairs their Android phone (or browser) to the GuGa server.
Devices can be given short tags via `guga --rename-device` (e.g. the tag `F`).

---

## Core Patterns

### Pattern 1 — Notify when done
Use this after completing any long-running task to inform the user on their phone.

```bash
# After finishing work:
guga "Task complete: model training finished. Loss: 0.043" --send-to F
```

```bash
# With a title label:
guga --from "GPU Server" "Training complete. Accuracy: 94.2%"
```

```bash
# Pipe stdout into a notification:
python train.py 2>&1 | tail -1 | guga --send-to F
```

---

### Pattern 2 — Ask user and wait for reply (MOST IMPORTANT PATTERN)
This is the primary interaction loop. The agent pauses, sends a question to the
user's phone, and the user replies from the Android app. The reply is captured
in a shell variable for the agent to act on.

```bash
REPLY=$(guga --ask-user "Should I deploy to production?" --send-to F --delay 5m)
echo "User replied: $REPLY"
```

If the user does not reply within the delay, the command exits with code 1.
Always handle this case in scripts.

```bash
REPLY=$(guga --ask-user "Continue with risky migration?" --send-to F --delay 10m --default "no")
# If the user doesn't reply in 10m, $REPLY will be "no".
```

---

### Pattern 3 — Full agentic loop (notify + ask + act + repeat)
This is the recommended pattern for multi-step agentic tasks that require
user input at key decision points. Always notify the user of progress,
then ask for decisions before irreversible actions.

```bash
#!/bin/bash
DEVICE="F"

# Step 1: Inform start
guga "Starting deployment pipeline. I'll check in at each stage." --send-to $DEVICE

# Step 2: Do preparatory work
./run_tests.sh
TEST_EXIT=$?

# Step 3: Notify result
if [ $TEST_EXIT -ne 0 ]; then
  guga "Tests failed. Deployment aborted." --send-to $DEVICE
  exit 1
fi
guga "All tests passed." --send-to $DEVICE

# Step 4: Ask before irreversible step
REPLY=$(guga --ask-user "Tests passed. Deploy to production now?" --send-to $DEVICE --delay 10m) || {
  guga "No reply received. Deployment cancelled for safety." --send-to $DEVICE
  exit 1
}

# Step 5: Act on reply
if echo "$REPLY" | grep -qi "yes\|y\|go\|sure\|ok\|deploy"; then
  guga "Deploying..." --send-to $DEVICE
  ./deploy.sh --env production
  guga "Deployment complete. All systems nominal." --send-to $DEVICE
else
  guga "Deployment cancelled on your request." --send-to $DEVICE
fi
```

---

### Pattern 4 — Watch a command, notify when done
Wrap any command with `guga` to automatically send a notification to the phone
when the command completes (success or failure).

```bash
guga python train.py --epochs 100 --lr 0.001
```

```bash
guga --from "Build Server" ./build.sh --release
```

---

### Pattern 5 — Interactive remote execution
For commands that interactively prompt for input, use `-r -i` to forward
prompts to the user's phone and feed replies back to the process.
Requires `--send-to` to designate which device handles the prompts.

```bash
guga -r -i --send-to F python3 interactive_script.py
```

---

### Pattern 6 — Watch for specific output patterns
Use `--look-for` to receive instant notifications when a specific pattern appears in a command's output.

```bash
guga -r --look-for "ERROR|CRITICAL" ./long_script.sh
```

### Pattern 7 — Output Logging
Every `guga -r` or `guga -i` execution is automatically logged to `~/.guga/logs/{unique_message_id}.log`. 
The message ID in your notification matches the filename for easy lookup.

---

## CLI Quick Reference

| Command | Purpose |
|---|---|
| `guga "MSG"` | Send notification to all devices |
| `guga "MSG" --send-to TAG` | Send to specific device/tag |
| `guga --from "LABEL" "MSG"` | Send with a title label |
| `echo "MSG" \| guga` | Send stdin as notification |
| `guga --ask-user "Q" --send-to TAG` | Ask user, block for reply |
| `guga --ask-user "Q" --send-to TAG --delay 5m` | Ask with a 5-minute timeout |
| `guga --ask-user "Q" --send-to TAG --default "X"` | Return "X" if timeout expires |
| `guga CMD [ARGS]` | Run command, notify on completion |
| `guga -r --look-for "REGEX" CMD` | Notify on regex match in output |
| `guga -r -i --send-to TAG CMD` | Run interactively, forward prompts |
| `guga -r -i --expect "REGEX" CMD` | Custom regex for prompt detection |
| `guga --status` | Show server status & devices |
| `guga --qr` | Show pairing QR code |
| `guga --approve` | Approve device pairing requests |
| `guga --rename-device` | Assign a short tag to a device |
| `guga --install-service` | Install as systemd service |

---

## Key Rules for Agents

1. **Always use `--send-to TAG`** when targeting a specific device (e.g. `--send-to F`).
2. **Always set `--delay`** on `--ask-user` calls. Use `5m` or `10m` for decisions; `never` for no timeout.
3. **Always handle timeout** — if `guga --ask-user` exits non-zero, the user did not reply.
4. **Notify before AND after** long tasks — once when starting, once when complete.
5. **Ask before irreversible actions** — deployments, migrations, deletions.
6. **Capture the reply** with `REPLY=$(guga --ask-user ...)` and parse it for keywords.
7. The GuGa server must be running (`guga --start-server` or as a systemd service).
