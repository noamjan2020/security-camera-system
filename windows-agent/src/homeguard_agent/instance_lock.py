from __future__ import annotations

import atexit
import os
import platform
from pathlib import Path


class SingleInstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        try:
            if platform.system() == "Windows":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError) as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError("Another HomeGuard Agent instance is already running") from exc
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        atexit.register(self.release)

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if platform.system() == "Windows":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass
        self._handle.close()
        self._handle = None
