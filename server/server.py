import atexit
import base64
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Set

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

# Enforce Linux-only restriction
if platform.system() != "Linux":
    print("❌ ERROR: This server is designed to run on Linux only.")
    print(f"Current OS: {platform.system()}")
    sys.exit(1)

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

connected_clients: dict[str, str] = {}  # session_id -> device_id
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
        # Auto-detect type from prefix
        client_type = "browser" if device_id.startswith("browser-") else "app"
        # Default to 30 days for migrated entries
        expires_at = time.time() + (30 * 24 * 3600)
        save_trusted_device(device_id, token, client_type, expires_at)
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>GuGa</title>
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }

        html, body {
            height: 100%;
            overscroll-behavior: none;
        }

        body {
            background: #000;
            color: #fff;
            font-family: 'Nunito', sans-serif;
            display: flex;
            justify-content: center;
            position: fixed;
            inset: 0;
            overflow: hidden;
        }

        .shell {
            width: 100%;
            max-width: 600px;
            height: 100%;
            display: flex;
            flex-direction: column;
            padding-top: env(safe-area-inset-top, 0px);
            padding-bottom: env(safe-area-inset-bottom, 0px);
        }

        /* ── Header ── */
        .hdr {
            flex-shrink: 0;
            padding: 24px 22px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .logo {
            font-size: 2rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            line-height: 1;
        }

        .status-pill {
            display: flex;
            align-items: center;
            gap: 7px;
            background: #111;
            border-radius: 999px;
            padding: 7px 14px 7px 10px;
            font-size: 0.7rem;
            font-weight: 700;
            color: #555;
            letter-spacing: 0.03em;
            transition: color 0.3s;
        }

        .dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #333;
            flex-shrink: 0;
            transition: background 0.3s;
        }

        .dot.online  { background: #fff; animation: blink 2.5s ease-in-out infinite; }
        .dot.waiting { background: #666; animation: blink 1s ease-in-out infinite; }
        .dot.error   { background: #555; }

        @keyframes blink {
            0%, 100% { opacity: 1; }
            50%       { opacity: 0.3; }
        }

        /* ── Feed ── */
        .feed {
            flex: 1;
            overflow-y: auto;
            overflow-x: hidden;
            padding: 8px 18px 4px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }
        .feed::-webkit-scrollbar { display: none; }

        /* ── Bubbles ── */
        .bubble {
            max-width: 82%;
            padding: 10px 16px;
            border-radius: 22px;
            font-size: 0.88rem;
            font-weight: 600;
            line-height: 1.45;
            animation: pop 0.2s cubic-bezier(0.34, 1.56, 0.64, 1) both;
            word-break: break-word;
        }

        @keyframes pop {
            from { opacity: 0; transform: scale(0.85); }
            to   { opacity: 1; transform: scale(1); }
        }

        .bubble.sys {
            align-self: center;
            background: transparent;
            color: #333;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            padding: 2px 0;
            max-width: 100%;
            text-align: center;
            animation: none;
        }

        .bubble.bot {
            align-self: flex-start;
            background: #fff;
            color: #000;
            border-bottom-left-radius: 6px;
        }

        .bubble.usr {
            align-self: flex-end;
            background: #1a1a1a;
            color: #fff;
            border-bottom-right-radius: 6px;
        }

        /* Typing indicator */
        .typing-bubble {
            align-self: flex-start;
            background: #fff;
            border-radius: 22px;
            border-bottom-left-radius: 6px;
            padding: 12px 18px;
            margin: 0 18px 4px;
            display: none;
            gap: 5px;
            align-items: center;
        }
        .typing-bubble.active { display: flex; }

        .typing-bubble span {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #000;
            animation: bounce 1.1s ease-in-out infinite;
        }
        .typing-bubble span:nth-child(2) { animation-delay: 0.18s; }
        .typing-bubble span:nth-child(3) { animation-delay: 0.36s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
            40%           { transform: translateY(-5px); opacity: 1; }
        }

        /* ── Input Row ── */
        .input-row {
            flex-shrink: 0;
            padding: 10px 16px 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        #cmdInput {
            flex: 1;
            background: #111;
            border: none;
            border-radius: 999px;
            color: #fff;
            font-family: 'Nunito', sans-serif;
            font-size: 16px;
            font-weight: 600;
            padding: 13px 20px;
            outline: none;
            -webkit-appearance: none;
            transition: background 0.2s;
        }

        #cmdInput::placeholder {
            color: #333;
            font-weight: 600;
        }

        #cmdInput:focus {
            background: #141414;
        }

        .send-btn {
            width: 46px;
            height: 46px;
            border-radius: 50%;
            border: none;
            background: #fff;
            color: #000;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            transition: transform 0.12s, background 0.15s;
            -webkit-appearance: none;
        }

        .send-btn:active {
            transform: scale(0.88);
            background: #ddd;
        }

        .send-btn svg {
            width: 18px;
            height: 18px;
            stroke: #000;
            fill: none;
            stroke-width: 2.2;
            stroke-linecap: round;
            stroke-linejoin: round;
        }

        @media (max-width: 400px) {
            .hdr { padding: 18px 16px 12px; }
            .feed { padding: 6px 14px 4px; }
            .input-row { padding: 8px 12px 14px; }
        }
    </style>
</head>
<body>
<div class="shell">

    <div class="hdr">
        <div class="logo">guga.</div>
        <div class="status-pill">
            <div class="dot" id="statusDot"></div>
            <span id="statusText">starting up</span>
        </div>
    </div>

    <div class="feed" id="feed"></div>

    <div class="typing-bubble" id="typing">
        <span></span><span></span><span></span>
    </div>

    <div class="input-row">
        <input
            type="text"
            id="cmdInput"
            placeholder="say something..."
            autocomplete="off"
            autocorrect="off"
            autocapitalize="off"
            spellcheck="false"
            inputmode="text"
            onkeydown="onKey(event)"
        />
        <button class="send-btn" onclick="sendCommand()">
            <svg viewBox="0 0 18 18">
                <line x1="2" y1="9" x2="16" y2="9"/>
                <polyline points="10,3 16,9 10,15"/>
            </svg>
        </button>
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

    const feed      = document.getElementById('feed');
    const statusDot = document.getElementById('statusDot');
    const statusTxt = document.getElementById('statusText');
    const typingEl  = document.getElementById('typing');

    function setStatus(label, state) {
        statusTxt.textContent = label;
        statusDot.className = 'dot ' + (state || '');
    }

    function addBubble(cls, text) {
        const div = document.createElement('div');
        div.className = 'bubble ' + cls;
        div.textContent = text;
        feed.appendChild(div);
        feed.scrollTo({ top: feed.scrollHeight, behavior: 'smooth' });
    }

    function onKey(e) { if (e.key === 'Enter') sendCommand(); }

    async function initAuth() {
        setStatus('connecting...', 'waiting');
        try {
            const helloRes = await fetch('/api/hello', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: deviceId })
            });
            const helloData = await helloRes.json();

            if (helloData.status === 'pin_required') {
                const pin = prompt('enter pairing pin:');
                if (!pin) { setStatus('cancelled', 'error'); return; }
                const verifyRes = await fetch('/api/verify_pin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_id: deviceId, pin: pin, client_type: 'browser' })
                });
                const verifyData = await verifyRes.json();
                if (verifyData.status === 'paired') {
                    token = verifyData.token;
                    localStorage.setItem('guga_token', token);
                    addBubble('sys', 'paired ✓');
                } else {
                    setStatus('auth failed', 'error');
                    addBubble('sys', verifyData.error || 'invalid pin');
                    return;
                }
            }
            connectSocket();
        } catch (e) {
            setStatus('error', 'error');
            addBubble('sys', String(e));
        }
    }

    function connectSocket() {
        let shownDisconnect = false;

        socket = io({
            query: { device_id: deviceId, token: token },
            transports: ['websocket', 'polling']
        });

        socket.on('connect', () => {
            shownDisconnect = false;
            setStatus('online', 'online');
            addBubble('sys', 'connected');
        });

        socket.on('disconnect', () => {
            if (!shownDisconnect) {
                shownDisconnect = true;
                setStatus('offline', 'error');
                addBubble('sys', 'disconnected');
            }
        });

        socket.on('guga_response', (data) => {
            typingEl.classList.remove('active');
            addBubble('bot', data.message || 'encrypted payload');
        });

        socket.on('connect_error', (err) => {
            if (err.message.includes('rejected')) {
                localStorage.removeItem('guga_token');
                setStatus('auth revoked', 'error');
                if (!shownDisconnect) {
                    shownDisconnect = true;
                    addBubble('sys', 'token revoked — refresh to re-pair');
                }
            } else if (!shownDisconnect) {
                shownDisconnect = true;
                setStatus('offline', 'error');
                addBubble('sys', 'disconnected');
            }
        });
    }

    function sendCommand() {
        const input = document.getElementById('cmdInput');
        const text = input.value.trim();
        if (!text || !socket) return;
        addBubble('usr', text);
        socket.emit('command', { phrase: text, device_id: deviceId });
        input.value = '';
        typingEl.classList.add('active');
        feed.scrollTo({ top: feed.scrollHeight, behavior: 'smooth' });
    }

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
    notify_all_clients(response_msg)
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
    connected_clients[request.sid] = device_id
    print(f"[+] Connected    sid={request.sid}  total={len(connected_clients)} (device_id={device_id})")
    send_private_message(request.sid, "Connection established. GuGu online.")


@socketio.on("disconnect")
def handle_disconnect():
    connected_clients.pop(request.sid, None)
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
        print(f"[WS] Incoming payload: {data}")
        token = trusted[device_id].get("token")
        client_type = trusted[device_id].get("type", "app")
        
        # Determine if we should attempt decryption
        if "iv" in data and "ciphertext" in data and token:
            print(f"[CRYPTO] Decrypting payload with token: {token[:8]}...")
            phrase_json = CryptoHelper.decrypt(data, token)
            phrase_obj = json.loads(phrase_json)
            command = phrase_obj.get("phrase", "").strip()
        elif client_type == "browser":
            # Allow plaintext for browsers
            print(f"[SECURITY] Allowing plaintext command for browser device: {device_id}")
            command = data.get("phrase", "").strip()
        else:
            raise ValueError("Encrypted payload required for app clients")
            
    except Exception as e:
        print(f"[CRYPTO] Process failed for {device_id}: {e}")
        emit("error", {"message": f"Processing error: {str(e)}"})
        return

    print(f"[WS] Command from {device_id}: '{command}'")
    response_text = process_command(command)
    notify_all_clients(response_text)


# ------------------------------------------------------------
# Core Logic
# ------------------------------------------------------------
def process_command(command: str) -> str:
    """Take the command and return a temporary not found message."""
    return f"Command '{command}' not found. Please wait for the admin to update the command list."


def notify_all_clients(message: str) -> None:
    """Emit guga_response to all connected clients (encrypted for apps, plain for browsers)."""
    trusted = load_trusted_devices()
    payload_json = json.dumps({"message": message})
    
    # Iterate over active sessions
    for sid, device_id in list(connected_clients.items()):
        try:
            device_info = trusted.get(device_id, {})
            client_type = device_info.get("type", "app")
            token = device_info.get("token")

            if client_type == "browser" or device_id.startswith("browser-") or not token:
                # Send plaintext for browsers
                print(f"[WS] Sending PLAIN to {sid} ({device_id})")
                socketio.emit("guga_response", {"message": message}, room=sid)
            else:
                # Encrypt for apps
                print(f"[WS] Sending ENCRYPTED to {sid} ({device_id})")
                encrypted = CryptoHelper.encrypt(payload_json, token)
                socketio.emit("guga_response", encrypted, room=sid)
        except Exception as e:
            print(f"[CRYPTO] Failed to send to {sid} ({device_id}): {e}")


def send_private_message(session_id: str, message: str) -> bool:
    """Send a private message to a specific session, with encryption if applicable."""
    if session_id not in connected_clients:
        return False
        
    device_id = connected_clients[session_id]
    trusted = load_trusted_devices()
    device_info = trusted.get(device_id, {})
    client_type = device_info.get("type", "app")
    token = device_info.get("token")
    payload_json = json.dumps({"message": message})

    try:
        if client_type == "browser" or not token:
            socketio.emit("guga_response", {"message": message}, room=session_id)
        else:
            encrypted = CryptoHelper.encrypt(payload_json, token)
            socketio.emit("guga_response", encrypted, room=session_id)
        return True
    except Exception as e:
        print(f"[CRYPTO] Private send failed for {session_id}: {e}")
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


def start_cloudflare_tunnel(port: int) -> str:
    """Start an ephemeral Cloudflare tunnel and capture the URL."""
    print(f"[NETWORK] Spawning Cloudflare Tunnel for port {port}...")
    
    # Determine local binary path
    filename = "cloudflared.exe" if platform.system().lower() == "windows" else "./cloudflared"
    # Ensure it's the one in the same dir as server.py
    cloudflare_cmd = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    
    # If not found locally, try global
    if not os.path.exists(cloudflare_cmd):
        cloudflare_cmd = "cloudflared"

    proc = subprocess.Popen(
        [cloudflare_cmd, "tunnel", "--url", f"http://localhost:{port}"],
        stderr=subprocess.PIPE,
        text=True
    )
    # Ensure the tunnel dies when the main process exits
    atexit.register(lambda: proc.terminate())
    
    url_pattern = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
    
    # Read stderr to find the URL
    for line in iter(proc.stderr.readline, ""):
        match = url_pattern.search(line)
        if match:
            url = match.group(0)
            return url
    return ""


# ------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------
# ------------------------------------------------------------
# OS Notification Alerter Lifecycle
# ------------------------------------------------------------
alerter_proc = None

def start_alerter():
    global alerter_proc
    val = os.getenv("ENABLE_OS_NOTIFICATIONS", "False")
    print(f"[DEBUG] ENABLE_OS_NOTIFICATIONS value: '{val}'")
    if val.lower() == "true":
        print("[OS ADAPTER] Starting OS Notification Alerter...")
        # Use the local venv python if available
        venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python3")
        if not os.path.exists(venv_python):
            venv_python = "python3" # Fallback
            
        alerter_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "os_notification_alerter.py")
        try:
            # We use a new session to ensure it doesn't immediately die if the shell is closed, 
            # though here it's managed by the server proc.
            alerter_proc = subprocess.Popen([venv_python, alerter_script])
        except Exception as e:
            print(f"[OS ADAPTER] Failed to start alerter binary: {e}")

def stop_alerter():
    global alerter_proc
    if alerter_proc:
        print("[OS ADAPTER] Stopping OS Notification Alerter...")
        alerter_proc.terminate()
        try:
            alerter_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            alerter_proc.kill()

atexit.register(stop_alerter)

if __name__ == "__main__":
    start_alerter()
    mode = os.getenv("MODE", "lan").lower()
    port = int(os.getenv("PORT", 6769))
    
    if mode == "public":
        public_url = start_cloudflare_tunnel(port)
        if public_url:
            base_url = public_url
            print(f"\n[NETWORK] Cloudflare Tunnel Active: {base_url}\n")
        else:
            print("\n[ERROR] Failed to start Cloudflare Tunnel. Falling back to LAN.\n")
            local_ip = get_local_ip()
            base_url = f"http://{local_ip}:{port}"
    else:
        local_ip = get_local_ip()
        base_url = f"http://{local_ip}:{port}"

    print(f"🚀 GuGa Backend — {base_url}\n")
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

    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)