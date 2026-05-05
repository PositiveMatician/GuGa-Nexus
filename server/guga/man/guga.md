# guga

> Send notifications to Android via the local GuGa server.
> Supports plain messages, interactive prompts, watching commands, and MCP integration.

- Send a plain message:
`guga "{{Build finished}}"`

- Send a notification from stdin to a specific device tag:
`echo "{{Deploy done}}" | guga --send-to {{F}}`

- Run a command and notify when it finishes:
`guga {{python train.py --epochs 100}}`

- Run a command interactively (forwarding terminal prompts to device):
`guga -r -i --send-to {{F}} {{python3 train.py}}`

- Ask a question and wait for a reply (with timeout and fallback):
`guga --ask-user "{{Continue build?}}" --send-to {{F}} --delay {{5m}} --default {{no}}`

- Watch command output for a pattern and notify immediately on match:
`guga -r --look-for "{{ERROR|CRITICAL}}" {{./long_script.sh}}`

- Show current server status and connected devices:
`guga --status`

- Show pairing QR code:
`guga --qr`

- Start the GuGa ASGI server in the background:
`guga --start-server --background --mode {{lan}}`

- Stop all background servers:
`guga --stop-server -A`

- Approve all pending pairing requests:
`guga --approve -A`

- Install the MCP server entry into Antigravity (one-time setup):
`guga --install-mcp`

- Preview MCP install without writing:
`guga --install-mcp --dry-run`

- Remove the MCP entry:
`guga --uninstall-mcp`

- List/unblock/revoke devices:
`guga --blocked`
`guga --unblock {{device-id}}`
`guga --revoke {{F}}`
