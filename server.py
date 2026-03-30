import socket
import sys
from typing import Set

import qrcode
from flask import Flask, jsonify, render_template_string, request
from flask_socketio import SocketIO, emit

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
HOST = "0.0.0.0"
PORT = 6769
QR_INVERTED = True
QR_SHOW_GUI = False
CORS_ALLOWED_ORIGINS = "*"

# ------------------------------------------------------------
# QR Code Helper
# ------------------------------------------------------------
def generate_qr(data: str, inverted: bool = False, show_gui: bool = False) -> None:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    if show_gui:
        try:
            img = qr.make_image(fill_color="black", back_color="white")
            img.show()
        except Exception as e:
            print(f"⚠ Could not open image viewer ({e}).", file=sys.stderr)

    print("\n--- Scan this QR code with your phone ---")
    try:
        qr.print_ascii(invert=inverted)
        print("(Inverted)" if inverted else "(Normal)")
    except Exception as e:
        print(f"⚠ Failed to print ASCII QR: {e}", file=sys.stderr)


# ------------------------------------------------------------
# Flask App & SocketIO  (threading mode — no monkey patching)
# ------------------------------------------------------------
app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ALLOWED_ORIGINS,
    async_mode="threading",
)

connected_clients: Set[str] = set()


# ------------------------------------------------------------
# HTML Dashboard
# ------------------------------------------------------------
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>GuGa Terminal</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { box-sizing: border-box; }
        body { background: #121212; color: #00ff00; font-family: monospace; padding: 20px; margin: 0; }
        h2 { margin-top: 0; }
        #status { font-size: 0.8em; color: #888; margin-bottom: 6px; }
        #chat {
            height: 60vh; overflow-y: auto;
            border: 1px solid #333; padding: 10px;
            margin-bottom: 10px; border-radius: 4px;
        }
        #chat p { margin: 4px 0; word-break: break-word; }
        .system { color: #888; }
        .you    { color: #00bfff; }
        .bot    { color: #00ff00; }
        #inputRow { display: flex; gap: 8px; }
        #commandInput {
            flex: 1; padding: 10px;
            background: #222; border: 1px solid #444;
            color: white; border-radius: 4px; font-family: monospace;
        }
        button {
            padding: 10px 20px; background: #00ff00;
            color: black; border: none; cursor: pointer;
            border-radius: 4px; font-weight: bold;
        }
    </style>
</head>
<body>
    <h2>GuGa Terminal</h2>
    <div id="status">Connecting…</div>
    <div id="chat"></div>
    <div id="inputRow">
        <input type="text" id="commandInput" placeholder="Type a message…" onkeydown="handleEnter(event)">
        <button onclick="sendCommand()">Send</button>
    </div>
    <script>
        const socket = io({ transports: ['websocket', 'polling'] });
        const chat   = document.getElementById('chat');
        const status = document.getElementById('status');

        function appendMsg(cls, label, text) {
            const p = document.createElement('p');
            p.className = cls;
            p.textContent = (label ? label + ' ' : '') + text;
            chat.appendChild(p);
            chat.scrollTop = chat.scrollHeight;
        }

        socket.on('connect',    () => {
            status.textContent = '● Connected via ' + socket.io.engine.transport.name;
            appendMsg('system', '[SYSTEM]', 'Connected.');
        });
        socket.on('disconnect', (r) => {
            status.textContent = '○ Disconnected';
            appendMsg('system', '[SYSTEM]', 'Disconnected: ' + r);
        });
        socket.on('guga_response', (data) => appendMsg('bot', 'GuGa:', data.message));

        function sendCommand() {
            const input = document.getElementById('commandInput');
            const text  = input.value.trim();
            if (!text) return;
            appendMsg('you', 'You:', text);
            socket.emit('command', { phrase: text });
            input.value = '';
        }
        function handleEnter(e) { if (e.key === 'Enter') sendCommand(); }
    </script>
</body>
</html>
"""


# ------------------------------------------------------------
# HTTP Routes
# ------------------------------------------------------------
@app.route("/")
def web_interface():
    return render_template_string(HTML_PAGE)


@app.route("/ping")
def ping():
    return jsonify({"status": "online", "clients": len(connected_clients)}), 200


@app.route("/clients")
def list_clients():
    """List all connected client session IDs."""
    return jsonify({"clients": list(connected_clients), "count": len(connected_clients)}), 200


@app.route("/send", methods=["POST"])
def send_to_all():
    """Broadcast a message to ALL connected clients.

    curl -X POST http://localhost:6769/send \\
         -H "Content-Type: application/json" \\
         -d '{"message": "Hello everyone!"}'
    """
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "No message provided"}), 400
    notify_all_clients(message)
    return jsonify({"ok": True, "sent_to": len(connected_clients)}), 200


@app.route("/send/<session_id>", methods=["POST"])
def send_to_one(session_id: str):
    """Send a message to ONE specific client by session ID.

    curl -X POST http://localhost:6769/send/<sid> \\
         -H "Content-Type: application/json" \\
         -d '{"message": "Hey just you!"}'
    """
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "No message provided"}), 400
    if send_private_message(session_id, message):
        return jsonify({"ok": True, "session_id": session_id}), 200
    return jsonify({"error": f"No client with session_id '{session_id}'"}), 404


@app.route("/api/command", methods=["POST"])
def handle_command_api():
    """HTTP fallback for Android clients that can't use WebSockets.

    curl -X POST http://localhost:6769/api/command \\
         -H "Content-Type: application/json" \\
         -d '{"command": "hello"}'
    """
    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "No command provided"}), 400
    print(f"[API] Command: '{command}'")
    response_msg = process_command(command)
    notify_all_clients(response_msg)
    return jsonify({"message": response_msg}), 200


# ------------------------------------------------------------
# Socket.IO Events
# ------------------------------------------------------------
@socketio.on("connect")
def handle_connect():
    connected_clients.add(request.sid)
    print(f"[+] Connected    sid={request.sid}  total={len(connected_clients)}")
    emit("guga_response", {"message": "Connection established. GuGa online."})


@socketio.on("disconnect")
def handle_disconnect():
    connected_clients.discard(request.sid)
    print(f"[-] Disconnected  sid={request.sid}  total={len(connected_clients)}")


@socketio.on("command")
def handle_command(data):
    command = data.get("phrase", "").strip()
    print(f"[WS] Command from {request.sid}: '{command}'")
    emit("guga_response", {"message": process_command(command)})


# ------------------------------------------------------------
# Core Logic
# ------------------------------------------------------------
def process_command(command: str) -> str:
    """Replace this with your real assistant logic."""
    return f"Echo: {command}"


def notify_all_clients(message: str) -> None:
    socketio.emit("guga_response", {"message": message})


def send_private_message(session_id: str, message: str) -> bool:
    if session_id in connected_clients:
        socketio.emit("guga_response", {"message": message}, room=session_id)
        return True
    return False


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------
def get_local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"


# ------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------
if __name__ == "__main__":
    local_ip = get_local_ip()
    base_url = f"http://{local_ip}:{PORT}"

    print(f"\n🚀 GuGa Backend — {base_url}\n")
    print(f"  GET  /ping                — health check")
    print(f"  GET  /clients             — list connected session IDs")
    print(f"  POST /send                — broadcast to ALL clients")
    print(f"  POST /send/<session_id>   — message ONE client")
    print(f"  POST /api/command         — HTTP fallback command\n")

    generate_qr(base_url, inverted=QR_INVERTED, show_gui=QR_SHOW_GUI)

    print(f"\n📱 Manual address: {base_url}")
    print("   Press Ctrl+C to stop.\n")

    socketio.run(app, host=HOST, port=PORT, debug=False, use_reloader=False)