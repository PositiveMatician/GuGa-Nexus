# GuGa — Full Agentic Loop Template

Use this template for multi-step tasks that require user approval at decision points.

```bash
#!/bin/bash
DEVICE="F"

# ── 0. Confirm server is up ───────────────────────────────────────────────────
guga --status || { echo "GuGa server not running. Start with: guga --start-server -b"; exit 1; }

# ── 1. Announce start ────────────────────────────────────────────────────────
guga "Starting deployment pipeline. I'll check in at each stage." --send-to $DEVICE

# ── 2. Do preparatory work ───────────────────────────────────────────────────
./run_tests.sh
TEST_EXIT=$?

# ── 3. Notify result ─────────────────────────────────────────────────────────
if [ $TEST_EXIT -ne 0 ]; then
  guga "Tests FAILED. Deployment aborted. Check logs." --send-to $DEVICE
  exit 1
fi
guga "All tests passed ✓" --send-to $DEVICE

# ── 4. Ask before irreversible step ─────────────────────────────────────────
REPLY=$(guga --ask-user "Tests passed. Deploy to production now? (yes/no)" \
  --send-to $DEVICE --delay 10m --default "no") || {
  guga "No reply received within timeout. Deployment cancelled for safety." --send-to $DEVICE
  exit 1
}

# ── 5. Act on reply ──────────────────────────────────────────────────────────
if echo "$REPLY" | grep -qi "yes\|y\|go\|sure\|ok\|deploy"; then
  guga "Deploying to production..." --send-to $DEVICE
  ./deploy.sh --env production
  DEPLOY_EXIT=$?

  if [ $DEPLOY_EXIT -eq 0 ]; then
    guga "Deployment complete ✓ All systems nominal." --send-to $DEVICE
  else
    guga "Deployment FAILED (exit $DEPLOY_EXIT). Check logs." --send-to $DEVICE
    exit $DEPLOY_EXIT
  fi
else
  guga "Deployment cancelled on your request." --send-to $DEVICE
fi

# ── 6. Ask for next intent ───────────────────────────────────────────────────
REPLY=$(guga --ask-user "What should I do next? (e.g. run smoke tests / nothing)" \
  --send-to $DEVICE --delay 5m --default "nothing")

if echo "$REPLY" | grep -qi "smoke\|test"; then
  guga "Running smoke tests..." --send-to $DEVICE
  ./smoke_tests.sh
  guga "Smoke tests complete." --send-to $DEVICE
fi
```

## Key Points

- Always capture `$REPLY` with `REPLY=$(guga --ask-user ...)`.
- Always provide `--delay` and handle the timeout with `|| { ... }`.
- Use `--default "no"` for safety-critical steps so timeout = abort.
- Parse with `grep -qi` for flexible matching — users type casually.
- Batch related status into one `guga` call; don't spam multiple notifications.
- Use `--from "Label"` to help the user identify which agent/server is messaging them.
