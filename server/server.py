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
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GUGA Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;600&display=swap" rel="stylesheet">
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        :root {
            --bg: #000000;
            --surface: #0a0a0a;
            --border: #1a1a1a;
            --text-primary: #ffffff;
            --text-secondary: #444444;
            --accent: #ffffff;
            --font: 'Inter', system-ui, -apple-system, sans-serif;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            background-color: var(--bg);
            color: var(--text-primary);
            font-family: var(--font);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }

        .dashboard {
            width: 100%;
            max-width: 800px;
            height: 90vh;
            display: flex;
            flex-direction: column;
            padding: 40px;
        }

        header {
            text-align: center;
            margin-bottom: 40px;
        }

        h1 {
            font-size: 3rem;
            font-weight: 200;
            letter-spacing: 0.3em;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        #status {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        #chat {
            flex: 1;
            overflow-y: auto;
            margin-bottom: 32px;
            padding-right: 20px;
            scrollbar-width: thin;
            scrollbar-color: var(--border) transparent;
        }

        #chat::-webkit-scrollbar { width: 4px; }
        #chat::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

        .msg {
            margin-bottom: 16px;
            line-height: 1.6;
            font-size: 0.95rem;
            animation: fadeIn 0.4s ease forwards;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .system { color: var(--text-secondary); font-size: 0.8rem; font-weight: 300; }
        .bot { font-weight: 400; }
        .you { color: var(--text-secondary); }

        .input-area {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
            display: flex;
            padding: 4px;
            transition: border-color 0.3s;
        }

        .input-area:focus-within {
            border-color: #333;
        }

        #commandInput {
            flex: 1;
            background: transparent;
            border: none;
            color: var(--text-primary);
            padding: 14px 20px;
            font-size: 0.9rem;
            font-weight: 300;
            outline: none;
        }

        #commandInput::placeholder { color: #222; }

        button {
            background: var(--accent);
            color: #000;
            border: none;
            padding: 0 32px;
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            cursor: pointer;
            transition: opacity 0.2s;
            border-radius: 2px;
        }

        button:hover { opacity: 0.9; }

        /* Mobile Adjustments */
        @media (max-width: 600px) {
            .dashboard { padding: 20px; height: 100vh; }
            h1 { font-size: 2rem; }
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <header>
            <h1>GUGA</h1>
            <div id="status">Establishing connection...</div>
        </header>

        <div id="chat"></div>

        <div class="input-area">
            <input type="text" id="commandInput" placeholder="TYPE COMMAND..." onkeydown="handleEnter(event)" autocomplete="off">
            <button onclick="sendCommand()">SEND</button>
        </div>
    </div>

    <script>
        let deviceId = localStorage.getItem('guga_device_id');
        if (!deviceId) {
            deviceId = 'browser-' + Math.random().toString(36).substring(2, 15);
            localStorage.setItem('guga_device_id', deviceId);
        }

        let token = localStorage.getItem('guga_token');
        let socket = null;

        const chatDisplay = document.getElementById('chat');
        const statusDisplay = document.getElementById('status');

        function appendMsg(cls, label, text) {
            const div = document.createElement('div');
            div.className = 'msg ' + cls;
            div.innerHTML = (label ? `<span style="opacity: 0.5; margin-right: 8px;">${label}</span>` : '') + text;
            chatDisplay.appendChild(div);
            chatDisplay.scrollTop = chatDisplay.scrollHeight;
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
                    const pin = prompt('ENTER PAIRING PIN:');
                    if (!pin) {
                        statusDisplay.textContent = 'ERROR: PAIRING CANCELLED';
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
                        appendMsg('system', 'AUTH', 'AUTHENTICATED');
                    } else {
                        statusDisplay.textContent = 'ERROR: ' + (verifyData.error || 'INVALID PIN');
                        return;
                    }
                }
                connectSocket();
            } catch (e) {
                statusDisplay.textContent = 'ERROR: ' + e;
            }
        }

        function connectSocket() {
            socket = io({
                query: { device_id: deviceId, token: token },
                transports: ['websocket', 'polling']
            });

            socket.on('connect', () => {
                statusDisplay.textContent = 'SECURE CONNECTION ACTIVE';
                appendMsg('system', 'SYS', 'HANDSHAKE COMPLETE');
            });

            socket.on('disconnect', (reason) => {
                statusDisplay.textContent = 'OFFLINE';
                appendMsg('system', 'SYS', 'CONNECTION LOST: ' + reason);
            });

            socket.on('guga_response', (data) => {
                const msg = data.message || 'ENCRYPTED PAYLOAD';
                appendMsg('bot', 'GUGA', msg);
            });

            socket.on('connect_error', (err) => {
                statusDisplay.textContent = 'CONNECTION REFUSED';
                appendMsg('system', 'ERR', err.message);
                if (err.message.includes('rejected')) {
                     localStorage.removeItem('guga_token');
                     statusDisplay.textContent = 'AUTH REVOKED. REFRESH TO RE-PAIR.';
                }
            });
        }

        function sendCommand() {
            const input = document.getElementById('commandInput');
            const text  = input.value.trim();
            if (!text || !socket) return;
            appendMsg('you', 'USER', text);
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
    if not token:
        return jsonify({"error": "No token for device"}), 403
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

    force_pair = data.get("force_pair", False)

    if is_device_trusted(device_id) and not force_pair:
        print(f"[SECURITY] Known device reconnected: {device_id}")
        return jsonify({"status": "trusted"}), 200

    # New device or force_pair — generate PIN
    pin = "".join([str(secrets.randbelow(10)) for _ in range(8)])
    pending_pairings[device_id] = pin
    if force_pair:
        print(f"\n[SECURITY] Device {device_id} requested RE-PAIRING. PIN: {pin}\n")
    else:
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
        token = trusted[device_id].get("token")
        if not token:
            raise ValueError("No token in trusted list")
        phrase = CryptoHelper.decrypt(data, token)
        phrase_obj = json.loads(phrase)
        command = phrase_obj.get("phrase", "").strip()
    except Exception as e:
        print(f"[CRYPTO] Decrypt failed for {device_id}: {e}")
        emit("error", {"message": f"Decryption error: {str(e)}"})
        return

    print(f"[WS] Command from {device_id}: '{command}'")
    response_text = process_command(command)
    token = trusted[device_id].get("token")
    if not token:
        print(f"[CRYPTO] No token for device {device_id}")
        return
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
    for device_id, device_info in trusted_devices.items():
        try:
            token = device_info.get("token")
            if not token: continue
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

    socketio.run(app, host=HOST, port=PORT, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)