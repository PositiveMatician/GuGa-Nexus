import json
import urllib.request
import urllib.error
import asyncio
import os
import sys
from ..db_utils import Database

PORT = int(os.getenv("PORT", 6769))

async def sendto_run_command(text: str, sender: str, request_id: str = None):
    """Handles the 'sendto' command: sendto <target> <message>"""
    command_parts = text.split()
    
    target_input = None
    message = text

    # 1. Handle Orphan Replies (via request_id)
    if request_id and not text.lower().startswith("sendto "):
        # Extract title from daemon.message_caches[sender]
        import sys
        daemon = sys.modules.get("guga.daemon") or sys.modules.get("server.guga.daemon")
        title = None
        if daemon and hasattr(daemon, "message_caches"):
            cache = daemon.message_caches.get(sender, [])
            for mid, data in cache:
                if mid == request_id:
                    title = data.get("title")
                    break
        
        if title:
            # If the title was "From Jason", we want just "Jason"
            if title.startswith("From "):
                target_input = title[5:].strip()
            else:
                target_input = title
            
            # Strip "reply " keyword from the message body if present
            if text.lower().startswith("reply "):
                message = text[6:].strip()
            else:
                message = text
        else:
            return {
                "title": "SendTo Error",
                "message": "❌ Context lost: Could not find the original message title."
            }
    
    # 2. Standard 'sendto' command parsing
    else:
        if len(command_parts) < 3:
            return {
                "title": "SendTo Error",
                "message": "Usage: sendto <device_id/tag/name> <message>"
            }
        target_input = command_parts[1]
        message = " ".join(command_parts[2:])

    # 3. Resolve names/tags using the database
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

    # 4. Make the HTTP request to the local server
    url = f"http://localhost:{PORT}/send/{target_device_id}"
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