"""
Test if commands send their reply to the client who ran the command or not.

This file contains the following test:
- test_commands_isolation_10_clients: Verifies command isolation by simulating 10 concurrent clients, having one client send a command, and ensuring that only the sender receives the reply while the other 9 bystander clients do not.
"""
import time
import unittest
import socketio
import threading
import os
import sys
import json
import tempfile

# Add server directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

# 1. We must set these BEFORE importing daemon to prevent real alerts/tunnels
os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["MODE"] = "lan"
os.environ["GUGA_VERBOSE"] = "false"

# Create a temporary trusted devices file for 10 devices
tmp_dir = tempfile.mkdtemp()
tmp_trusted = os.path.join(tmp_dir, "trusted_devices.json")
trusted_data = {
    f"browser-{i}": {"token": f"test-token-{i}", "type": "browser", "expires_at": time.time() + 3600}
    for i in range(1, 11)
}
with open(tmp_trusted, "w") as f:
    json.dump(trusted_data, f)

# Import daemon and override the file constant
from guga import daemon
daemon.TRUSTED_DEVICES_FILE = tmp_trusted

from guga.daemon import app, socketio as server_socketio

class VirtualBrowser:
    def __init__(self, device_id, token):
        self.sio = socketio.Client()
        self.device_id = device_id
        self.token = token
        self.received_messages = []

        # Register the handler correctly
        self.sio.on('guga_response', self.on_message)
    
    def on_message(self, data):
        self.received_messages.append(data)
    
    def connect(self, url):
        # Pass device_id and token as query parameters
        self.sio.connect(f"{url}?device_id={self.device_id}&token={self.token}")

    def send_command(self, text):
        self.sio.emit('command', { 'phrase': text, 'device_id': self.device_id })   
        
    def disconnect(self):
        if self.sio.connected:
            self.sio.disconnect()

class TestPrivateCommandReplyToClient(unittest.TestCase):
    server_thread = None

    @classmethod
    def setUpClass(cls):
        cls.server_url = "http://127.0.0.1:6769"
        
        # Start the server in a background thread
        def run_server():
            server_socketio.run(app, host="127.0.0.1", port=6769, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        
        # Give the server a moment to start up
        time.sleep(2)

    def test_commands_isolation_10_clients(self):
        '''Verifies command isolation with 10 concurrent clients.'''
        clients = [VirtualBrowser(f"browser-{i}", f"test-token-{i}") for i in range(1, 11)]

        try:
            for c in clients:
                c.connect(self.server_url)
            
            time.sleep(2) # Wait for all to stabilize

            # Client index 4 (browser-5) sends a command
            sender_index = 4
            clients[sender_index].send_command("Multi-client test")
            time.sleep(1)

            # Assertions
            for i, c in enumerate(clients):
                if i == sender_index:
                    # Sender should have Welcome + Reply
                    self.assertEqual(len(c.received_messages), 2, f"Sender (client {i+1}) should have received reply")
                    self.assertEqual(c.received_messages[1]["title"], "System")
                    self.assertIn("Multi-client test", c.received_messages[1]["message"])
                else:
                    # Others should ONLY have the Welcome message
                    self.assertEqual(len(c.received_messages), 1, f"Bystander (client {i+1}) should NOT have received reply")

        finally:
            for c in clients:
                c.disconnect()
        



    

if __name__ == '__main__': 
    unittest.main()