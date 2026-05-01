import unittest
import threading
import time
import os
import sys
import json
import socketio
from unittest.mock import patch, MagicMock

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

from guga import daemon
from guga.daemon import app, socketio as server_socketio, connected_clients

class TestConcurrentAsks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_utils import kill_port
        cls.server_port = 6782
        kill_port(cls.server_port)
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        
        # Prevent real notifications
        os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
        os.environ["GUGA_TEST_MODE"] = "True" # Allow bypass of auth for testing
        
        def run_server():
            os.environ["PORT"] = str(cls.server_port)
            daemon.run_server()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.sio = socketio.Client()
        self.sio.connect(f"{self.server_url}?device_id=test-device&token=test-token")
        time.sleep(0.5)
        self.received_asks = []
        self.received_responses = []

        @self.sio.on('guga_ask')
        def on_ask(data):
            self.received_asks.append(data)

        @self.sio.on('guga_response')
        def on_response(data):
            self.received_responses.append(data)

    def tearDown(self):
        if self.sio.connected:
            self.sio.disconnect()

    def test_concurrent_asks_with_specific_replies(self):
        """Verify that two concurrent asks can be resolved via explicit request_id."""
        from guga import cli
        
        results = {}
        
        def ask_1():
            res = cli.guga_ask_user("Question 1", self.server_port, "test-device", timeout=30)
            results['ask_1'] = res
            
        def ask_2():
            res = cli.guga_ask_user("Question 2", self.server_port, "test-device", timeout=30)
            results['ask_2'] = res

        t1 = threading.Thread(target=ask_1)
        t2 = threading.Thread(target=ask_2)
        
        t1.start()
        time.sleep(1) # Ensure order
        t2.start()
        
        # Wait for both asks to be received by client
        max_wait = 10
        while len(self.received_asks) < 2 and max_wait > 0:
            time.sleep(0.5)
            max_wait -= 0.5
            
        self.assertEqual(len(self.received_asks), 2)
        
        # Identify IDs
        id1 = self.received_asks[0]['request_id']
        id2 = self.received_asks[1]['request_id']
        
        # Reply to ID 1 first, then ID 2
        self.sio.emit('reply', {'request_id': id1, 'message': 'Reply to 1'})
        time.sleep(0.5)
        self.sio.emit('reply', {'request_id': id2, 'message': 'Reply to 2'})
        
        t1.join(timeout=5)
        t2.join(timeout=5)
        
        self.assertEqual(results.get('ask_1'), 'Reply to 1')
        self.assertEqual(results.get('ask_2'), 'Reply to 2')

    def test_stack_fallback_reply(self):
        """Verify that a reply without request_id resolves the LATEST ask."""
        from guga import cli
        
        results = {}
        
        def ask_1():
            res = cli.guga_ask_user("Question 1", self.server_port, "test-device", timeout=10)
            results['ask_1'] = res
            
        def ask_2():
            res = cli.guga_ask_user("Question 2", self.server_port, "test-device", timeout=10)
            results['ask_2'] = res

        t1 = threading.Thread(target=ask_1)
        t2 = threading.Thread(target=ask_2)
        
        t1.start()
        time.sleep(1)
        t2.start()
        
        time.sleep(1) # Wait for asks
        
        # Reply without ID - should hit Ask 2 (latest)
        self.sio.emit('reply', {'message': 'Latest Reply'})
        
        t2.join(timeout=5)
        self.assertEqual(results.get('ask_2'), 'Latest Reply')
        self.assertNotIn('ask_1', results) # Ask 1 should still be pending
        
        # Now reply again - should hit Ask 1
        self.sio.emit('reply', {'message': 'Next Reply'})
        t1.join(timeout=5)
        self.assertEqual(results.get('ask_1'), 'Next Reply')

    def test_command_bypass_with_none_id(self):
        """Verify that sending a command with request_id=None bypasses the interactive block."""
        from guga import cli
        
        results = {}
        def ask_thread():
            res = cli.guga_ask_user("Blocking Question", self.server_port, "test-device", timeout=10)
            results['ask'] = res

        t = threading.Thread(target=ask_thread)
        t.start()
        time.sleep(1)
        
        # 1. Send normal command - should be intercepted as reply
        self.sio.emit('command', {'device_id': 'test-device', 'phrase': 'Intercepted'})
        t.join(timeout=5)
        self.assertEqual(results.get('ask'), 'Intercepted')
        
        # 2. Reset and test bypass
        results.clear()
        t = threading.Thread(target=ask_thread)
        t.start()
        time.sleep(1)
        
        # Send command with request_id=None - should NOT be intercepted
        self.sio.emit('command', {'device_id': 'test-device', 'phrase': 'Bypass Command', 'request_id': None})
        time.sleep(1)
        
        # Check if we got a guga_response for the command (meaning it was processed as a command)
        self.assertTrue(any("Bypass Command" in r.get('message', '') for r in self.received_responses))
        self.assertNotIn('ask', results) # Ask should still be pending
        
        # Finally resolve the ask
        self.sio.emit('reply', {'message': 'Final Resolution'})
        t.join(timeout=5)
        self.assertEqual(results.get('ask'), 'Final Resolution')

    def test_concurrent_pty_sessions(self):
        """Verify that two PTY-based interactive sessions can run concurrently and resolve correctly."""
        from guga import cli
        
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'scratch', 'prompt_script.py'))
        results = {}
        
        # Auto-responder: reply to each ask as it arrives, mapping session order to names
        reply_map = {}
        ask_count = [0]
        names = ["UserOne", "UserTwo"]
        
        @self.sio.on('guga_ask')
        def auto_reply(data):
            req_id = data.get('request_id')
            idx = ask_count[0]
            ask_count[0] += 1
            self.received_asks.append(data)
            if idx < len(names):
                reply_map[req_id] = names[idx]
                # Reply immediately in a separate thread to avoid blocking
                def do_reply():
                    time.sleep(0.3)
                    self.sio.emit('reply', {'request_id': req_id, 'message': names[idx]})
                threading.Thread(target=do_reply, daemon=True).start()
        
        def run_session(session_id):
            with patch('sys.stdout.write') as mock_write:
                try:
                    cli.run_interactive_command([sys.executable, script_path], self.server_port, False, f"Session {session_id}", "test-device")
                except SystemExit:
                    pass
                output = "".join(call.args[0] for call in mock_write.call_args_list)
                results[session_id] = output

        t1 = threading.Thread(target=run_session, args=(1,))
        t2 = threading.Thread(target=run_session, args=(2,))
        
        t1.start()
        time.sleep(2)  # Give session 1 enough time to spawn and emit a prompt
        t2.start()
        
        t1.join(timeout=20)
        t2.join(timeout=20)
        
        self.assertIn("Hello, UserOne!", results.get(1, ""), f"Session 1 output mismatch: {results.get(1)}")
        self.assertIn("Hello, UserTwo!", results.get(2, ""), f"Session 2 output mismatch: {results.get(2)}")

if __name__ == '__main__':
    unittest.main()
