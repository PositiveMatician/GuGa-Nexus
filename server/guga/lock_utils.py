"""
GuGa Nexus — Locking Utilities
Version: 1.5.0

This module provides simple file-based locking to prevent race conditions
during installation and concurrent system operations.
"""

import os
import fcntl
import time
from typing import Optional

class FileLock:
    """A cross-process file lock using fcntl.flock."""
    def __init__(self, lock_name: str):
        config_dir = os.path.expanduser("~/.guga")
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        self.lock_file = os.path.join(config_dir, f"{lock_name}.lock")
        self.fd = None

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """Acquire the lock. Returns True if successful."""
        self.fd = os.open(self.lock_file, os.O_RDWR | os.O_CREAT)
        
        start_time = time.time()
        while True:
            try:
                if blocking:
                    fcntl.flock(self.fd, fcntl.LOCK_EX)
                    return True
                else:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
            except BlockingIOError:
                if not blocking:
                    return False
                if timeout is not None and (time.time() - start_time) > timeout:
                    return False
                time.sleep(0.1)

    def release(self):
        """Release the lock."""
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
