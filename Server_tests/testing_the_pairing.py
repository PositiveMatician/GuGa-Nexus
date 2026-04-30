"""
Tests for the pairing API logic (Phase 20.1: Client-Generated PIN & Approval).

This file covers manual test suites 2, 3, and 4 from TODO.md:
- TestPairingSuite2: Concurrent pairing requests and Watch mode logic.
- TestPairingSuite3: Security, manual rejection, rate limiting, and localhost protection.
- TestPairingSuite4: Edge cases like TTL expiration, force re-pair, and device name fallback.
"""

import time
import unittest
import os
import sys
import json
import tempfile

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["MODE"] = "lan"
os.environ["GUGA_VERBOSE"] = "false"

# Create a temporary trusted devices file
tmp_dir = tempfile.mkdtemp()
tmp_trusted = os.path.join(tmp_dir, "trusted_devices.json")
with open(tmp_trusted, "w") as f:
    json.dump({}, f)

from guga import daemon
daemon.TRUSTED_DEVICES_FILE = tmp_trusted
from guga.daemon import app

class TestPairingSuite2(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        daemon.pending_pairings.clear()
        daemon.blocked_devices.clear()

    def test_concurrent_pairing(self):
        '''Suite 2.3: Concurrent Pairing Requests'''
        res1 = self.client.post("/api/hello", json={"device_id": "b-1", "pin": "11111111", "device_name": "Device 1"})
        res2 = self.client.post("/api/hello", json={"device_id": "b-2", "pin": "22222222", "device_name": "Device 2"})
        
        self.assertEqual(res1.json["status"], "pin_required")
        self.assertEqual(res2.json["status"], "pin_required")
        
        # Verify both appear in pending
        pending = self.client.get("/api/pending", environ_base={'REMOTE_ADDR': '127.0.0.1'}).json["pending"]
        self.assertEqual(len(pending), 2)
        
        # Approve both
        self.client.post("/api/approve", json={"device_id": "b-1", "action": "approve"}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
        self.client.post("/api/approve", json={"device_id": "b-2", "action": "approve"}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
        
        # Verify tokens
        v1 = self.client.post("/api/verify_pin", json={"device_id": "b-1", "pin": "11111111", "client_type": "browser"})
        v2 = self.client.post("/api/verify_pin", json={"device_id": "b-2", "pin": "22222222", "client_type": "browser"})
        
        self.assertEqual(v1.json["status"], "paired")
        self.assertEqual(v2.json["status"], "paired")

class TestPairingSuite3(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        daemon.pending_pairings.clear()
        daemon.blocked_devices.clear()

    def test_manual_rejection(self):
        '''Suite 3.5: Manual Rejection'''
        self.client.post("/api/hello", json={"device_id": "rej-1", "pin": "12345678", "device_name": "RejectMe"})
        
        # Reject
        rej_res = self.client.post("/api/approve", json={"device_id": "rej-1", "action": "reject"}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
        self.assertEqual(rej_res.json["status"], "rejected")
        
        # Verify client gets blocked
        v_res = self.client.post("/api/verify_pin", json={"device_id": "rej-1", "pin": "12345678"})
        self.assertEqual(v_res.status_code, 404) # 404 because pending entry was deleted

    def test_rate_limiting(self):
        '''Suite 3.6: Rate Limiting (Brute Force Protection)'''
        self.client.post("/api/hello", json={"device_id": "brute-1", "pin": "11111111", "device_name": "Brute"})
        
        # 4 Wrong attempts
        for _ in range(4):
            res = self.client.post("/api/verify_pin", json={"device_id": "brute-1", "pin": "00000000"})
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.json["error"], "Invalid PIN")
            
        # 5th Wrong attempt -> too many attempts
        res5 = self.client.post("/api/verify_pin", json={"device_id": "brute-1", "pin": "00000000"})
        self.assertEqual(res5.status_code, 401)
        self.assertEqual(res5.json["error"], "too many attempts")
        
        # New hello request should be blocked (429)
        new_hello = self.client.post("/api/hello", json={"device_id": "brute-1", "pin": "11111111", "device_name": "Brute"})
        self.assertEqual(new_hello.status_code, 429)
        self.assertEqual(new_hello.json["error"], "too many failed attempts")

    def test_localhost_protection(self):
        '''Suite 3.7: Localhost-Only Protection'''
        self.client.post("/api/hello", json={"device_id": "local-1", "pin": "11111111", "device_name": "Local"})
        
        # Attempt from different IP
        external_ip = '192.168.1.100'
        
        pending_res = self.client.get("/api/pending", environ_base={'REMOTE_ADDR': external_ip})
        self.assertEqual(pending_res.status_code, 403)
        
        approve_res = self.client.post("/api/approve", json={"device_id": "local-1", "action": "approve"}, environ_base={'REMOTE_ADDR': external_ip})
        self.assertEqual(approve_res.status_code, 403)

class TestPairingSuite4(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        daemon.pending_pairings.clear()
        daemon.blocked_devices.clear()

    def test_pairing_request_expiration(self):
        '''Suite 4.8: Pairing Request Expiration (TTL)'''
        self.client.post("/api/hello", json={"device_id": "ttl-1", "pin": "12345678", "device_name": "ExpireMe"})
        
        # Manually alter the requested_at time to simulate 6 minutes passing
        daemon.pending_pairings["ttl-1"]["requested_at"] = time.time() - 360
        
        # GET /api/pending automatically calls clean_expired_pairings()
        pending = self.client.get("/api/pending", environ_base={'REMOTE_ADDR': '127.0.0.1'}).json["pending"]
        self.assertEqual(len(pending), 0)
        self.assertNotIn("ttl-1", daemon.pending_pairings)

    def test_force_repair(self):
        '''Suite 4.9: Force Re-pair'''
        # Initial pairing
        self.client.post("/api/hello", json={"device_id": "repair-1", "pin": "11111111", "device_name": "Repair"})
        self.client.post("/api/approve", json={"device_id": "repair-1", "action": "approve"}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
        v1 = self.client.post("/api/verify_pin", json={"device_id": "repair-1", "pin": "11111111", "client_type": "app"})
        token1 = v1.json["token"]
        
        # Re-send without force_pair should return trusted
        hello_trusted = self.client.post("/api/hello", json={"device_id": "repair-1"})
        self.assertEqual(hello_trusted.json["status"], "trusted")
        
        # Re-send with force_pair
        hello_force = self.client.post("/api/hello", json={"device_id": "repair-1", "pin": "22222222", "force_pair": True, "device_name": "Repair"})
        self.assertEqual(hello_force.json["status"], "pin_required")
        
        # Approve and verify new token
        self.client.post("/api/approve", json={"device_id": "repair-1", "action": "approve"}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
        v2 = self.client.post("/api/verify_pin", json={"device_id": "repair-1", "pin": "22222222", "client_type": "app"})
        token2 = v2.json["token"]
        
        self.assertNotEqual(token1, token2)

    def test_device_name_fallback(self):
        '''Suite 4.10: Device Name Fallback'''
        # Send /api/hello without device_name
        self.client.post("/api/hello", json={"device_id": "anon-1", "pin": "12345678"})
        
        pending = self.client.get("/api/pending", environ_base={'REMOTE_ADDR': '127.0.0.1'}).json["pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["device_name"], "Unknown Device")

if __name__ == '__main__':
    unittest.main()
