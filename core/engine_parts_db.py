from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text atomically to avoid truncated/corrupted JSON on crash.

    Strategy: write to a temp file in the same directory, then os.replace.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


@dataclass
class EnginePartRecord:
    """One observed engine_part_* entry, persisted editor-side."""

    key: str
    label: str = ""
    sample: Optional[Any] = None
    first_seen_utc: str = ""
    last_seen_utc: str = ""
    seen_count: int = 0

    def to_json(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "sample": self.sample,
            "first_seen_utc": self.first_seen_utc,
            "last_seen_utc": self.last_seen_utc,
            "seen_count": self.seen_count,
        }

    @classmethod
    def from_json(cls, key: str, obj: Dict[str, Any]) -> "EnginePartRecord":
        return cls(
            key=key,
            label=str(obj.get("label") or ""),
            sample=obj.get("sample"),
            first_seen_utc=str(obj.get("first_seen_utc") or ""),
            last_seen_utc=str(obj.get("last_seen_utc") or ""),
            seen_count=int(obj.get("seen_count") or 0),
        )


class EnginePartsDb:
    """Small editor-side database of engine_part_* entries.

    Purpose:
    - Persist discovered engine_part_* keys across runs
    - Optionally store a "sample" payload for future tooling

    Stored at ``data/engine_parts_db.json``.
    """

    def __init__(self, path: Path, parts: Optional[Dict[str, EnginePartRecord]] = None):
        self.path = path
        self.parts: Dict[str, EnginePartRecord] = parts or {}

    @classmethod
    def load_default(cls, base_dir: Path) -> "EnginePartsDb":
        path = base_dir / "data" / "engine_parts_db.json"
        if not path.exists():
            return cls(path, {})
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            src = raw.get("engine_parts") if isinstance(raw, dict) else None
            parts: Dict[str, EnginePartRecord] = {}
            if isinstance(src, dict):
                for k, v in src.items():
                    if isinstance(k, str) and k.startswith("engine_part_") and isinstance(v, dict):
                        parts[k] = EnginePartRecord.from_json(k, v)
            return cls(path, parts)
        except Exception:
            return cls(path, {})

    def save(self) -> None:
        """Persist the database to disk.

        Important: we *do not* swallow exceptions here.
        EnginePartsTab/MainWindow will catch/log failures so we can see why a
        write did not happen (the previous behavior silently "lost" the DB).

        We also use json.dumps(..., default=str) so that any non-JSON-serializable
        values inside a sample payload do not prevent the DB from saving.
        """

        payload = {
            "updated_utc": _utc_now_iso(),
            "engine_parts": {k: rec.to_json() for k, rec in sorted(self.parts.items())},
        }
        _atomic_write_text(
            self.path,
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        )

    def observe_m_items(self, m_items: Dict[str, Any], *, label_resolver=None) -> int:
        """Merge all engine_part_* entries from a save into this DB.

        Returns the number of new keys added.
        """

        now = _utc_now_iso()
        added = 0
        for k, v in (m_items or {}).items():
            ks = str(k)
            if not ks.startswith("engine_part_"):
                continue

            rec = self.parts.get(ks)
            if rec is None:
                rec = EnginePartRecord(key=ks, first_seen_utc=now)
                self.parts[ks] = rec
                added += 1
            rec.last_seen_utc = now
            rec.seen_count = int(rec.seen_count or 0) + 1

            # Store a sample payload (best-effort JSON-serializable)
            rec.sample = v

            if label_resolver is not None:
                try:
                    lbl = str(label_resolver(ks) or "").strip()
                    if lbl and lbl != ks:
                        rec.label = lbl
                except Exception:
                    pass

        # Save only if we observed at least one engine_part_* entry.
        if self.parts:
            self.save()
        return added

    def label(self, key: str) -> str:
        rec = self.parts.get(str(key))
        if rec and rec.label:
            return rec.label
        return str(key)
