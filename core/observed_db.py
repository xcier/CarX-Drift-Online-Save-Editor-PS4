from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, Any, Optional, Union
import json

from .fs_atomic import atomic_write_json

from datetime import datetime


@dataclass
class ObservedDb:
    """Lightweight persistence for IDs observed in saves.

    Backwards-compatible: older versions stored values as strings (e.g. name)
    instead of dict records. We normalize on load and during upsert.
    """

    cars: Dict[str, Dict[str, Any]]
    tracks: Dict[str, Dict[str, Any]]

    @staticmethod
    def _normalize_table(obj: Any) -> Dict[str, Dict[str, Any]]:
        """Normalize legacy shapes into {id: record_dict}."""
        if obj is None:
            return {}
        # Legacy: list of ids -> convert to dict records
        if isinstance(obj, list):
            out: Dict[str, Dict[str, Any]] = {}
            for x in obj:
                if x is None:
                    continue
                sid = str(x)
                out[sid] = {"first_seen": None, "last_seen": None, "count": 0, "sources": []}
            return out
        # Expected: dict
        if isinstance(obj, dict):
            out2: Dict[str, Dict[str, Any]] = {}
            for k, v in obj.items():
                sid = str(k)
                if isinstance(v, dict):
                    out2[sid] = dict(v)
                else:
                    # Legacy: value was a string (e.g. display name) or other primitive
                    out2[sid] = {
                        "name": v if isinstance(v, str) else str(v),
                        "first_seen": None,
                        "last_seen": None,
                        "count": 0,
                        "sources": [],
                    }
            return out2
        # Unknown shape
        return {}

    @staticmethod
    def load(path: Path) -> "ObservedDb":
        if not path.exists():
            return ObservedDb(cars={}, tracks={})
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            cars = ObservedDb._normalize_table(obj.get("cars", {}))
            tracks = ObservedDb._normalize_table(obj.get("tracks", {}))
            return ObservedDb(cars=cars, tracks=tracks)
        except Exception:
            return ObservedDb(cars={}, tracks={})

    def merge_ids(
        self,
        *,
        cars: Set[str],
        tracks: Set[str],
        sources: Optional[Dict[str, Set[str]]] = None,
    ) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        sources = sources or {}

        def ensure_record(kind: str, _id: str, rec_any: Any) -> Dict[str, Any]:
            """Coerce legacy record shapes into a mutable dict."""
            if rec_any is None:
                return {
                    "first_seen": today,
                    "last_seen": today,
                    "count": 0,
                    "sources": [],
                }
            if isinstance(rec_any, dict):
                return rec_any
            # Legacy: string or primitive
            d: Dict[str, Any] = {
                "name": rec_any if isinstance(rec_any, str) else str(rec_any),
                "first_seen": today,
                "last_seen": today,
                "count": 0,
                "sources": [],
            }
            return d

        def upsert(tbl: Dict[str, Dict[str, Any]], kind: str, _id: str) -> None:
            rec_any = tbl.get(_id)
            rec = ensure_record(kind, _id, rec_any)
            if rec_any is None or not isinstance(rec_any, dict):
                # Newly created or migrated
                rec.setdefault("first_seen", today)
            if not rec.get("first_seen"):
                rec["first_seen"] = today
            rec["last_seen"] = today
            rec["count"] = int(rec.get("count", 0)) + 1

            merged = set(rec.get("sources", []) or []) | set(sources.get(f"{kind}:{_id}", set()))
            rec["sources"] = sorted(list(merged))

            tbl[_id] = rec

        for cid in cars:
            upsert(self.cars, "cars", str(cid))
        for tid in tracks:
            upsert(self.tracks, "tracks", str(tid))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        obj = {"cars": self.cars, "tracks": self.tracks}
        atomic_write_json(path, obj, encoding="utf-8", indent=2, ensure_ascii=False)
