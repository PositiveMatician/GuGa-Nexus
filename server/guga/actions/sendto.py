import json
import urllib.request
import urllib.error
import asyncio
from ..db_utils import Database

async def sendto_run_command(text: str, sender: str):
    """Handles the 'sendto' command: sendto <target> <message>"""
    command_parts = text.split()
    
    if len(command_parts) < 3:
        return {
            "title": "SendTo Error",
            "message": "Usage: sendto <device_id/tag/name> <message>"
        }
        
    target_input = command_parts[1]
    message = " ".join(command_parts[2:])

    # 1. Resolve names/tags using the database
    # We run this in a thread if it's blocking, but SQLite is usually fast.
    # For now, let's keep it simple.
    db = Database()
    trusted = db.get_trusted_devices()
    
    sender_info = trusted.get(sender, {})
    sender_display = sender_info.get("tag") or sender_info.get("name") or sender
    
    target_device_id = target_input
    target_display = target_input
    
    target_lower = target_input.lower()
    for did, info in trusted.items():
        if did.lower() == target_lower or \
           (info.get("name") or "").lower() == target_lower or \
           (info.get("tag") or "").lower() == target_lower:
            target_device_id = did
            target_display = info.get("tag") or info.get("name") or did
            break

    # 2. Make the HTTP request to the local server
    url = f"http://localhost:6769/send/{target_device_id}"
    payload = {
        "message": message,
        "title": f"From {sender_display}"
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        # CRITICAL: Use asyncio.to_thread to avoid blocking the event loop.
        # This prevents the deadlock where the worker blocks the server from handling the request.
        def do_request():
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status

        status = await asyncio.to_thread(do_request)
        
        if status == 200:
            return {
                "title": "SendTo Mode",
                "message": f"✅ Message sent to '{target_display}'"
            }
        else:
            return {
                "title": "SendTo Error",
                "message": f"❌ Server returned status {status}"
            }
    except urllib.error.URLError as e:
        return {
            "title": "SendTo Error",
            "message": f"❌ Could not reach server: {getattr(e, 'reason', str(e))}"
        }
    except Exception as e:
        return {
            "title": "SendTo Error",
            "message": f"❌ Unexpected error: {str(e)}"
        }