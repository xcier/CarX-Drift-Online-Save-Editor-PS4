from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_write_bytes_qt(path: Path, data: bytes) -> bool:
    """Try atomic write using Qt QSaveFile. Returns True if used."""
    try:
        from PyQt6.QtCore import QSaveFile, QIODevice

        path.parent.mkdir(parents=True, exist_ok=True)
        f = QSaveFile(str(path))
        if not f.open(QIODevice.OpenModeFlag.WriteOnly):
            return False
        # QSaveFile inherits QIODevice; write() accepts bytes.
        n = f.write(data)
        if n == -1:
            f.cancelWriting()
            return False
        if not f.commit():
            return False
        return True
    except Exception:
        return False


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write bytes to `path`.

    Prefer Qt QSaveFile when available; otherwise fall back to temp file + replace.
    QSaveFile writes to a temporary file and commits it on success, discarding the
    temp file on failure.
    """
    path = Path(path)
    if _atomic_write_bytes_qt(path, data):
        return

    # Fallback: temp file + replace
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", newline: str = "") -> None:
    """Atomically write text to `path`."""
    data = (text if newline is None else text.replace("\n", newline)).encode(encoding)
    atomic_write_bytes(Path(path), data)


def atomic_write_json(path: Path, obj: Any, *, encoding: str = "utf-8", indent: int = 2, ensure_ascii: bool = False) -> None:
    """Atomically write JSON to `path`."""
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)
    atomic_write_text(Path(path), text, encoding=encoding)
