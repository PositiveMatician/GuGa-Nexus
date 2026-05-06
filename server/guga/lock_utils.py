"""
GuGa Nexus — Locking Utilities
Version: 1.6.0

Cross-platform file locking using the `filelock` package.
Works on Linux (fcntl), macOS, and Windows (msvcrt) transparently.
"""

import os
from filelock import FileLock as _FileLock, Timeout


class FileLock:
    """Cross-platform file lock backed by the `filelock` package."""

    def __init__(self, lock_name: str):
        config_dir = os.environ.get("GUGA_CONFIG_DIR", os.path.expanduser("~/.guga"))
        os.makedirs(config_dir, exist_ok=True)
        self.lock_file = os.path.join(config_dir, f"{lock_name}.lock")
        self._lock = _FileLock(self.lock_file)

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """Acquire lock. Returns True on success, False on timeout/non-blocking miss."""
        try:
            # timeout=-1 means block forever; 0 means non-blocking
            effective_timeout = -1 if blocking and timeout < 0 else (0 if not blocking else timeout)
            self._lock.acquire(timeout=effective_timeout)
            return True
        except Timeout:
            return False

    def release(self):
        """Release lock."""
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
