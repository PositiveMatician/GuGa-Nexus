# guga

> Send notifications to Android via the local GuGa server.
> Supports plain messages, interactive prompts, and watching commands to notify on completion.

- Send a plain message:
`guga "{{Build finished}}"`

- Send a notification from stdin to a specific device tag:
`echo "{{Deploy done}}" | guga --send-to {{F}}`

- Run a command and notify when it finishes:
`guga {{python train.py --epochs 100}}`

- Run a command interactively (forwarding terminal prompts to device):
`guga -r -i --send-to {{F}} {{python3 train.py}}`

- Ask a question and wait for a reply:
`guga --ask-user "{{Continue build?}}" --send-to {{F}} --delay {{5m}}`

- Show current server status and connected devices:
`guga --status`

- Show pairing QR code:
`guga --qr`

- Start the GuGa ASGI server in the foreground:
`guga --start-server`
