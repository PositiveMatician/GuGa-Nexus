import pyautogui
import asyncio
import sys
import os

async def get_message_context(request_id: str) -> str:
    """
    Attempts to retrieve the message content associated with a request_id.
    Checks for a .log file in ~/.guga/logs/ first, then memory cache, then DB.
    """
    if not request_id:
        return ""

    # 1. Check for log file <id>.log (Primary source)
    log_dir = os.path.expanduser("~/.guga/logs")
    log_file = os.path.join(log_dir, f"{request_id}.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                return f.read().strip()
        except Exception:
            pass

    daemon = sys.modules.get("guga.daemon") or sys.modules.get("server.guga.daemon")
    if not daemon:
        return ""
        
    # 2. Check Memory Cache (for normal messages)
    if hasattr(daemon, "message_caches"):
        for client_id, cache in daemon.message_caches.items():
            for mid, data in cache:
                if mid == request_id:
                    return data.get("message", "")
                    
    # 3. Check Database (for 'ask' questions)
    if hasattr(daemon, "db"):
        ask = daemon.db.get_pending_ask(request_id)
        if ask:
            return ask.get("message", "")
            
    return ""

async def antigravity_run_command(text: str, request_id: str = None):
    """
    Automates the 'antigravity' sequence: 
    Ctrl+Shift+F -> Ctrl+Shift+L -> Type text + Context -> Enter.
    """
    try:
        context = await get_message_context(request_id)
        
        # Clean the command prefix "antigravity " if it exists at the start
        import re
        clean_text = re.sub(r'^antigravity\s*', '', text, flags=re.IGNORECASE).strip()

        # Prepare full payload
        full_payload = clean_text
        if context:
            full_payload += f"\n--- CONTEXT ---\n{context}\n--- END ---\n"

        # 0. Focus window/app (Windows + T -> type 'antigravity' -> Enter)
        await asyncio.to_thread(pyautogui.hotkey, 'win', 't')
        await asyncio.sleep(0.3)
        await asyncio.to_thread(pyautogui.write, 'antigravity', interval=0.01)
        await asyncio.to_thread(pyautogui.press, 'enter')
        await asyncio.sleep(0.5)

        # 1. Open search (Ctrl+Shift+F)
        await asyncio.to_thread(pyautogui.hotkey, 'ctrl', 'shift', 'f')
        await asyncio.sleep(0.3)
        
        # 2. Open new chat (Ctrl+Shift+L)
        await asyncio.to_thread(pyautogui.hotkey, 'ctrl', 'shift', 'l')
        await asyncio.sleep(0.5)
        
        # 3. Type the text and context
        # We split by newline and use Shift+Enter to prevent premature sending
        lines = full_payload.split('\n')
        for i, line in enumerate(lines):
            if line:
                await asyncio.to_thread(pyautogui.write, line, interval=0.001)
            if i < len(lines) - 1:
                # Add a small delay to ensure the app processes the newline
                await asyncio.sleep(0.05)
                await asyncio.to_thread(pyautogui.hotkey, 'shift', 'enter')
        
        # 4. Press Enter to finally send the complete payload
        await asyncio.to_thread(pyautogui.press, 'enter')

        return {
            "title": "Antigravity Mode",
            "message": f"🚀 Automation sequence completed for: '{clean_text[:50]}...'" + (f" (with context)" if context else "")
        }
    except Exception as e:
        return {
            "title": "Antigravity Error",
            "message": f"❌ Automation failed: {str(e)}"
        }