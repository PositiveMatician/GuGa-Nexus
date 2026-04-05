import eventlet
eventlet.monkey_patch()

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

CONFIG_DIR = os.path.expanduser("~/.guga")
if not os.path.exists(CONFIG_DIR):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception:
        pass

env_path = os.path.join(CONFIG_DIR, '.env')
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
VERBOSE = os.getenv("GUGA_VERBOSE", "false").lower() == "true"

# ── Silence werkzeug's per-request HTTP logs ──────────────────────────────────
import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ── Logging helpers ───────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"

def log(msg: str) -> None:
    """Standard info log — always shown."""
    print(f"  {msg}")

def log_event(symbol: str, color: str, label: str, detail: str = "") -> None:
    """Structured event line: symbol  LABEL  detail"""
    detail_str = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {color}{symbol}{RESET}  {BOLD}{label}{RESET}{detail_str}")

def log_debug(msg: str) -> None:
    """Only shown when GUGA_VERBOSE=true."""
    if VERBOSE:
        print(f"  {DIM}[debug] {msg}{RESET}")

def print_pin_box(pin: str, label: str = "PAIRING PIN") -> None:
    """Print a highly visible bordered box around the PIN."""
    width = 30
    border = "─" * width
    pin_spaced = "  ".join(pin)
    pad = (width - len(pin_spaced)) // 2
    pin_line = " " * pad + pin_spaced

    print()
    print(f"  {YELLOW}┌{border}┐{RESET}")
    print(f"  {YELLOW}│{RESET}  {DIM}{label}{RESET}{' ' * (width - len(label) - 2)}{YELLOW}│{RESET}")
    print(f"  {YELLOW}│{RESET}{' ' * width}{YELLOW}│{RESET}")
    print(f"  {YELLOW}│{RESET}{BOLD}{GREEN}{pin_line}{' ' * (width - len(pin_line))}{RESET}{YELLOW}│{RESET}")
    print(f"  {YELLOW}│{RESET}{' ' * width}{YELLOW}│{RESET}")
    print(f"  {YELLOW}└{border}┘{RESET}\033[8m[GUGA_PIN] {pin}\033[0m")
    print()

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

    print(f"\n  {'─' * 38}")
    print(f"   Scan with GuGa app  ·  or enter address manually")
    print(f"  {'─' * 38}\n")
    try:
        qr.print_ascii(invert=inverted)
    except Exception as e:
        print(f"  ⚠ Could not render QR: {e}", file=sys.stderr)


# ------------------------------------------------------------
# Flask App & SocketIO
# ------------------------------------------------------------
app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ALLOWED_ORIGINS,
    async_mode="eventlet",
)

connected_clients: dict[str, str] = {}  # session_id -> device_id
pending_pairings: dict = {}
# Structure per entry:
# {
#   "pin": "47291835",
#   "device_name": "Pixel 7",
#   "requested_at": 1712345678.0,
#   "attempts": 0,
#   "approved": False
# }

blocked_devices: dict = {}
# Structure per entry: { device_id: unblock_timestamp }

TRUSTED_DEVICES_FILE = os.path.join(CONFIG_DIR, "trusted_devices.json")


def clean_expired_pairings():
    """Remove pending entries older than 5 minutes."""
    now = time.time()
    expired = [d for d, e in pending_pairings.items()
               if now - e["requested_at"] > 300]
    for d in expired:
        del pending_pairings[d]


# ------------------------------------------------------------
# Crypto
# ------------------------------------------------------------
class CryptoHelper:
    @staticmethod
    def encrypt(plaintext_str: str, hex_token: str) -> dict:
        log_debug(f"encrypting with token {hex_token[:8]}…")
        key = bytes.fromhex(hex_token)
        iv = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext_str.encode(), None)
        return {
            "iv": base64.b64encode(iv).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }

    @staticmethod
    def decrypt(encrypted_dict: dict, hex_token: str) -> str:
        log_debug(f"decrypting with token {hex_token[:8]}…")
        key = bytes.fromhex(hex_token)
        iv = base64.b64decode(encrypted_dict["iv"])
        ciphertext = base64.b64decode(encrypted_dict["ciphertext"])
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(iv, ciphertext, None).decode()


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
        log_debug(f"migrating legacy entry for {device_id}")
        token = entry
        client_type = "browser" if device_id.startswith("browser-") else "app"
        expires_at = time.time() + (30 * 24 * 3600)
        save_trusted_device(device_id, token, client_type, expires_at)
        return True

    if time.time() >= entry.get("expires_at", 0):
        log_event("⚠", YELLOW, "device expired", device_id)
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

        .bubble.title {
            align-self: flex-start;
            background: transparent;
            color: #555;
            font-size: 0.65rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            padding: 0 0 2px 4px;
            margin-bottom: -4px;
            max-width: 100%;
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

    function addNotification(title, message) {
        if (title) {
            addBubble('title', title);
        }
        addBubble('bot', message);
    }

    function onKey(e) { if (e.key === 'Enter') sendCommand(); }

    async function initAuth() {
        setStatus('connecting...', 'waiting');
        try {
            // Generate a random 8-digit PIN locally
            const pin = Array.from({length: 8}, () => Math.floor(Math.random() * 10)).join('');
            
            const helloRes = await fetch('/api/hello', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    device_id: deviceId, 
                    pin: pin,
                    device_name: navigator.userAgent.includes("Firefox") ? "Firefox" : 
                                 navigator.userAgent.includes("Chrome") ? "Chrome" : "Browser"
                })
            });
            const helloData = await helloRes.json();

            if (helloData.status === 'pin_required') {
                addBubble('sys', 'Your PIN: ' + pin.split('').join(' '));
                addBubble('sys', 'Run `guga --approve` on your Linux machine');
                
                // Poll for approval
                let attempts = 0;
                const pollInterval = setInterval(async () => {
                    attempts++;
                    if (attempts > 60) { // 5 minutes (5s * 60)
                        clearInterval(pollInterval);
                        setStatus('expired', 'error');
                        addBubble('sys', 'Pairing request expired.');
                        return;
                    }
                    
                    try {
                        const verifyRes = await fetch('/api/verify_pin', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ device_id: deviceId, pin: pin, client_type: 'browser' })
                        });
                        const verifyData = await verifyRes.json();
                        
                        if (verifyData.status === 'paired') {
                            clearInterval(pollInterval);
                            token = verifyData.token;
                            localStorage.setItem('guga_token', token);
                            addBubble('sys', 'paired ✓');
                            connectSocket();
                        } else if (verifyRes.status === 401 && verifyData.error === "too many attempts") {
                            clearInterval(pollInterval);
                            setStatus('blocked', 'error');
                            addBubble('sys', 'Too many failed attempts.');
                        }
                    } catch (e) {}
                }, 5000);
                
                setStatus('waiting for approval...', 'waiting');
                return;
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
            if (data.title || data.message) {
                addNotification(data.title, data.message || 'encrypted payload');
            }
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
    title = data.get("title", "").strip()
    if not message:
        return jsonify({"error": "No message provided"}), 400
    notify_all_clients(message, title)
    return jsonify({"ok": True, "sent_to": len(connected_clients)}), 200


@app.route("/send/<session_id>", methods=["POST"])
def send_to_one(session_id: str):
    """Send a message to ONE specific client by session ID."""
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
        log_debug(f"received encrypted payload from {device_id}")
        phrase = CryptoHelper.decrypt(data, token)
        phrase_obj = json.loads(phrase)
        command = phrase_obj.get("phrase", "").strip()
    except Exception as e:
        log_event("✗", RED, "decrypt failed", str(e))
        return jsonify({"error": f"Decryption failed: {str(e)}"}), 400

    if not command:
        return jsonify({"error": "No command"}), 400
    log_event("→", CYAN, "command (HTTP)", f"{device_id}: {command!r}")
    response_msg = process_command(command)
    notify_all_clients(response_msg)
    return jsonify({"ok": True}), 200


@app.route("/api/hello", methods=["POST"])
def handle_hello():
    """Device introduces itself. Returns 'trusted' or 'pin_required'."""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    pin = data.get("pin", "").strip()
    device_name = data.get("device_name", "Unknown Device").strip()

    if not device_id:
        return jsonify({"error": "device_id required"}), 400

    # New device or force_pair logic
    force_pair = data.get("force_pair", False)

    if is_device_trusted(device_id) and not force_pair:
        log_event("↩", CYAN, "device reconnected", device_id)
        return jsonify({"status": "trusted"}), 200

    # From Phase 20.1: Client-generated PIN is required for pairing
    if not pin:
        return jsonify({"error": "pin required for pairing"}), 400
    if not pin.isdigit() or len(pin) != 8:
        return jsonify({"error": "pin must be 8 digits"}), 400

    # Check blocklist
    if device_id in blocked_devices:
        if time.time() < blocked_devices[device_id]:
            return jsonify({"error": "too many failed attempts"}), 429
        else:
            del blocked_devices[device_id]

    clean_expired_pairings()

    # Store pending pairing
    pending_pairings[device_id] = {
        "pin": pin,
        "device_name": device_name,
        "requested_at": time.time(),
        "attempts": 0,
        "approved": False
    }

    log_event("?", YELLOW, "pairing request", f"{device_name} ({device_id[:8]}...) - PIN: {pin}")
    return jsonify({"status": "pin_required"}), 200


@app.route("/api/verify_pin", methods=["POST"])
def handle_verify_pin():
    """Wait for authorization. Returns token on success."""
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    pin = data.get("pin", "").strip()
    client_type = data.get("client_type", "app").strip()

    entry = pending_pairings.get(device_id)
    if not entry:
        return jsonify({"error": "No pending pairing for this device"}), 404

    # The client must provide the same PIN it sent in /api/hello
    if entry["pin"] != pin:
        entry["attempts"] += 1
        if entry["attempts"] >= 5:
            del pending_pairings[device_id]
            blocked_devices[device_id] = time.time() + 600  # 10 min
            return jsonify({"error": "too many attempts"}), 401
        return jsonify({"error": "Invalid PIN"}), 401

    if not entry["approved"]:
        return jsonify({"status": "waiting_for_approval"}), 202

    # Approved! Determine TTL based on client type
    ttl_seconds = (30 * 24 * 3600) if client_type == "app" else 3600
    expires_at = time.time() + ttl_seconds

    token = secrets.token_hex(32)
    save_trusted_device(device_id, token, client_type, expires_at)
    pending_pairings.pop(device_id, None)

    log_event("✓", GREEN, "device paired", f"{device_id}  type={client_type}")
    return jsonify({"status": "paired", "token": token}), 200


@app.route("/api/pending", methods=["GET"])
def get_pending():
    """List pending pairing requests (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
    clean_expired_pairings()
    result = [
        {
            "device_id": did,
            "device_name": entry["device_name"],
            "pin": entry["pin"],
            "requested_at": entry["requested_at"],
            "attempts": entry["attempts"],
        }
        for did, entry in pending_pairings.items() if not entry["approved"]
    ]
    # Sort newest first
    result.sort(key=lambda x: x["requested_at"], reverse=True)
    return jsonify({"pending": result[:5]}), 200


@app.route("/api/approve", methods=["POST"])
def approve_device():
    """Approve or reject a specific device (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    action = data.get("action", "").strip()  # "approve" or "reject"

    if action == "approve":
        entry = pending_pairings.get(device_id)
        if not entry:
            return jsonify({"error": "No pending pairing for this device"}), 404
        entry["approved"] = True
        log_event("✓", GREEN, "pairing approved", f"{entry['device_name']} ({device_id[:8]}...)")
        return jsonify({"status": "approved"}), 200

    elif action == "reject":
        pending_pairings.pop(device_id, None)
        blocked_devices[device_id] = time.time() + 600
        log_event("✗", RED, "pairing rejected", device_id)
        return jsonify({"status": "rejected"}), 200

    return jsonify({"error": "action must be approve or reject"}), 400


# ------------------------------------------------------------
# Socket.IO Events
# ------------------------------------------------------------
@socketio.on("connect")
def handle_connect():
    # Validate auth token and device_id from query parameters
    device_id = request.args.get('device_id')
    token = request.args.get('token')
    if not device_id or not token or not is_device_trusted(device_id):
        log_event("✗", RED, "connection rejected", f"device_id={device_id}")
        return False
    trusted = load_trusted_devices()
    entry = trusted.get(device_id, {})
    if entry.get('token') != token:
        log_event("✗", RED, "token mismatch", f"device_id={device_id}")
        return False
    connected_clients[request.sid] = device_id
    log_event("↑", GREEN, "connected", f"{device_id}  ({len(connected_clients)} online)")
    send_private_message(request.sid, "Connection established. GuGu online.")


@socketio.on("disconnect")
def handle_disconnect():
    connected_clients.pop(request.sid, None)
    log_event("↓", DIM, "disconnected", f"({len(connected_clients)} online)")


@socketio.on("command")
def handle_command(data):
    """Accepts encrypted command payload from trusted Android device."""
    device_id = data.get("device_id", "").strip()
    trusted = load_trusted_devices()

    if device_id not in trusted:
        log_event("✗", RED, "untrusted command", device_id)
        emit("error", {"message": "Untrusted device"})
        return

    try:
        log_debug(f"incoming WS payload from {device_id}")
        token = trusted[device_id].get("token")
        client_type = trusted[device_id].get("type", "app")
        
        if "iv" in data and "ciphertext" in data and token:
            phrase_json = CryptoHelper.decrypt(data, token)
            phrase_obj = json.loads(phrase_json)
            command = phrase_obj.get("phrase", "").strip()
        elif client_type == "browser":
            log_debug(f"plaintext command for browser device: {device_id}")
            command = data.get("phrase", "").strip()
        else:
            raise ValueError("Encrypted payload required for app clients")
            
    except Exception as e:
        log_event("✗", RED, "processing error", str(e))
        emit("error", {"message": f"Processing error: {str(e)}"})
        return

    log_event("→", CYAN, "command", f"{device_id}: {command!r}")
    response_text = process_command(command)
    notify_all_clients(response_text)


# ------------------------------------------------------------
# Core Logic
# ------------------------------------------------------------
def process_command(command: str) -> str:
    """Take the command and return a temporary not found message."""
    return f"Command '{command}' not found. Please wait for the admin to update the command list."


def notify_all_clients(message: str, title: str = None) -> None:
    """Emit guga_response to all connected clients."""
    trusted = load_trusted_devices()
    payload_data = {"message": message}
    if title:
        payload_data["title"] = title
    payload_json = json.dumps(payload_data)
    
    for sid, device_id in list(connected_clients.items()):
        try:
            device_info = trusted.get(device_id, {})
            client_type = device_info.get("type", "app")
            token = device_info.get("token")

            if client_type == "browser" or device_id.startswith("browser-") or not token:
                socketio.emit("guga_response", payload_data, room=sid)
            else:
                encrypted = CryptoHelper.encrypt(payload_json, token)
                socketio.emit("guga_response", encrypted, room=sid)
        except Exception as e:
            log_event("✗", RED, "send failed", f"{sid} ({device_id}): {e}")


def send_private_message(session_id: str, message: str) -> bool:
    """Send a private message to a specific session."""
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
        log_event("✗", RED, "private send failed", f"{session_id}: {e}")
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
    log_event("⚙", CYAN, f"spawning tunnel on port {port}...")
    
    filename = "cloudflared.exe" if platform.system().lower() == "windows" else "./cloudflared"
    cloudflare_cmd = os.path.join(CONFIG_DIR, filename)
    
    if not os.path.exists(cloudflare_cmd):
        cloudflare_cmd = "cloudflared"

    proc = subprocess.Popen(
        [cloudflare_cmd, "tunnel", "--url", f"http://localhost:{port}"],
        stderr=subprocess.PIPE,
        text=True
    )
    atexit.register(lambda: proc.terminate())
    
    url_pattern = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
    
    # Read stderr to find the URL
    for line in iter(proc.stderr.readline, ""):
        match = url_pattern.search(line)
        if match:
            url = match.group(0)
            return url
    return ""


# ── Background Process Lifecycle ──────────────────────────────────────────
alerter_proc = None
tunnel_url = None

def start_alerter():
    global alerter_proc
    val = os.getenv("ENABLE_OS_NOTIFICATIONS", "False")
    log_debug(f"ENABLE_OS_NOTIFICATIONS={val!r}")
    if val.lower() == "true":
        # Use sys.executable directly since pip manages packages globally or in an activated virtualenv
        venv_python = sys.executable
        alerter_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerter.py")
        try:
            log_event("⚙", CYAN, "starting OS alerter…")
            alerter_proc = subprocess.Popen([venv_python, alerter_script])
        except Exception as e:
            log_event("✗", RED, "OS notif alerter failed to start", str(e))

def stop_alerter():
    global alerter_proc
    if alerter_proc:
        alerter_proc.terminate()
        try:
            alerter_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            alerter_proc.kill()

atexit.register(stop_alerter)

# ── Global Initialization (Runs even under Gunicorn) ────────────────────────
def initialize_system():
    global tunnel_url
    
    # 1. Start Alerter
    start_alerter()

    # 2. Check for Public Mode / Cloudflare Tunnel
    mode = os.getenv("MODE", "lan").lower()
    port = int(os.getenv("PORT", 6769))
    
    if mode == "public":
        tunnel_url = start_cloudflare_tunnel(port)
        if tunnel_url:
            log_event("✓", GREEN, "tunnel online", tunnel_url)
            # EXPLICIT LOG FOR RE-RUN TOOLS:
            print(f"\n  {BOLD}{'─' * 40}{RESET}")
            print(f"  {BOLD}  TUNNEL URL: {tunnel_url}{RESET}")
            print(f"  {BOLD}{'─' * 40}{RESET}\n")
        else:
            log_event("⚠", YELLOW, "tunnel failed", "falling back to LAN")

# Only run initialization ONCE at module import time
if not os.environ.get("GUGA_INITIALIZED"):
    os.environ["GUGA_INITIALIZED"] = "true"
    initialize_system()

if __name__ == "__main__":
    os_notif_enabled = os.getenv("ENABLE_OS_NOTIFICATIONS", "False").lower() == "true"
    mode = os.getenv("MODE", "lan").lower()
    port = int(os.getenv("PORT", 6769))

    # ── Startup banner ────────────────────────────────────────────────────────
    width = 40
    print()
    print(f"  {BOLD}{'─' * width}{RESET}")
    print(f"  {BOLD}  GuGa Nexus{RESET}  {DIM}backend server{RESET}")
    print(f"  {BOLD}{'─' * width}{RESET}")
    print()
    
    final_url = tunnel_url if tunnel_url else f"http://{get_local_ip()}:{port}"
    print(f"  {DIM}address{RESET}   {BOLD}{final_url}{RESET}")
    print(f"  {DIM}mode{RESET}      {BOLD}{mode.upper()}{RESET}")
    os_status = f"{GREEN}enabled{RESET}" if os_notif_enabled else f"{DIM}disabled{RESET}"
    print(f"  {DIM}os notif{RESET}  {os_status}")
    print()
    print(f"  {DIM}routes{RESET}")
    print(f"    {DIM}GET{RESET}   /ping               health check")
    print(f"    {DIM}GET{RESET}   /clients            list connected devices")
    print(f"    {DIM}POST{RESET}  /send               broadcast to all  {DIM}(localhost only){RESET}")
    print(f"    {DIM}POST{RESET}  /send/<session_id>  message one device")
    print()
    print(f"  {BOLD}{'─' * width}{RESET}")
    print()

    # ── QR code ───────────────────────────────────────────────────────────────
    generate_qr(final_url, inverted=QR_INVERTED, show_gui=QR_SHOW_GUI)

    print(f"  {DIM}manual address →{RESET}  {BOLD}{final_url}{RESET}")
    print(f"  {DIM}press Ctrl+C to stop{RESET}")
    print()

    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)