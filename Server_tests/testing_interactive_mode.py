import unittest
import threading
import time
import os
import sys
import json
import socketio
import eventlet
from unittest.mock import patch, MagicMock

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

from guga import daemon
from guga.daemon import app, socketio as server_socketio, connected_clients

class TestInteractiveMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_port = 6780
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        
        # Prevent real notifications
        os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
        
        def run_server():
            server_socketio.run(app, host="127.0.0.1", port=cls.server_port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.sio = socketio.Client()
        # Mock trusted device check to always pass for 'test-device'
        self.patcher = patch('guga.daemon.is_device_trusted', return_value=True)
        self.patcher.start()
        
        # Patch load_trusted_devices to return a valid token
        self.patcher2 = patch('guga.daemon.load_trusted_devices', return_value={'test-device': {'token': 'test-token'}})
        self.patcher2.start()

    def tearDown(self):
        if self.sio.connected:
            self.sio.disconnect()
        self.patcher.stop()
        self.patcher2.stop()

    def test_ask_user_flow(self):
        """Tests the full flow of --ask-user: CLI -> Server -> Client -> Server -> CLI"""
        
        received_ask = []
        
        @self.sio.on('guga_ask')
        def on_ask(data):
            received_ask.append(data)
            # Simulate user reply
            self.sio.emit('reply', {'message': 'User says YES'})

        # Connect the mock client
        self.sio.connect(f"{self.server_url}?device_id=test-device&token=test-token")
        time.sleep(1)

        # In a separate thread, act as the CLI calling the /api/ask endpoint
        replies = []
        def call_cli():
            from guga import cli
            # Capture stdout
            with patch('sys.stdout.write') as mock_write:
                cli.guga_ask_user("Should I?", self.server_port, "test-device")
                # Collect what was printed
                output = "".join(call.args[0] for call in mock_write.call_args_list)
                replies.append(output.strip())

        cli_thread = threading.Thread(target=call_cli)
        cli_thread.start()
        
        # Wait for the flow to complete
        cli_thread.join(timeout=5)
        
        self.assertEqual(len(received_ask), 1)
        self.assertEqual(received_ask[0]['message'], "Should I?")
        self.assertEqual(len(replies), 1)
        # Check that the core reply string is in the captured output
        self.assertIn("User says YES", replies[0])

if __name__ == '__main__':
    unittest.main()
