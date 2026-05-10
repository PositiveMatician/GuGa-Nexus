"""
GuGa Nexus — OS Notification Alerter

This module monitors D-Bus for system notifications and forwards
them to the local GuGa server for delivery to Android devices.
"""

import asyncio
import asyncio.subprocess
import re
import aiohttp
import os
import logging
import logging.handlers
import platform
import sys
from dotenv import load_dotenv

CONFIG_DIR = os.path.expanduser("~/.guga")
env_path = os.path.join(CONFIG_DIR, '.env')
load_dotenv(dotenv_path=env_path)

# Enforce Linux-only restriction
if platform.system() != "Linux":
    # This is a known limitation, not an error. Exit gracefully.
    print(f"ℹ️  OS Notification monitoring is currently Linux-exclusive (requires D-Bus).")
    print(f"   Skipping alerter startup on {platform.system()}.")
    sys.exit(0)

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
SERVER_URL = os.getenv("ALERTER_SERVER_URL", "http://localhost:6769/send")
LOG_FILE = os.path.join(CONFIG_DIR, "alerter.log")

# Rotating file logger (1 MB per file, 2 backups)
_handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger = logging.getLogger("alerter")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)

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
    
    payload_msg = f"{clean_title}: {clean_body}"
    if not clean_title and not clean_body:
        return

    log_entry = f"Forwarding: {payload_msg}"
    print(log_entry)
    logger.info(log_entry)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SERVER_URL, json={"message": payload_msg , "title":app_name}) as resp:
                status_msg = f"Server Response: {resp.status}"
                print(status_msg)
                logger.info(status_msg)
    except Exception as e:
        err_msg = f"Error forwarding: {e}"
        print(err_msg)
        logger.info(err_msg)

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

    if not proc.stdout:
        print("Failed to capture dbus-monitor stdout.")
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
                logger.info(f"\n[Intercepted] App: {app_name}\nTitle: {summary}\nBody: {body}")
                asyncio.create_task(forward_to_server(app_name, summary, body))
                state = "IDLE"
            elif "array [" in line:
                # Body was empty, moving to actions
                print(f"\n[Intercepted] App: {app_name} (No body)")
                logger.info(f"\n[Intercepted] App: {app_name}\nTitle: {summary}\nBody: (empty)")
                asyncio.create_task(forward_to_server(app_name, summary, ""))
                state = "IDLE"

if __name__ == "__main__":
    try:
        asyncio.run(monitor_notifications())
    except KeyboardInterrupt:
        print("\nStopping OS Notification Alerter...")
