import sys

async def status_run_command(text: str):
    daemon = sys.modules.get("guga.daemon") or sys.modules.get("server.guga.daemon")
    if not daemon:
        return {"title": "Status Error", "message": "Could not connect to daemon state."}
    
    clients_count = len(daemon.connected_clients) if hasattr(daemon, 'connected_clients') else "?"
    return {
        "title": "System Status",
        "message": f"Server is online. {clients_count} clients connected."
    }
