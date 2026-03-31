import base64
import json
import os
import secrets
import socket
import sys
import time
from typing import Set

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
pending_pairings: dict = {}  # device_id -> PIN string
TRUSTED_DEVICES_FILE = "trusted_devices.json"


# ------------------------------------------------------------
# Crypto
# ------------------------------------------------------------
class CryptoHelper:
    @staticmethod
    def encrypt(plaintext_str: str, hex_token: str) -> dict:
        print(f"[CRYPTO] Encrypting: '{plaintext_str}' with token: {hex_token[:8]}...")
        key = bytes.fromhex(hex_token)
        iv = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext_str.encode(), None)
        res = {
            "iv": base64.b64encode(iv).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
        print(f"[CRYPTO] Result: {res}")
        return res

    @staticmethod
    def decrypt(encrypted_dict: dict, hex_token: str) -> str:
        print(f"[CRYPTO] Decrypting payload with token: {hex_token[:8]}...")
        key = bytes.fromhex(hex_token)
        iv = base64.b64decode(encrypted_dict["iv"])
        ciphertext = base64.b64decode(encrypted_dict["ciphertext"])
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None).decode()
        print(f"[CRYPTO] Decrypted: '{plaintext}'")
        return plaintext


def load_trusted_devices() -> dict:
    """Load trusted devices from JSON file."""
    if not os.path.exists(TRUSTED_DEVICES_FILE):
        return {}
    try:
        with open(TRUSTED_DEVICES_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_trusted_device(device_id: str, token: str, client_type: str, expires_at: float) -> None:
    """Persist a paired device's token, type, and expiry to JSON file."""
    devices = load_trusted_devices()
    devices[device_id] = {
        "token": token,
        "type": client_type,
        "expires_at": expires_at,
    }
    with open(TRUSTED_DEVICES_FILE, "w") as f:
        json.dump(devices, f, indent=2)


def is_device_trusted(device_id: str) -> bool:
    trusted = load_trusted_devices()
    entry = trusted.get(device_id)
    if not entry:
        return False

    # Handle legacy string-only tokens (migrate them)
    if isinstance(entry, str):
        print(f"[SECURITY] Migrating legacy entry for {device_id}")
        token = entry
        # Default to 30 days for migrated entries
        expires_at = time.time() + (30 * 24 * 3600)
        save_trusted_device(device_id, token, "app", expires_at)
        return True

    if time.time() >= entry.get("expires_at", 0):
        # Expired, remove entry
        print(f"[SECURITY] Entry for {device_id} EXPIRED. Removing.")
        del trusted[device_id]
        with open(TRUSTED_DEVICES_FILE, "w") as f:
            json.dump(trusted, f, indent=2)
        return False
    return True


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
        let deviceId = localStorage.getItem('guga_device_id');
        if (!deviceId) {
            deviceId = 'browser-' + Math.random().toString(36).substring(2, 15);
            localStorage.setItem('guga_device_id', deviceId);
        }

        let token = localStorage.getItem('guga_token');
        let socket = null;

        const chat   = document.getElementById('chat');
        const status = document.getElementById('status');

        function appendMsg(cls, label, text) {
            const p = document.createElement('p');
            p.className = cls;
            p.textContent = (label ? label + ' ' : '') + text;
            chat.appendChild(p);
            chat.scrollTop = chat.scrollHeight;
        }

        async function initAuth() {
            try {
                const helloRes = await fetch('/api/hello', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_id: deviceId })
                });
                const helloData = await helloRes.json();

                if (helloData.status === 'pin_required') {
                    const pin = prompt('Enter the 8-digit PIN shown on the server console:');
                    if (!pin) {
                        status.textContent = '❌ Pairing cancelled';
                        return;
                    }
                    const verifyRes = await fetch('/api/verify_pin', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ device_id: deviceId, pin: pin, client_type: 'browser' })
                    });
                    const verifyData = await verifyRes.json();
                    if (verifyData.status === 'paired') {
                        token = verifyData.token;
                        localStorage.setItem('guga_token', token);
                        appendMsg('system', '[AUTH]', 'Pairing successful.');
                    } else {
                        status.textContent = '❌ Pairing failed: ' + (verifyData.error || 'Unknown error');
                        return;
                    }
                }
                connectSocket();
            } catch (e) {
                status.textContent = '❌ Auth error: ' + e;
            }
        }

        function connectSocket() {
            // Use query parameters for auth consistent with server code
            socket = io({
                query: { device_id: deviceId, token: token },
                transports: ['websocket', 'polling']
            });

            socket.on('connect', () => {
                status.textContent = '● Connected (' + socket.io.engine.transport.name + ')';
                appendMsg('system', '[SYSTEM]', 'Session active.');
            });

            socket.on('disconnect', (r) => {
                status.textContent = '○ Disconnected';
                appendMsg('system', '[SYSTEM]', 'Disconnected: ' + r);
            });

            socket.on('guga_response', (data) => {
                // Handle both encrypted and unencrypted (though server should encrypt for trusted)
                const msg = data.message || 'Encrypted payload received (decrypt not implemented in browser yet)';
                appendMsg('bot', 'GuGa:', msg);
            });

            socket.on('connect_error', (err) => {
                status.textContent = '❌ Connection Error';
                appendMsg('system', '[ERROR]', err.message);
                if (err.message.includes('rejected')) {
                     localStorage.removeItem('guga_token');
                     status.textContent = '❌ Auth Rejected. Refresh to re-pair.';
                }
            });
        }

        function sendCommand() {
            const input = document.getElementById('commandInput');
            const text  = input.value.trim();
            if (!text || !socket) return;
            appendMsg('you', 'You:', text);
            // Browser dashboard sends plaintext for now, server handles it
            socket.emit('command', { phrase: text, device_id: deviceId });
            input.value = '';
        }

        function handleEnter(e) { if (e.key === 'Enter') sendCommand(); }

        initAuth();
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
    """Broadcast a message to ALL connected clients (localhost only)."""
    # Restrict to localhost requests
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
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
    """Encrypted HTTP fallback for Android clients."""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()

    if not is_device_trusted(device_id):
        return jsonify({"error": "Untrusted device"}), 403

    trusted = load_trusted_devices()
    entry = trusted.get(device_id, {})
    token = entry.get("token")
    try:
        print(f"[API] Received encrypted payload: {data}")
        phrase = CryptoHelper.decrypt(data, token)
        phrase_obj = json.loads(phrase)
        command = phrase_obj.get("phrase", "").strip()
    except Exception as e:
        print(f"[CRYPTO] Decrypt failed: {e}")
        return jsonify({"error": f"Decryption failed: {str(e)}"}), 400

    if not command:
        return jsonify({"error": "No command"}), 400
    print(f"[API] Command from {device_id}: '{command}'")
    response_msg = process_command(command)
    notify_all_clients_encrypted(response_msg, trusted)
    return jsonify({"ok": True}), 200


@app.route("/api/hello", methods=["POST"])
def handle_hello():
    """Device introduces itself. Returns 'trusted' or 'pin_required'."""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    if is_device_trusted(device_id):
        print(f"[SECURITY] Known device reconnected: {device_id}")
        return jsonify({"status": "trusted"}), 200

    # New device — generate PIN
    pin = "".join([str(secrets.randbelow(10)) for _ in range(8)])
    pending_pairings[device_id] = pin
    print(f"\n[SECURITY] New device detected! Pairing PIN: {pin}\n")
    return jsonify({"status": "pin_required"}), 200


@app.route("/api/verify_pin", methods=["POST"])
def handle_verify_pin():
    """Verify the PIN entered by the user. Returns token on success."""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    pin = data.get("pin", "").strip()
    client_type = data.get("client_type", "app").strip()  # default to app

    expected_pin = pending_pairings.get(device_id)
    if not expected_pin or expected_pin != pin:
        print(f"[SECURITY] PIN verification FAILED for device: {device_id}")
        return jsonify({"error": "Invalid PIN"}), 401

    # Determine TTL based on client type
    if client_type == "app":
        ttl_seconds = 30 * 24 * 3600  # 30 days
    else:
        ttl_seconds = 3600  # 1 hour for browser
    expires_at = time.time() + ttl_seconds

    token = secrets.token_hex(32)  # 256-bit secure token
    save_trusted_device(device_id, token, client_type, expires_at)
    pending_pairings.pop(device_id, None)
    print(f"[SECURITY] Device paired successfully: {device_id} (type={client_type}, expires_at={expires_at})")
    return jsonify({"status": "paired", "token": token}), 200


# ------------------------------------------------------------
# Socket.IO Events
# ------------------------------------------------------------
@socketio.on("connect")
def handle_connect():
    # Validate auth token and device_id from query parameters
    device_id = request.args.get('device_id')
    token = request.args.get('token')
    if not device_id or not token or not is_device_trusted(device_id):
        print(f"[SECURITY] Socket connection rejected for device_id={device_id}")
        # Disconnect the client immediately
        return False
    # Verify token matches stored token
    trusted = load_trusted_devices()
    entry = trusted.get(device_id, {})
    if entry.get('token') != token:
        print(f"[SECURITY] Socket token mismatch for device_id={device_id}")
        return False
    connected_clients.add(request.sid)
    print(f"[+] Connected    sid={request.sid}  total={len(connected_clients)} (device_id={device_id})")
    emit("guga_response", {"message": "Connection established. GuGa online."})


@socketio.on("disconnect")
def handle_disconnect():
    connected_clients.discard(request.sid)
    print(f"[-] Disconnected  sid={request.sid}  total={len(connected_clients)}")


@socketio.on("command")
def handle_command(data):
    """Accepts encrypted command payload from trusted Android device."""
    device_id = data.get("device_id", "").strip()
    trusted = load_trusted_devices()

    if device_id not in trusted:
        print(f"[SECURITY] Untrusted command from device: {device_id}")
        emit("error", {"message": "Untrusted device"})
        return

    try:
        print(f"[WS] Received encrypted payload: {data}")
        phrase = CryptoHelper.decrypt(data, trusted[device_id])
        phrase_obj = json.loads(phrase)
        command = phrase_obj.get("phrase", "").strip()
    except Exception as e:
        print(f"[CRYPTO] Decrypt failed for {device_id}: {e}")
        emit("error", {"message": f"Decryption error: {str(e)}"})
        return

    print(f"[WS] Command from {device_id}: '{command}'")
    response_text = process_command(command)
    token = trusted[device_id]
    encrypted_response = CryptoHelper.encrypt(json.dumps({"message": response_text}), token)
    emit("guga_response", encrypted_response)


# ------------------------------------------------------------
# Core Logic
# ------------------------------------------------------------
def process_command(command: str) -> str:
    """Replace this with your real assistant logic."""
    return f"Echo: {command}"


def notify_all_clients(message: str) -> None:
    socketio.emit("guga_response", {"message": message})


def notify_all_clients_encrypted(message: str, trusted_devices: dict) -> None:
    """Emit encrypted guga_response to each connected client using their token."""
    payload = json.dumps({"message": message})
    for device_id, token in trusted_devices.items():
        try:
            encrypted = CryptoHelper.encrypt(payload, token)
            socketio.emit("guga_response", encrypted)
        except Exception as e:
            print(f"[CRYPTO] Failed to encrypt for {device_id}: {e}")


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
    print(f"  POST /api/command         — HTTP fallback command")
    print(f"  POST /api/hello           — device handshake")
    print(f"  POST /api/verify_pin      — PIN verification\n")


    generate_qr(base_url, inverted=QR_INVERTED, show_gui=QR_SHOW_GUI)

    print(f"\n📱 Manual address: {base_url}")
    print("   Press Ctrl+C to stop.\n")

    socketio.run(app, host=HOST, port=PORT, debug=False, use_reloader=False)