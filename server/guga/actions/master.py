import time
from . import antigravity, sendto

# Command Registry
# Format: "keyword": handler_function or response_dict
COMMANDS = {
    "ping": {
        "title": "System",
        "message": "pong 🏓"
    },
    "status": {
        "title": "System",
        "message": "All systems nominal. Server is listening for incoming signals."
    },
    "help": {
        "title": "Available Commands",
        "message": "Try: ping, status, antigravity, help, sendto"
    }
}

async def run_command(command: str, client: str):
    """
    Take the command from the remote client and return a response dictionary.
    This is the central dispatcher for all remote-initiated actions.
    Now asynchronous to support non-blocking I/O in actions.
    """
    if not command:
        return {
            "title": "System",
            "message": "Empty command received."
        }

    cmd_lower = command.lower().strip()

    # 1. Check specific keyword handlers
    if "antigravity" in cmd_lower:
        return await antigravity.antigravity_run_command(command)

    elif "sendto" in cmd_lower:
        return await sendto.sendto_run_command(command, sender=client)

    # 2. Check static command registry
    if cmd_lower in COMMANDS:
        res = COMMANDS[cmd_lower]
        if callable(res):
            return await res(command) if hasattr(res, '__code__') and res.__code__.co_flags & 0x80 else res(command)
        return res

    # 3. Dynamic commands or fallbacks
    if cmd_lower.startswith("echo "):
        return {
            "title": "Echo",
            "message": command[5:].strip()
        }

    # 4. Final fallback
    return {
        "title": "System",
        "message": f"Command '{command}' not recognized. Type 'help' for available commands."
    }