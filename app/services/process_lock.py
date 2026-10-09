"""Kernel-released single-host locks for operations that outlive an HTTP call."""
import os
from pathlib import Path


class ProcessLock:
    """Never unlink a lock file: an unlinked inode could admit two owners."""

    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> bool:
        if self.fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except (BlockingIOError, PermissionError):
            os.close(fd)
            return False
        except OSError as exc:
            os.close(fd)
            if exc.errno in (11, 13, 35, 36):
                return False
            raise
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


def operation_lock_path(database: Path, operation: str) -> Path:
    return database.parent / ("." + database.name + "." + operation + ".lock")
