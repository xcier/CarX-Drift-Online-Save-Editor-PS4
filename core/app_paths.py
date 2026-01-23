from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable


def _is_portable_mode(base_dir: Path) -> bool:
    """Return True if the app should store data beside the project/exe.

    Portable mode is enabled by:
      - environment variable CARX_EDITOR_PORTABLE=1, or
      - a file named 'portable.flag' inside <base_dir>/data
    """
    if os.environ.get("CARX_EDITOR_PORTABLE", "").strip() == "1":
        return True
    try:
        return (Path(base_dir) / "data" / "portable.flag").exists()
    except Exception:
        return False


def _qt_app_data_dir(app_name: str) -> Path | None:
    """Return per-user application data directory using Qt QStandardPaths."""
    try:
        from PyQt6.QtCore import QStandardPaths

        loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        if not loc:
            loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not loc:
            return None
        p = Path(loc) / app_name
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return None


def get_writable_data_dir(base_dir: Path, *, app_name: str = "carx-drift-editor") -> Path:
    """Return a stable writable directory for editor-side data.

    Default (non-portable) behavior stores data in the user's per-app data directory
    using Qt QStandardPaths. Portable mode stores data in <base_dir>/data.

    Always returns a directory that exists (created if needed).
    """
    base_dir = Path(base_dir)

    # Portable mode: keep data beside the project/exe.
    if _is_portable_mode(base_dir):
        data_dir = base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    # Preferred: per-user Qt location.
    qt_dir = _qt_app_data_dir(app_name)
    if qt_dir is not None:
        return qt_dir

    # Fallback: project-local data/
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def migrate_portable_files_if_needed(base_dir: Path, target_dir: Path, filenames: Iterable[str]) -> None:
    """Copy known JSON DB files from <base_dir>/data into `target_dir` once.

    Only copies when source exists and destination does not exist.
    """
    src_dir = Path(base_dir) / "data"
    if not src_dir.exists():
        return
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for name in filenames:
        try:
            src = src_dir / name
            dst = target_dir / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
        except Exception:
            continue
