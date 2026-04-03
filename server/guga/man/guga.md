# guga

> Send notifications to Android via the local GuGa server.
> Supports plain messages, stdin pipes, and watching commands to notify on completion.
> More information: <https://github.com/your-repo/guga>

- Send a plain message:

`guga "{{Build finished}}"`

- Send a notification from stdin:

`echo "{{Deploy done}}" | guga`

- Run a command and notify when it finishes (includes exit status, elapsed time, last output line):

`guga {{python train.py --epochs 100}}`

- Force message mode (never executes, even if the string looks like a command):

`guga --message "{{python train.py}}"`

- Force run mode with a quoted command string:

`guga --run "{{sleep 5}}"`

- Run a command with a label so you know which machine fired the notification:

`guga --run {{./deploy.sh}} --title "{{Prod Server}}"`

- Run silently (no terminal output from guga, command output still streams normally):

`guga {{python train.py}} --silent --title "{{GPU}}"`

- Use a custom server port:

`guga "{{message}}" --server {{9000}}`
