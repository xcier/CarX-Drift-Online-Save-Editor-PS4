from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


def compute_file_sha1(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def default_work_dir(base_dat: Path, work_root: Path) -> Path:
    """Stable, collision-proof work directory for a given base save file.

    Uses stem + file size + sha1 prefix so different files never share a folder.
    """
    size = base_dat.stat().st_size
    sig = compute_file_sha1(base_dat)[:8]
    return work_root / f"{base_dat.stem}_{size}_{sig}"


@dataclass(frozen=True)
class WorkContext:
    base_dat: Path
    work_dir: Path
    base_sig: str
    file_size: int

    @classmethod
    def from_base(cls, base_dat: Path, work_root: Path) -> "WorkContext":
        base_sig = compute_file_sha1(base_dat)
        file_size = base_dat.stat().st_size
        return cls(base_dat=base_dat, work_dir=default_work_dir(base_dat, work_root), base_sig=base_sig, file_size=file_size)
