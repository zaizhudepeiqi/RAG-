import os
from pathlib import Path
from uuid import uuid4


class LocalStorageAdapter:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("storage root must be absolute")
        self._root = root

    def check_writable(self) -> None:
        health_dir = self._root / ".health"
        health_dir.mkdir(parents=True, exist_ok=True)
        source = health_dir / f"{uuid4()}.tmp"
        target = health_dir / f"{uuid4()}.ok"
        try:
            with source.open("wb") as handle:
                handle.write(b"ok")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(source, target)
        finally:
            source.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
