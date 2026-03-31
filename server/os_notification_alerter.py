import asyncio
import re
import aiohttp
import os

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
SERVER_URL = "http://localhost:6769/send"
LOG_FILE = "alerter.log"

# ------------------------------------------------------------
# Text Cleaning (Stripping Formatting)
# ------------------------------------------------------------
def clean_text(text: str) -> str:
    """
    Strips HTML-like tags and common markdown formatting from text.
    """
    if not text:
        return ""
    
    # 1. Strip HTML tags (e.g., <b>, <i>, <a href="...">)
    text = re.sub(r'<[^>]+>', '', text)
    
    # 2. Strip Markdown bold/italic/strike (e.g., **, *, __, _, ~~)
    text = re.sub(r'(\*\*|__|\*|_|~~)', '', text)
    
    # 3. Strip Markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # 4. Strip excessive newlines and whitespace
    text = re.sub(r'\n+', ' ', text)
    text = text.strip()
    
    return text

# ------------------------------------------------------------
# Forwarding Logic
# ------------------------------------------------------------
async def forward_to_server(app_name: str, title: str, body: str):
    """
    Sends the cleaned notification to the local server's /send route.
    """
    clean_title = clean_text(title)
    clean_body = clean_text(body)
    
    payload_msg = f"[{app_name}] {clean_title}: {clean_body}"
    if not clean_title and not clean_body:
        return

    log_entry = f"Forwarding: {payload_msg}\n"
    print(log_entry.strip())
    with open(LOG_FILE, "a") as f:
        f.write(log_entry)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SERVER_URL, json={"message": payload_msg}) as resp:
                status_msg = f"Server Response: {resp.status}\n"
                print(status_msg.strip())
                with open(LOG_FILE, "a") as f:
                    f.write(status_msg)
    except Exception as e:
        err_msg = f"Error forwarding: {e}\n"
        print(err_msg.strip())
        with open(LOG_FILE, "a") as f:
            f.write(err_msg)

# ------------------------------------------------------------
# D-Bus Monitor via Subprocess
# ------------------------------------------------------------
async def monitor_notifications():
    """
    Runs dbus-monitor and parses its output to detect notifications.
    """
    # Explicitly filter for method_call to avoid duplicates from signals
    cmd = ["dbus-monitor", "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
    except Exception as e:
        print(f"Failed to start dbus-monitor: {e}")
        return

    print("Monitoring D-Bus for notifications (method calls only)...")
    
    # State tracking
    state = "IDLE"
    app_name = ""
    summary = ""
    body = ""
    
    while True:
        line_bytes = await proc.stdout.readline()
        if not line_bytes:
            break
            
        line = line_bytes.decode(errors='replace').strip()
        
        # Detect start of method call specifically
        if "method call" in line and "interface=org.freedesktop.Notifications; member=Notify" in line:
            state = "APP_NAME"
            app_name = ""
            summary = ""
            body = ""
            continue
            
        if state == "APP_NAME":
            match = re.search(r'string\s+"(.*)"', line)
            if match:
                app_name = match.group(1)
                state = "REPLACES_ID"
        
        elif state == "REPLACES_ID":
            if "uint32" in line:
                state = "ICON"
                
        elif state == "ICON":
            match = re.search(r'string\s+"(.*)"', line)
            if match:
                state = "SUMMARY"
                
        elif state == "SUMMARY":
            match = re.search(r'string\s+"(.*)"', line)
            if match:
                summary = match.group(1)
                state = "BODY"
                
        elif state == "BODY":
            # Body can be a string or we might see 'array [' if body is empty
            match = re.search(r'string\s+"(.*)"', line)
            if match:
                body = match.group(1)
                # Done capturing this notification
                print(f"\n[Intercepted] App: {app_name}")
                with open(LOG_FILE, "a") as f:
                    f.write(f"\n[Intercepted] App: {app_name}\nTitle: {summary}\nBody: {body}\n")
                asyncio.create_task(forward_to_server(app_name, summary, body))
                state = "IDLE"
            elif "array [" in line:
                # Body was empty, moving to actions
                print(f"\n[Intercepted] App: {app_name} (No body)")
                with open(LOG_FILE, "a") as f:
                    f.write(f"\n[Intercepted] App: {app_name}\nTitle: {summary}\nBody: (empty)\n")
                asyncio.create_task(forward_to_server(app_name, summary, ""))
                state = "IDLE"

if __name__ == "__main__":
    try:
        asyncio.run(monitor_notifications())
    except KeyboardInterrupt:
        print("\nStopping OS Notification Alerter...")
