import unittest
import threading
import time
import os
import sys
import json
import socketio
import tempfile
import asyncio
from unittest.mock import patch, MagicMock

# 1. Setup temporary environment BEFORE importing guga modules
tmp_dir = tempfile.mkdtemp()
tmp_db = os.path.join(tmp_dir, "guga_test_mcp.db")
os.environ["GUGA_DB_PATH"] = tmp_db
os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["GUGA_TEST_MODE"] = "True"
os.environ["PORT"] = "6790"

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

from guga import daemon
from guga.daemon import app, socketio as server_socketio, connected_clients
from guga.db_utils import Database
from guga.mcp_server import GugaMcpServer

class TestMcpFunctionality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_utils import kill_port
        cls.server_port = 6790
        kill_port(cls.server_port)
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        cls.tmp_db = tmp_db
        
        # Pre-populate DB
        db = Database(cls.tmp_db)
        db.save_trusted_device("test-device", "test-token", "browser", time.time() + 3600, "MCP Test Device", "M")

        def run_server():
            daemon.run_server()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.sio = socketio.Client()
        self.received_asks = []
        self.received_responses = []
        
        @self.sio.on('guga_ask')
        def on_ask(data):
            self.received_asks.append(data)

        @self.sio.on('guga_response')
        def on_response(data):
            self.received_responses.append(data)

        self.sio.connect(f"{self.server_url}?device_id=test-device&token=test-token")
        time.sleep(0.5)
        
        # MCP Server instance
        self.mcp = GugaMcpServer(self.server_url)

    def tearDown(self):
        if self.sio.connected:
            self.sio.disconnect()
        time.sleep(0.2)

    def test_mcp_send_notification(self):
        """Verify sending a notification via MCP tool reaches the client."""
        async def run_test():
            # In mcp_server.py, call_tool is a decorated internal function.
            # We can find it via self.mcp.app._request_handlers
            handler = self.mcp.app.request_handlers.get("tools/call")
            if not handler:
                # Compatibility check for different mcp versions
                # Newer versions use @app.call_tool() which registers a handler
                # We'll try to trigger it manually via the registered function
                for h in self.mcp.app.request_handlers.values():
                    if hasattr(h, "__name__") and h.__name__ == "call_tool":
                        handler = h
                        break
            
            # Since we can't easily trigger the JSON-RPC internals, we call the 
            # private tool methods directly but wrapped in an event loop as they are async.
            result = await self.mcp._tool_send_notification({"message": "MCP Hello", "device": "M"})
            return result

        result = asyncio.run(run_test())
        self.assertIn("✅ Notification sent", result[0].text)
        
        # Wait for client to receive
        max_wait = 5
        while not self.received_responses and max_wait > 0:
            time.sleep(0.2)
            max_wait -= 0.2
            
        self.assertTrue(any("MCP Hello" in r.get("message", "") for r in self.received_responses))

    def test_mcp_list_devices(self):
        """Verify MCP tool lists connected devices."""
        async def run_test():
            result = await self.mcp._tool_list_devices()
            return result

        result = asyncio.run(run_test())
        text = result[0].text
        self.assertIn("MCP Test Device", text)
        self.assertIn("[M]", text)
        self.assertIn("test-device", text)

    def test_mcp_ask_user(self):
        """Verify interactive ask-reply loop via MCP tools."""
        tool_result = []
        
        def run_mcp_ask():
            async def do_ask():
                return await self.mcp._tool_ask_user({"prompt": "What color?", "device": "M"})
            
            res = asyncio.run(do_ask())
            tool_result.append(res)

        ask_thread = threading.Thread(target=run_mcp_ask)
        ask_thread.start()
        
        # Wait for client to get the ask
        max_wait = 5
        while not self.received_asks and max_wait > 0:
            time.sleep(0.2)
            max_wait -= 0.2
            
        self.assertEqual(len(self.received_asks), 1)
        self.assertIn("What color?", self.received_asks[0]["message"])
        req_id = self.received_asks[0]["request_id"]
        
        # Client replies
        self.sio.emit("reply", {"request_id": req_id, "message": "Blue"})
        
        ask_thread.join(timeout=5)
        
        self.assertEqual(len(tool_result), 1)
        self.assertIn("User replied: Blue", tool_result[0][0].text)

if __name__ == '__main__':
    unittest.main()
