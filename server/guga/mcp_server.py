import asyncio
import os
import json
import jwt
import time
from typing import Optional, List
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
import requests

# We'll use this to talk to the local GuGa server if running in stdio mode
# or we'll define a way to inject the local logic if running in SSE mode.

class GugaMcpServer:
    def __init__(self, server_url: str = "http://localhost:6769"):
        self.server_url = server_url
        self.app = Server("guga-nexus")
        self._setup_tools()

    def _setup_tools(self):
        @self.app.list_tools()
        async def list_tools() -> List[types.Tool]:
            return [
                types.Tool(
                    name="send_notification",
                    description="Send a notification to paired GuGa devices (Android or Browser).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "The message body to send."},
                            "title": {"type": "string", "description": "Optional title for the notification.", "default": "GuGa"},
                            "device": {"type": "string", "description": "Optional device ID or tag (e.g. 'F'). If omitted, broadcasts to all."}
                        },
                        "required": ["message"]
                    }
                ),
                types.Tool(
                    name="ask_user",
                    description="Send a question to a GuGa device and wait for a reply from the user.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string", "description": "The question to ask the user."},
                            "device": {"type": "string", "description": "Target device ID or tag (compulsory for ask)."},
                            "timeout": {"type": "string", "description": "Timeout duration (e.g. '5m', '120s', 'never').", "default": "5m"}
                        },
                        "required": ["prompt", "device"]
                    }
                ),
                types.Tool(
                    name="list_devices",
                    description="List all connected and paired GuGa devices.",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                )
            ]

        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[types.TextContent]:
            if name == "send_notification":
                return await self._tool_send_notification(arguments)
            elif name == "ask_user":
                return await self._tool_ask_user(arguments)
            elif name == "list_devices":
                return await self._tool_list_devices()
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def _tool_send_notification(self, args: dict) -> List[types.TextContent]:
        message = args["message"]
        title = args.get("title", "GuGa")
        device = args.get("device")

        endpoint = f"/send/{device}" if device else "/send"
        url = f"{self.server_url}{endpoint}"
        
        try:
            # We use loop.run_in_executor for requests since it's blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, json={"message": message, "title": title}, timeout=5)
            )
            
            if response.status_code == 200:
                return [types.TextContent(type="text", text=f"✅ Notification sent.")]
            else:
                return [types.TextContent(type="text", text=f"❌ Failed to send: {response.text}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"❌ Error communicating with GuGa server: {str(e)}")]

    async def _tool_ask_user(self, args: dict) -> List[types.TextContent]:
        prompt = args["prompt"]
        device = args["device"]
        timeout_str = args.get("timeout", "5m")
        
        # Parse duration (simple version)
        timeout = 300
        if timeout_str.endswith("s"): timeout = int(timeout_str[:-1])
        elif timeout_str.endswith("m"): timeout = int(timeout_str[:-1]) * 60
        elif timeout_str == "never": timeout = None

        url = f"{self.server_url}/api/ask"
        
        try:
            loop = asyncio.get_event_loop()
            # Ask can block for a long time, so we set a high timeout on the request itself
            req_timeout = (timeout + 10) if timeout else None
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json={"message": prompt, "device_id": device, "timeout": timeout}, timeout=req_timeout)
            )
            
            if response.status_code == 200:
                reply = response.json().get("reply")
                return [types.TextContent(type="text", text=f"User replied: {reply}")]
            else:
                return [types.TextContent(type="text", text=f"❌ Ask failed: {response.text}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"❌ Error: {str(e)}")]

    async def _tool_list_devices(self) -> List[types.TextContent]:
        url = f"{self.server_url}/api/devices"
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(url, timeout=5)
            )
            if response.status_code == 200:
                devices = response.json().get("devices", [])
                if not devices:
                    return [types.TextContent(type="text", text="No devices connected.")]
                
                output = "Connected Devices:\n"
                for d in devices:
                    tag = f" [{d['tag']}]" if d.get('tag') else ""
                    output += f"- {d['device_name']}{tag} ({d['device_id']})\n"
                return [types.TextContent(type="text", text=output)]
            else:
                return [types.TextContent(type="text", text=f"❌ Failed to list devices: {response.text}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"❌ Error: {str(e)}")]

    async def run_stdio(self):
        """Run the server using stdio transport (for local tools)."""
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await self.app.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="guga-nexus",
                    server_version="1.5.0",
                    capabilities=self.app.get_capabilities()
                )
            )

# SSE Transport Integration for Quart
def create_mcp_app(guga_server_url: str):
    mcp_handler = GugaMcpServer(guga_server_url)
    return mcp_handler
