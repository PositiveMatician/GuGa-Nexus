"""
Tests the messaging between server and clients


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

# Create a temporary trusted devices file
tmp_dir = tempfile.mkdtemp()
tmp_trusted = os.path.join(tmp_dir, "trusted_devices.json")
with open(tmp_trusted, "w") as f:
    json.dump({
        "browser-1": {"token": "test-token-1", "type": "browser", "expires_at": time.time() + 3600},
        "browser-2": {"token": "test-token-2", "type": "browser", "expires_at": time.time() + 3600}
    }, f)

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
        
    def disconnect(self):
        if self.sio.connected:
            self.sio.disconnect()

class TestPrivateMessagesToClient(unittest.TestCase):
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

    def test_broadcast_message(self):
        '''Sends a broadcast message to all the clients'''

        client1 = VirtualBrowser("browser-1", "test-token-1")
        client2 = VirtualBrowser("browser-2", "test-token-2")

        try:
            client1.connect(self.server_url)
            client2.connect(self.server_url)
            time.sleep(1)

            # Trigger broadcast via the server's HTTP API
            with app.test_client() as c:
                c.post("/send", json={
                    "message": "Hello",
                    "title": "test"
                })
            
            # Wait for Socket.IO delivery
            time.sleep(1)

            # Assertions (Each client gets 2 messages: Welcome + Broadcast)
            self.assertEqual(len(client1.received_messages), 2)
            self.assertEqual(len(client2.received_messages), 2)

            # Check the broadcast message (the second one received)
            self.assertEqual(client1.received_messages[1]["message"], "Hello")
            self.assertEqual(client1.received_messages[1]["title"], "test")

        finally:
            client1.disconnect()
            client2.disconnect()

    def test_private_messages(self):
        '''Sends a private message to a specific client and ensures others don't get it'''
        
        from guga.daemon import connected_clients 
        \
        client1 = VirtualBrowser("browser-1", "test-token-1")
        client2 = VirtualBrowser("browser-2", "test-token-2")

        try:
            client1.connect(self.server_url)
            client2.connect(self.server_url)
            time.sleep(1)
            
            # Now we use the device_id directly!
            with app.test_client() as c:
                # 1. Send to Client 1 only
                c.post(f"/send/{client1.device_id}", json={
                    "message": "Secret for 1",
                    "title": "Private"
                })
                
                # 2. Send to Client 2 only
                c.post(f"/send/{client2.device_id}", json={
                    "message": "Secret for 2",
                    "title": "Private"
                })

            time.sleep(1)

            # Each should have 2 messages total (1 Welcome + 1 its own secret)
            self.assertEqual(len(client1.received_messages), 2)
            self.assertEqual(len(client2.received_messages), 2)

            self.assertEqual(client1.received_messages[1]["message"], "Secret for 1")
            self.assertEqual(client2.received_messages[1]["message"], "Secret for 2")

        finally:
            client1.disconnect()
            client2.disconnect()

if __name__ == '__main__': 
    unittest.main()