"""
GuGa Nexus — Core ASGI Backend
Version: 1.5.1

This module implements the GuGa server using Quart (ASGI) and SocketIO.
It handles device pairing, encrypted command routing, and non-blocking
interactive PTY sessions.
"""


import asyncio

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
from typing import Set, List, Dict, Optional, Any
import collections
import uuid

from .db_utils import Database
from .lock_utils import FileLock

db = Database()

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get("GUGA_CONFIG_DIR", os.path.expanduser("~/.guga"))
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
from quart import Quart, jsonify, render_template, request, send_file
import socketio

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
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
)
app = Quart(__name__)
app_asgi = socketio.ASGIApp(sio, app)

# ── MCP & JWT Configuration ──────────────────────────────────────────────────
MCP_JWT_SECRET = os.getenv("MCP_JWT_SECRET")
if not MCP_JWT_SECRET:
    MCP_JWT_SECRET = secrets.token_hex(32)
    # Persist it to .env
    try:
        with open(env_path, "a") as f:
            f.write(f"\nMCP_JWT_SECRET={MCP_JWT_SECRET}\n")
        log_event("⚙", YELLOW, "generated new MCP_JWT_SECRET")
    except Exception:
        pass

import jwt
from .mcp_server import create_mcp_app
from .actions import master
from mcp.server.sse import SseServerTransport

mcp_handler = create_mcp_app(f"http://localhost:{PORT}")
sse_transport = SseServerTransport("/mcp/messages")
 
main_loop = None

connected_clients: dict[str, str] = {}  # session_id -> device_id (remains in-memory)

# The following were moved to SQLite:
# pending_pairings, blocked_devices, message_caches (partially)

# For each device_id, stores a deque of (message_id, message_dict)
message_caches: Dict[str, collections.deque] = {} 

# Maps request_id (device_id + "_" + message_id) to asyncio Event
pending_requests: Dict[str, asyncio.Event] = {}

# Tracks the order of active 'ask' requests for each device
request_stacks: Dict[str, List[str]] = {}

command_queue = asyncio.Queue()

TRUSTED_DEVICES_FILE = os.environ.get("GUGA_TRUSTED_DEVICES_FILE", os.path.join(CONFIG_DIR, "trusted_devices.json"))

def migrate_json_to_db():
    """Migrates existing JSON data to SQLite on first run."""
    if os.path.exists(TRUSTED_DEVICES_FILE):
        log_event("⚙", YELLOW, "migrating trusted_devices.json to db...")
        try:
            with open(TRUSTED_DEVICES_FILE, "r") as f:
                devices = json.load(f)
                for did, info in devices.items():
                    if isinstance(info, str): # Legacy migration
                        db.save_trusted_device(did, info, "app", time.time() + 30*24*3600, "Unknown Device")
                    else:
                        db.save_trusted_device(
                            did, 
                            info.get("token"), 
                            info.get("type", "app"), 
                            info.get("expires_at", 0), 
                            info.get("name", "Unknown Device"),
                            info.get("tag")
                        )
            os.rename(TRUSTED_DEVICES_FILE, TRUSTED_DEVICES_FILE + ".bak")
            log_event("✓", GREEN, "migration complete")
        except Exception as e:
            log_event("✗", RED, "migration failed", str(e))

migrate_json_to_db()

def clean_expired_pairings():
    """Remove pending entries older than 5 minutes."""
    now = time.time()
    pending = db.get_pending_pairings()
    for entry in pending:
        if now - entry["requested_at"] > 300:
            db.delete_pending_pairing(entry["id"])


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
    """Load trusted devices from SQLite."""
    return db.get_trusted_devices()


def save_trusted_device(device_id: str, token: str, client_type: str, expires_at: float, name: str = "Unknown Device") -> None:
    """Persist a paired device's token, type, and expiry to SQLite."""
    db.save_trusted_device(device_id, token, client_type, expires_at, name)


def is_device_trusted(device_id: str) -> bool:
    trusted = db.get_trusted_devices()
    entry = trusted.get(device_id)
    if not entry:
        return False

    if time.time() >= entry.get("expires_at", 0):
        log_event("⚠", YELLOW, "device expired", device_id)
        db.delete_trusted_device(device_id)
        return False
    return True


# region
 

#------------------------------------------------------------
# region HTML Dashboard
# ------------------------------------------------------------
# HTML interface separated into templates/index.html


# endregion

# ------------------------------------------------------------
# region HTTP Routes
# ------------------------------------------------------------
@app.route("/")
async def web_interface():
    return await render_template("index.html")


@app.route("/ping")
async def ping():
    return jsonify({"status": "online", "clients": len(connected_clients)}), 200


@app.route("/llms.txt")
async def llms_txt():
    """Serve the llms.txt file for AI crawlers/reference."""
    path = os.path.join(HERE, "FOR_AI_REFERENCE", "llms.txt")
    if os.path.exists(path):
        return await send_file(path)
    return "Not Found", 404


@app.route("/tools.json")
async def tools_json():
    """Serve OpenAI-compatible tool definitions for agent frameworks."""
    path = os.path.join(HERE, "FOR_AI_REFERENCE", "tools.json")
    if os.path.exists(path):
        return await send_file(path, mimetype="application/json")
    return jsonify({"error": "Not Found"}), 404


@app.route("/send/<target>", methods=["POST"])
async def private_send(target: str):
    """Route to send a message to a specific target (SID, Device ID, Name, or Tag)."""
    if request.remote_addr != "127.0.0.1":
        return "Unauthorized", 401
    
    data = await request.get_json()
    if not data or "message" not in data:
        return "Invalid request", 400
        
    success = await send_private_message(target, data["message"], data.get("title"), msg_id=data.get("unique_message_id"))
    return "OK" if success else ("Not Found", 404)


@app.route("/clients")
async def list_clients():
    """List all connected clients with detailed info."""
    trusted = load_trusted_devices()
    data = []
    for sid, device_id in connected_clients.items():
        device_info = trusted.get(device_id, {})
        data.append({
            "session_id": sid,
            "device_id": device_id,
            "name": device_info.get("name", "Unknown"),
            "type": device_info.get("type", "app"),
            "tag": device_info.get("tag")
        })
    return json.dumps(data)


@app.route("/send", methods=["POST"])
async def send_to_all():
    """Broadcast a message to ALL connected clients (localhost only)."""
    # Restrict to localhost requests
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
    data = await request.get_json() or {}
    message = data.get("message", "").strip()
    title = data.get("title", "").strip()
    msg_id = data.get("unique_message_id")
    if not message:
        return jsonify({"error": "No message provided"}), 400
    await notify_all_clients(message, title, msg_id=msg_id)
    return jsonify({"ok": True, "sent_to": len(connected_clients)}), 200


# ------------------------------------------------------------
# region MCP & Security
# ------------------------------------------------------------

def mcp_token_required(f):
    """Decorator to enforce JWT token for MCP endpoints."""
    from functools import wraps
    @wraps(f)
    async def decorated(*args, **kwargs):
        token = request.args.get("token")
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
        if not token:
            return jsonify({"error": "Unauthorized: No token provided"}), 401
            
        try:
            jwt.decode(token, MCP_JWT_SECRET, algorithms=["HS256"])
        except Exception as e:
            return jsonify({"error": f"Unauthorized: {str(e)}"}), 401
            
        return await f(*args, **kwargs)
    return decorated


@app.route("/mcp/token", methods=["GET"])
async def get_mcp_token():
    """Generate an MCP access token (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
        
    payload = {
        "iss": "guga-nexus",
        "iat": time.time(),
        "exp": time.time() + (365 * 24 * 3600) # 1 year
    }
    token = jwt.encode(payload, MCP_JWT_SECRET, algorithm="HS256")
    return jsonify({"token": token}), 200


@app.route("/mcp/sse", methods=["GET"])
@mcp_token_required
async def handle_mcp_sse():
    """Establishes the MCP SSE stream."""
    async def sse_handler(read_stream, write_stream):
        await mcp_handler.app.run(
            read_stream,
            write_stream,
            mcp_handler.app.create_initialization_options()
        )

    # Note: SseServerTransport.connect_sse returns an async context manager
    # that takes (scope, receive, send)
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await sse_handler(read_stream, write_stream)
        
    return "", 200


@app.route("/mcp/messages", methods=["POST"])
@mcp_token_required
async def handle_mcp_messages():
    """Receives JSON-RPC messages from MCP clients."""
    await sse_transport.handle_post_message(
        request.scope, request.receive, request._send
    )
    return "", 200

# endregion


    return None
 
 
def resolve_session_id(target: str) -> Optional[str]:
    """Resolves a target string (SID, Device ID, Name, or Tag) to a Session ID."""
    sids = get_sids_by_device(target)
    return sids[0] if sids else None


def get_sids_by_device(target: str) -> List[str]:
    """Returns all session IDs associated with a device ID, name, or tag."""
    if target == "all":
        return list(connected_clients.keys())
        
    # If target is already a valid Session ID
    if target in connected_clients:
        return [target]
        
    target_lower = target.lower()
    trusted = load_trusted_devices()
    sids = []
    
    for sid, dev_id in connected_clients.items():
        # Match by exact device ID
        if dev_id.lower() == target_lower:
            sids.append(sid)
            continue
            
        # Match by name or tag
        info = trusted.get(dev_id, {})
        if (info.get("name") or "").lower() == target_lower or \
           (info.get("tag") or "").lower() == target_lower:
            sids.append(sid)
            
    return sids


@app.route("/api/command", methods=["POST"])
async def handle_command_api():
    """Encrypted HTTP fallback for Android clients."""
    data = await request.get_json() or {}
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

    request_id = phrase_obj.get("request_id")
    message_id = phrase_obj.get("message_id")
    
    if not command:
        return jsonify({"error": "No command"}), 400
    log_event("→", CYAN, "command (HTTP)", f"{device_id} (req: {request_id}): {command!r}")
    response_msg = await master.run_command(command, client=device_id, request_id=request_id)
    for sid in get_sids_by_device(device_id):
        await send_private_message(sid, response_msg["message"], response_msg["title"])
    return jsonify({"ok": True}), 200


@app.route("/api/ask", methods=["POST"])
async def handle_ask():
    """Sends a prompt to a device and blocks until a reply is received."""
    data = await request.get_json() or {}
    message = data.get("message", "").strip()
    device_id = data.get("device_id", "").strip()
    title = data.get("title", "Question")
    timeout = data.get("timeout") # Can be None for infinite

    if not message:
        return jsonify({"error": "message required"}), 400
    if not device_id:
        return jsonify({"error": "device_id is compulsory for --ask-user"}), 400

    # Determine target SIDs and actual device_id
    target_sids = get_sids_by_device(device_id)
    if not target_sids:
        return jsonify({"error": f"Device {device_id} is not connected"}), 404
    
    # Use the real device_id for internal tracking
    device_id = connected_clients[target_sids[0]]

    # Create an event to wait for
    evt = asyncio.Event()
    
    # Generate unique IDs
    msg_id = uuid.uuid4().hex[:8]
    request_id = f"{device_id}_{msg_id}"
    
    # Track in DB and stack
    db.add_pending_ask(request_id, device_id, message, title)
    
    if device_id not in request_stacks:
        request_stacks[device_id] = []
    request_stacks[device_id].append(request_id)
    pending_requests[request_id] = evt

    log_event("?", YELLOW, "ask user", f"{device_id}: {message} (req: {request_id})")
    
    # Send the ask via SocketIO
    payload = {
        "message": message,
        "title": title,
        "is_ask": True,
        "unique_message_id": msg_id,
        "request_id": request_id
    }
    
    # Cache the message
    cache_message(device_id, payload)
    
    for sid in target_sids:
        await sio.emit("guga_ask", payload, to=sid)
 
    try:
        # Wait for the reply
        if timeout:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
        else:
            # Infinite wait
            await evt.wait()
        
        reply = getattr(evt, "reply", None)
        log_event("✓", GREEN, "ask resolved", f"{device_id} (req: {request_id}): {reply!r}")
        db.set_ask_reply(request_id, reply)
        return jsonify({"reply": reply}), 200
    except (asyncio.TimeoutError, TimeoutError):
        return jsonify({"error": "Timed out waiting for user reply"}), 408
    finally:
        pending_requests.pop(request_id, None)
        if device_id in request_stacks and request_id in request_stacks[device_id]:
            request_stacks[device_id].remove(request_id)

@app.route("/api/hello", methods=["POST"])
async def handle_hello():
    data = await request.get_json() or {}
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
    blocked = db.get_blocked_devices()
    if device_id in blocked:
        if time.time() < blocked[device_id]:
            return jsonify({"error": "too many failed attempts"}), 429
        else:
            db.unblock_device(device_id)

    clean_expired_pairings()

    # Store pending pairing
    db.add_pending_pairing(device_id, pin, device_name)

    log_event("?", YELLOW, "pairing request", f"{device_name} ({device_id[:8]}...) - PIN: {pin}")
    return jsonify({"status": "pin_required"}), 200


@app.route("/api/verify_pin", methods=["POST"])
async def handle_verify_pin():
    """Wait for authorization. Returns token on success."""
    data = await request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    pin = data.get("pin", "").strip()
    client_type = data.get("client_type", "app").strip()

    entry = db.get_pending_pairing(device_id)
    if not entry:
        return jsonify({"error": "No pending pairing for this device"}), 404

    # The client must provide the same PIN it sent in /api/hello
    if entry["pin"] != pin:
        attempts = entry["attempts"] + 1
        if attempts >= 5:
            db.delete_pending_pairing(device_id)
            db.block_device(device_id, time.time() + 600)  # 10 min
            return jsonify({"error": "too many attempts"}), 401
        db.update_pending_pairing(device_id, attempts=attempts)
        return jsonify({"error": "Invalid PIN"}), 401

    if not entry["approved"]:
        return jsonify({"status": "waiting_for_approval"}), 202

    # Approved! Determine TTL based on client type
    ttl_seconds = (30 * 24 * 3600) if client_type == "app" else 3600
    expires_at = time.time() + ttl_seconds

    token = secrets.token_hex(32)
    save_trusted_device(device_id, token, client_type, expires_at, name=entry["name"])
    db.delete_pending_pairing(device_id)

    log_event("✓", GREEN, "device paired", f"{device_id}  type={client_type}")
    return jsonify({"status": "paired", "token": token}), 200


@app.route("/api/pending", methods=["GET"])
async def get_pending():
    """List pending pairing requests (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
    clean_expired_pairings()
    pending = db.get_pending_pairings()
    result = [
        {
            "device_id": entry["id"],
            "device_name": entry["name"],
            "pin": entry["pin"],
            "requested_at": entry["requested_at"],
            "attempts": entry["attempts"],
            "status": entry["status"],
        }
        for entry in pending
    ]
    # Sort newest first
    result.sort(key=lambda x: x["requested_at"], reverse=True)
    return jsonify({"pending": result[:5]}), 200


@app.route("/api/approve", methods=["POST"])
async def approve_device():
    """Approve or reject a specific device (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
    data = await request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    action = data.get("action", "").strip()  # "approve", "reject", or "review"

    if action == "review":
        entry = db.get_pending_pairing(device_id)
        if not entry:
            return jsonify({"error": "No pending pairing"}), 404
        db.update_pending_pairing(device_id, status="UNDER_REVIEW")
        return jsonify({"status": "under_review"}), 200

    if action == "approve":
        entry = db.get_pending_pairing(device_id)
        if not entry:
            return jsonify({"error": "No pending pairing for this device"}), 404
        db.update_pending_pairing(device_id, approved=1, status="APPROVED")
        log_event("✓", GREEN, "pairing approved", f"{entry['name']} ({device_id[:8]}...)")
        return jsonify({"status": "approved"}), 200

    elif action == "reject":
        db.delete_pending_pairing(device_id)
        db.block_device(device_id, time.time() + 600)
        log_event("✗", RED, "pairing rejected", device_id)
        return jsonify({"status": "rejected"}), 200

    return jsonify({"error": "action must be approve, reject, or review"}), 400


@app.route("/api/devices", methods=["GET"])
async def list_active_devices():
    """List connected devices with their names and tags (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
        
    trusted = load_trusted_devices()
    
    # We want to list unique devices that are currently connected
    connected_dids = set(connected_clients.values())
    
    result = []
    for did in connected_dids:
        info = trusted.get(did, {})
        result.append({
            "device_id": did,
            "device_name": info.get("name", "Unknown Device"),
            "tag": info.get("tag"),
            "type": info.get("type")
        })
        
    return jsonify({"devices": result}), 200


@app.route("/api/rename", methods=["POST"])
async def rename_device():
    """Assign a tag to a device (localhost only)."""
    if request.remote_addr not in ["127.0.0.1", "::1"]:
        return jsonify({"error": "Forbidden"}), 403
    data = await request.get_json() or {}
    device_id = data.get("device_id", "").strip()
    tag = data.get("tag", "").strip()
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    trusted = db.get_trusted_devices()
    if device_id not in trusted:
        return jsonify({"error": "Device not found"}), 404
        
    # Check if tag is already used by another device
    if tag:
        for did, info in trusted.items():
            if info.get("tag") == tag and did != device_id:
                return jsonify({"error": f"Tag '{tag}' is already used by another device"}), 400

    entry = trusted[device_id]
    db.save_trusted_device(
        device_id, 
        entry["token"], 
        entry["type"], 
        entry["expires_at"], 
        entry["name"], 
        tag
    )
        
    log_event("✎", YELLOW, "device tagged", f"{device_id} -> {tag or 'None'}")
    return jsonify({"status": "ok"}), 200

# endregion

# ------------------------------------------------------------
# Socket.IO Events
# ------------------------------------------------------------
@sio.on("connect")
async def handle_connect(sid, environ):
    from urllib.parse import parse_qs
    query = parse_qs(environ.get('QUERY_STRING', ''))
    device_id = query.get('device_id', [None])[0]
    token = query.get('token', [None])[0]
    
    # In test mode, we allow mock clients to connect even if not trusted
    test_mode = os.getenv("GUGA_TEST_MODE", "false").lower() == "true"
    
    if not device_id or not token:
        log_event("✗", RED, "connection rejected", "missing credentials")
        return False
        
    if not test_mode and not is_device_trusted(device_id):
        log_event("✗", RED, "connection rejected", f"untrusted device_id={device_id}")
        return False
        
    if not test_mode:
        trusted = load_trusted_devices()
        entry = trusted.get(device_id, {})
        if entry.get('token') != token:
            log_event("✗", RED, "token mismatch", f"device_id={device_id}")
            return False
            
    connected_clients[sid] = device_id
    log_event("↑", GREEN, "connected", f"{device_id} (SID: {sid}) ({len(connected_clients)} online)")
    await send_private_message(sid, "Connection established. GuGa online.")


@sio.on("disconnect")
async def handle_disconnect(sid):
    connected_clients.pop(sid, None)
    log_event("↓", DIM, "disconnected", f"({len(connected_clients)} online)")


@sio.on("command")
async def handle_command(sid, data):
    """Accepts encrypted command payload from trusted Android device."""
    device_id = data.get("device_id", "").strip()
    test_mode = os.getenv("GUGA_TEST_MODE", "false").lower() == "true"
    trusted = load_trusted_devices()

    if not test_mode and device_id not in trusted:
        log_event("✗", RED, "untrusted command", device_id)
        await sio.emit("error", {"message": "Untrusted device"}, to=sid)
        return

    try:
        log_debug(f"incoming WS payload from {device_id}")
        device_info = trusted.get(device_id, {})
        token = device_info.get("token")
        client_type = device_info.get("type", "browser" if test_mode else "app")
        
        if "iv" in data and "ciphertext" in data and token:
            phrase_json = CryptoHelper.decrypt(data, token)
            phrase_obj = json.loads(phrase_json)
            command = phrase_obj.get("phrase", "").strip()
        elif client_type == "browser" or test_mode:
            log_debug(f"plaintext command for device: {device_id}")
            command = data.get("phrase", "").strip()
        else:
            raise ValueError("Encrypted payload required for app clients")
            
        # Extract request_id if present (can be in encrypted payload or outer data)
        request_id = data.get("request_id")
        if "phrase_obj" in locals() and not request_id:
            request_id = phrase_obj.get("request_id")
            
    except Exception as e:
        log_event("✗", RED, "processing error", str(e))
        await sio.emit("error", {"message": f"Processing error: {str(e)}"}, to=sid)
        return

    log_event("→", CYAN, "command queued", f"{device_id} (req: {request_id}): {command!r}")
    
    await command_queue.put({
        "device_id": device_id,
        "sid": sid,
        "command": command,
        "request_id": request_id,
        "has_request_id_field": "request_id" in data or ("phrase_obj" in locals() and "request_id" in phrase_obj)
    })


@sio.on("reply")
async def handle_reply(sid, data):
    """Receives a reply from a client for a pending 'ask'."""
    device_id = connected_clients.get(sid)
    if not device_id:
        return

    reply = data.get("message", "").strip()
    request_id = data.get("request_id")
    
    log_event("←", GREEN, "reply", f"{device_id} (req: {request_id if request_id else 'latest'}): {reply!r}")

    # 1. Explicit request_id targeted
    if request_id:
        if request_id in pending_requests:
            log_event("←", GREEN, "reply matched", f"{device_id} (req: {request_id})")
            evt = pending_requests[request_id]
            evt.reply = reply
            evt.set()
        else:
            log_event("⚙", CYAN, "orphan reply -> master", f"{device_id}: {reply!r}")
            response_msg = await master.run_command(reply, client=device_id, request_id=request_id)
            await send_private_message(sid, response_msg["message"], response_msg["title"])
    
    # 2. Fallback to stack-based resolution (latest request)
    elif device_id in request_stacks and request_stacks[device_id]:
        target_id = request_stacks[device_id][-1]
        if target_id in pending_requests:
            evt = pending_requests[target_id]
            evt.reply = reply
            evt.set()


# ------------------------------------------------------------
# Core Logic
# ------------------------------------------------------------
async def command_worker():
    """Background worker to process commands sequentially from the queue."""
    log_event("⚙", CYAN, "command worker started")
    while True:
        log_event("⚙", CYAN, "worker waiting for item")
        item = await command_queue.get()
        log_event("⚙", CYAN, "worker got item")
        try:
            device_id = item["device_id"]
            sid = item["sid"]
            command = item["command"]
            request_id = item.get("request_id")
            has_explicit_field = item.get("has_request_id_field", False)
            
            # 1. Check if this command should be intercepted as a reply to a pending ask
            # Bypass interception ONLY if client explicitly sent request_id=None
            if has_explicit_field and request_id is None:
                log_event("⚙", CYAN, "explicit command bypass", f"{device_id}: {command!r}")
                # Fall through to normal command processing
            elif device_id in request_stacks and request_stacks[device_id]:
                # Resolve target request_id: specific one provided or the latest in stack
                target_id = request_id if request_id else request_stacks[device_id][-1]
                
                if target_id in pending_requests:
                    log_event("←", GREEN, "intercepted as reply", f"{device_id} (req: {target_id}): {command!r}")
                    evt = pending_requests[target_id]
                    evt.reply = command
                    evt.set()
                    continue
                else:
                    log_event("⚠", YELLOW, "orphan intercept", f"Request {target_id} not found")

            # Process as normal command
            log_event("⚙", CYAN, "processing command", f"{device_id}: {command!r}")
            response_msg = await master.run_command(command, client=device_id, request_id=request_id)
            await send_private_message(sid, response_msg["message"], response_msg["title"])
        except Exception as e:
            log_event("✗", RED, "worker error", str(e))
        finally:
            await asyncio.sleep(0) # Yield

 
def cache_message(device_id: str, message_data: dict, msg_id: str = None) -> str:
    """Assigns a unique ID, caches the message, and returns the message ID."""
    if not msg_id:
        msg_id = uuid.uuid4().hex[:8]
    message_data["unique_message_id"] = msg_id
    
    if device_id not in message_caches:
        message_caches[device_id] = collections.deque(maxlen=50)
    message_caches[device_id].append((msg_id, message_data))
    return msg_id


async def notify_all_clients(message: str, title: str = None, msg_id: str = None) -> None:
    """Emit guga_response to all connected clients."""
    trusted = load_trusted_devices()
    payload_data = {"message": message}
    if title:
        payload_data["title"] = title
    
    for sid, device_id in list(connected_clients.items()):
        try:
            device_info = trusted.get(device_id, {})
            client_type = device_info.get("type", "app")
            token = device_info.get("token")

            # Clone data to avoid modifying the original during caching for different devices
            local_payload = payload_data.copy()
            final_msg_id = cache_message(device_id, local_payload, msg_id=msg_id)
            local_payload_json = json.dumps(local_payload)

            if client_type == "browser" or device_id.startswith("browser-") or not token:
                await sio.emit("guga_response", local_payload, to=sid)
            else:
                encrypted = CryptoHelper.encrypt(local_payload_json, token)
                await sio.emit("guga_response", encrypted, to=sid)
        except Exception as e:
            log_event("✗", RED, "broadcast failed", f"{sid}: {e}")


async def send_private_message(target: Any, message: str, title: str = None, msg_id: str = None) -> bool:
    """Sends a message to a specific client by resolving its target ID/Name/Tag."""
    session_id = resolve_session_id(target)
    
    if not session_id or session_id not in connected_clients:
        return False
        
    device_id = connected_clients[session_id]
    trusted = load_trusted_devices()
    device_info = trusted.get(device_id, {})
    client_type = device_info.get("type", "app")
    token = device_info.get("token")
    payload_data = {"message": message}
    if title:
        payload_data["title"] = title

    test_mode = os.getenv("GUGA_TEST_MODE", "false").lower() == "true"
    
    try:
        final_msg_id = cache_message(device_id, payload_data, msg_id=msg_id)
        payload_json = json.dumps(payload_data)

        if test_mode or client_type == "browser" or not token:
            await sio.emit("guga_response", payload_data, to=session_id)
        else:
            encrypted = CryptoHelper.encrypt(payload_json, token)
            await sio.emit("guga_response", encrypted, to=session_id)
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
    with FileLock("tunnel"):
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
def initialize_system(mode: Optional[str] = None, port: Optional[int] = None):
    global tunnel_url
    
    # 1. Start Alerter
    start_alerter()

    # 2. Check for Public Mode / Cloudflare Tunnel
    mode = mode or os.getenv("MODE", "lan").lower()
    port = port or int(os.getenv("PORT", 6769))
    
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

# Only run initialization ONCE at module import time if not explicitly called by run_server
if not os.environ.get("GUGA_INITIALIZED") and __name__ == "__main__":
    os.environ["GUGA_INITIALIZED"] = "true"
    initialize_system()

def run_server(mode: Optional[str] = None, port: Optional[int] = None):
    # Ensure system is initialized with the correct parameters
    if not os.environ.get("GUGA_INITIALIZED"):
        os.environ["GUGA_INITIALIZED"] = "true"
        initialize_system(mode=mode, port=port)
    
    os_notif_enabled = os.getenv("ENABLE_OS_NOTIFICATIONS", "False").lower() == "true"
    mode = mode or os.getenv("MODE", "lan").lower()
    port = port or int(os.getenv("PORT", 6769))

    # ── Startup banner ────────────────────────────────────────────────────────
    width = 40
    print()
    print(f"  {BOLD}{'─' * width}{RESET}")
    print(f"  {BOLD}  GuGa Nexus{RESET}  {DIM}backend server{RESET}")
    print(f"  {BOLD}{'─' * width}{RESET}")
    print()
    
    final_url = tunnel_url if tunnel_url else f"http://{get_local_ip()}:{port}"
    print(f"  {DIM}address{RESET}   {BOLD}{final_url}{RESET}\033[8m[GUGA_URL] {final_url}\033[0m")
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

    # Save current URL for standalone tools (like guga --qr) to find easily
    url_file = os.path.join(CONFIG_DIR, "current_url")
    try:
        with open(url_file, "w") as f:
            f.write(final_url)
        atexit.register(lambda: (os.remove(url_file) if os.path.exists(url_file) else None))
    except Exception:
        pass

    print(f"  {DIM}manual address →{RESET}  {BOLD}{final_url}{RESET}")
    print(f"  {DIM}press Ctrl+C to stop{RESET}")
    print()

    import uvicorn
    config = uvicorn.Config(app_asgi, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)

    async def main_async():
        global main_loop
        main_loop = asyncio.get_running_loop()
        log_event("⚙", CYAN, f"Main loop captured: {main_loop}")
        sio.start_background_task(command_worker)
        await server.serve()

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run_server()