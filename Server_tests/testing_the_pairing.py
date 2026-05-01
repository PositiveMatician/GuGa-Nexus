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

# Create a temporary database
tmp_dir = tempfile.mkdtemp()
tmp_db = os.path.join(tmp_dir, "guga_test.db")
os.environ["GUGA_DB_PATH"] = tmp_db

from guga.db_utils import Database
db_test = Database(tmp_db)

from guga import daemon
# daemon.TRUSTED_DEVICES_FILE = tmp_trusted  # No longer needed
from guga.daemon import app
import asyncio

class TestPairingSuite2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = app.test_client()
        with db_test._get_connection() as conn:
            conn.execute("DELETE FROM pending_pairings")
            conn.execute("DELETE FROM blocked_devices")
            conn.execute("DELETE FROM trusted_devices")
            conn.commit()

    async def test_concurrent_pairing(self):
        '''Suite 2.3: Concurrent Pairing Requests'''
        res1 = await self.client.post("/api/hello", json={"device_id": "b-1", "pin": "11111111", "device_name": "Device 1"})
        res2 = await self.client.post("/api/hello", json={"device_id": "b-2", "pin": "22222222", "device_name": "Device 2"})
        
        r1_json = await res1.get_json()
        r2_json = await res2.get_json()
        self.assertEqual(r1_json["status"], "pin_required")
        self.assertEqual(r2_json["status"], "pin_required")
        
        # Verify both appear in pending
        pending_res = await self.client.get("/api/pending", scope_base={'client': ('127.0.0.1', 12345)})
        pending_json = await pending_res.get_json()
        pending = pending_json["pending"]
        self.assertEqual(len(pending), 2)
        
        # Approve both
        await self.client.post("/api/approve", json={"device_id": "b-1", "action": "approve"}, scope_base={'client': ('127.0.0.1', 12345)})
        await self.client.post("/api/approve", json={"device_id": "b-2", "action": "approve"}, scope_base={'client': ('127.0.0.1', 12345)})
        
        # Verify tokens
        v1_res = await self.client.post("/api/verify_pin", json={"device_id": "b-1", "pin": "11111111", "client_type": "browser"})
        v2_res = await self.client.post("/api/verify_pin", json={"device_id": "b-2", "pin": "22222222", "client_type": "browser"})
        
        v1_json = await v1_res.get_json()
        v2_json = await v2_res.get_json()
        self.assertEqual(v1_json["status"], "paired")
        self.assertEqual(v2_json["status"], "paired")

class TestPairingSuite3(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = app.test_client()
        with db_test._get_connection() as conn:
            conn.execute("DELETE FROM pending_pairings")
            conn.execute("DELETE FROM blocked_devices")
            conn.execute("DELETE FROM trusted_devices")
            conn.commit()

    async def test_manual_rejection(self):
        '''Suite 3.5: Manual Rejection'''
        await self.client.post("/api/hello", json={"device_id": "rej-1", "pin": "12345678", "device_name": "RejectMe"})
        
        # Reject
        rej_res = await self.client.post("/api/approve", json={"device_id": "rej-1", "action": "reject"}, scope_base={'client': ('127.0.0.1', 12345)})
        rej_json = await rej_res.get_json()
        self.assertEqual(rej_json["status"], "rejected")
        
        # Verify client gets blocked
        v_res = await self.client.post("/api/verify_pin", json={"device_id": "rej-1", "pin": "12345678"})
        self.assertEqual(v_res.status_code, 404) # 404 because pending entry was deleted

    async def test_rate_limiting(self):
        '''Suite 3.6: Rate Limiting (Brute Force Protection)'''
        await self.client.post("/api/hello", json={"device_id": "brute-1", "pin": "11111111", "device_name": "Brute"})
        
        # 4 Wrong attempts
        for _ in range(4):
            res = await self.client.post("/api/verify_pin", json={"device_id": "brute-1", "pin": "00000000"})
            self.assertEqual(res.status_code, 401)
            res_json = await res.get_json()
            self.assertEqual(res_json["error"], "Invalid PIN")
            
        # 5th Wrong attempt -> too many attempts
        res5 = await self.client.post("/api/verify_pin", json={"device_id": "brute-1", "pin": "00000000"})
        self.assertEqual(res5.status_code, 401)
        res5_json = await res5.get_json()
        self.assertEqual(res5_json["error"], "too many attempts")
        
        # New hello request should be blocked (429)
        new_hello = await self.client.post("/api/hello", json={"device_id": "brute-1", "pin": "11111111", "device_name": "Brute"})
        self.assertEqual(new_hello.status_code, 429)
        new_hello_json = await new_hello.get_json()
        self.assertEqual(new_hello_json["error"], "too many failed attempts")

    async def test_localhost_protection(self):
        '''Suite 3.7: Localhost-Only Protection'''
        await self.client.post("/api/hello", json={"device_id": "local-1", "pin": "11111111", "device_name": "Local"})
        
        # Attempt from different IP
        external_ip = '192.168.1.100'
        
        pending_res = await self.client.get("/api/pending", scope_base={'client': (external_ip, 12345)})
        self.assertEqual(pending_res.status_code, 403)
        
        approve_res = await self.client.post("/api/approve", json={"device_id": "local-1", "action": "approve"}, scope_base={'client': (external_ip, 12345)})
        self.assertEqual(approve_res.status_code, 403)

class TestPairingSuite4(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = app.test_client()
        with db_test._get_connection() as conn:
            conn.execute("DELETE FROM pending_pairings")
            conn.execute("DELETE FROM blocked_devices")
            conn.execute("DELETE FROM trusted_devices")
            conn.commit()

    async def test_pairing_request_expiration(self):
        '''Suite 4.8: Pairing Request Expiration (TTL)'''
        await self.client.post("/api/hello", json={"device_id": "ttl-1", "pin": "12345678", "device_name": "ExpireMe"})
        
        # Manually alter the requested_at time to simulate 6 minutes passing
        db_test.update_pending_pairing("ttl-1", requested_at=time.time() - 360)
        
        # GET /api/pending automatically calls clean_expired_pairings()
        pending_res = await self.client.get("/api/pending", scope_base={'client': ('127.0.0.1', 12345)})
        pending_json = await pending_res.get_json()
        pending = pending_json["pending"]
        self.assertEqual(len(pending), 0)
        self.assertIsNone(db_test.get_pending_pairing("ttl-1"))

    async def test_force_repair(self):
        '''Suite 4.9: Force Re-pair'''
        # Initial pairing
        await self.client.post("/api/hello", json={"device_id": "repair-1", "pin": "11111111", "device_name": "Repair"})
        await self.client.post("/api/approve", json={"device_id": "repair-1", "action": "approve"}, scope_base={'client': ('127.0.0.1', 12345)})
        v1_res = await self.client.post("/api/verify_pin", json={"device_id": "repair-1", "pin": "11111111", "client_type": "app"})
        v1_json = await v1_res.get_json()
        token1 = v1_json["token"]
        
        # Re-send without force_pair should return trusted
        hello_trusted_res = await self.client.post("/api/hello", json={"device_id": "repair-1"})
        hello_trusted_json = await hello_trusted_res.get_json()
        self.assertEqual(hello_trusted_json["status"], "trusted")
        
        # Re-send with force_pair
        hello_force_res = await self.client.post("/api/hello", json={"device_id": "repair-1", "pin": "22222222", "force_pair": True, "device_name": "Repair"})
        hello_force_json = await hello_force_res.get_json()
        self.assertEqual(hello_force_json["status"], "pin_required")
        
        # Approve and verify new token
        await self.client.post("/api/approve", json={"device_id": "repair-1", "action": "approve"}, scope_base={'client': ('127.0.0.1', 12345)})
        v2_res = await self.client.post("/api/verify_pin", json={"device_id": "repair-1", "pin": "22222222", "client_type": "app"})
        v2_json = await v2_res.get_json()
        token2 = v2_json["token"]
        
        self.assertNotEqual(token1, token2)

    async def test_device_name_fallback(self):
        '''Suite 4.10: Device Name Fallback'''
        # Send /api/hello without device_name
        await self.client.post("/api/hello", json={"device_id": "anon-1", "pin": "12345678"})
        
        pending_res = await self.client.get("/api/pending", scope_base={'client': ('127.0.0.1', 12345)})
        pending_json = await pending_res.get_json()
        pending = pending_json["pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["device_name"], "Unknown Device")

if __name__ == '__main__':
    unittest.main()
