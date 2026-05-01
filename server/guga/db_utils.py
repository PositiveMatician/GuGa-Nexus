import os
import sqlite3
import time
import json
from typing import Dict, List, Optional, Any

CONFIG_DIR = os.path.expanduser("~/.guga")
DB_PATH = os.environ.get("GUGA_DB_PATH", os.path.join(CONFIG_DIR, "guga.db"))

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        if not os.path.exists(os.path.dirname(self.db_path)):
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with self._get_connection() as conn:
            # Trusted Devices
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trusted_devices (
                    id TEXT PRIMARY KEY,
                    token TEXT,
                    type TEXT,
                    expires_at REAL,
                    name TEXT,
                    tag TEXT
                )
            """)
            
            # Capabilities
            conn.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # Installed Stages
            conn.execute("""
                CREATE TABLE IF NOT EXISTS installed_stages (
                    stage_id TEXT PRIMARY KEY
                )
            """)
            
            # Pending Pairings
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_pairings (
                    id TEXT PRIMARY KEY,
                    pin TEXT,
                    name TEXT,
                    requested_at REAL,
                    attempts INTEGER DEFAULT 0,
                    approved INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'PENDING'
                )
            """)
            
            # Blocked Devices
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blocked_devices (
                    id TEXT PRIMARY KEY,
                    unblock_at REAL
                )
            """)
            
            # Pending Asks (for concurrent interactive sessions)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_asks (
                    request_id TEXT PRIMARY KEY,
                    device_id TEXT,
                    message TEXT,
                    title TEXT,
                    created_at REAL,
                    reply TEXT,
                    status TEXT DEFAULT 'PENDING'
                )
            """)
            
            conn.commit()

    # --- Trusted Devices ---
    def get_trusted_devices(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM trusted_devices")
            rows = cursor.fetchall()
            return {row['id']: dict(row) for row in rows}

    def save_trusted_device(self, device_id: str, token: str, client_type: str, expires_at: float, name: str, tag: Optional[str] = None):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trusted_devices (id, token, type, expires_at, name, tag)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (device_id, token, client_type, expires_at, name, tag))
            conn.commit()

    def delete_trusted_device(self, device_id: str):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM trusted_devices WHERE id = ?", (device_id,))
            conn.commit()

    # --- Capabilities ---
    def get_capabilities(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            # Get installed stages
            cursor = conn.execute("SELECT stage_id FROM installed_stages")
            stages = [row['stage_id'] for row in cursor.fetchall()]
            
            # Get capabilities
            cursor = conn.execute("SELECT key, value FROM capabilities")
            caps = {row['key']: json.loads(row['value']) for row in cursor.fetchall()}
            
            return {"installed_stages": stages, "capabilities": caps}

    def save_capabilities(self, data: Dict[str, Any]):
        with self._get_connection() as conn:
            # Update stages
            conn.execute("DELETE FROM installed_stages")
            for stage in data.get("installed_stages", []):
                conn.execute("INSERT INTO installed_stages (stage_id) VALUES (?)", (stage,))
            
            # Update capabilities
            conn.execute("DELETE FROM capabilities")
            for key, val in data.get("capabilities", {}).items():
                conn.execute("INSERT INTO capabilities (key, value) VALUES (?, ?)", (key, json.dumps(val)))
            
            conn.commit()

    # --- Pending Pairings ---
    def get_pending_pairings(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM pending_pairings WHERE approved = 0")
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_pairing(self, device_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM pending_pairings WHERE id = ?", (device_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_pending_pairing(self, device_id: str, pin: str, name: str):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pending_pairings (id, pin, name, requested_at, attempts, approved, status)
                VALUES (?, ?, ?, ?, 0, 0, 'PENDING')
            """, (device_id, pin, name, time.time()))
            conn.commit()

    def update_pending_pairing(self, device_id: str, **kwargs):
        if not kwargs: return
        cols = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [device_id]
        with self._get_connection() as conn:
            conn.execute(f"UPDATE pending_pairings SET {cols} WHERE id = ?", vals)
            conn.commit()

    def delete_pending_pairing(self, device_id: str):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM pending_pairings WHERE id = ?", (device_id,))
            conn.commit()

    # --- Blocked Devices ---
    def get_blocked_devices(self) -> Dict[str, float]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id, unblock_at FROM blocked_devices")
            return {row['id']: row['unblock_at'] for row in cursor.fetchall()}

    def block_device(self, device_id: str, unblock_at: float):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO blocked_devices (id, unblock_at) VALUES (?, ?)", (device_id, unblock_at))
            conn.commit()

    def unblock_device(self, device_id: str):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM blocked_devices WHERE id = ?", (device_id,))
            conn.commit()

    # --- Pending Asks ---
    def add_pending_ask(self, request_id: str, device_id: str, message: str, title: str):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO pending_asks (request_id, device_id, message, title, created_at, status)
                VALUES (?, ?, ?, ?, ?, 'PENDING')
            """, (request_id, device_id, message, title, time.time()))
            conn.commit()

    def set_ask_reply(self, request_id: str, reply: str):
        with self._get_connection() as conn:
            conn.execute("UPDATE pending_asks SET reply = ?, status = 'COMPLETED' WHERE request_id = ?", (reply, request_id))
            conn.commit()

    def get_pending_ask(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM pending_asks WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
