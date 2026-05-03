import pyautogui
import asyncio

async def antigravity_run_command(text: str):
    """
    Automates the 'antigravity' sequence: 
    Ctrl+Shift+F -> Ctrl+Shift+L -> Type text -> Enter.
    """
    try:
        # Use asyncio.sleep instead of time.sleep to keep the event loop alive
        await asyncio.sleep(0.5)
        
        # 1. Open search (Ctrl+Shift+F)
        # We use to_thread for pyautogui as it might have blocking I/O
        await asyncio.to_thread(pyautogui.hotkey, 'ctrl', 'shift', 'f')
        await asyncio.sleep(0.3)
        
        # 2. Open new chat (Ctrl+Shift+L)
        await asyncio.to_thread(pyautogui.hotkey, 'ctrl', 'shift', 'l')
        await asyncio.sleep(0.5)
        
        # 3. Type the text
        await asyncio.to_thread(pyautogui.write, text, interval=0.01)
        
        # 4. Press Enter
        await asyncio.to_thread(pyautogui.press, 'enter')

        return {
            "title": "Antigravity Mode",
            "message": f"🚀 Automation sequence completed for: '{text}'"
        }
    except Exception as e:
        return {
            "title": "Antigravity Error",
            "message": f"❌ Automation failed: {str(e)}"
        }