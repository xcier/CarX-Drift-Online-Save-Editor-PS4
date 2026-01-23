from __future__ import annotations

import json

from .app_paths import get_writable_data_dir
from .fs_atomic import atomic_write_json

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class FavoriteItem:
    category: str  # cars | tracks | engine_parts | keys
    value: str
    name: str = ""  # optional user label (separate from DB name)
    note: str = ""
    added_utc: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "value": self.value,
            "name": self.name,
            "note": self.note,
            "added_utc": self.added_utc,
        }

    @classmethod
    def from_json(cls, obj: Dict[str, Any]) -> "FavoriteItem":
        return cls(
            category=str(obj.get("category") or ""),
            value=str(obj.get("value") or ""),
            name=str(obj.get("name") or ""),
            note=str(obj.get("note") or ""),
            added_utc=str(obj.get("added_utc") or ""),
        )


class FavoritesDb:
    """Small, editor-side favorites store.

    Stored in ``data/favorites.json``. These favorites are not written into
    the game save; they are convenience shortcuts for the editor UI.
    """

    def __init__(self, path: Path, items: Optional[List[FavoriteItem]] = None):
        self.path = path
        self.items: List[FavoriteItem] = items or []

    @classmethod
    def load_default(cls, base_dir: Path) -> "FavoritesDb":
        data_dir = get_writable_data_dir(base_dir)
        path = data_dir / "favorites.json"
        if not path.exists():
            return cls(path, [])
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            arr = raw.get("items") if isinstance(raw, dict) else raw
            items: List[FavoriteItem] = []
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict):
                        items.append(FavoriteItem.from_json(it))
            return cls(path, items)
        except Exception:
            return cls(path, [])

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                self.path,
                {"items": [x.to_json() for x in self.items]},
                encoding="utf-8",
                indent=2,
                ensure_ascii=False,
            )
        except Exception:
            pass

    def add(self, category: str, value: Any, *, name: str = "", note: str = "") -> None:
        cat = str(category).strip() or "keys"
        val = str(value).strip()
        if not val:
            return
        # de-dupe
        for it in self.items:
            if it.category == cat and it.value == val:
                # update metadata
                if name:
                    it.name = name
                if note:
                    it.note = note
                self.save()
                return
        self.items.append(FavoriteItem(category=cat, value=val, name=str(name or ""), note=str(note or ""), added_utc=_utc_now_iso()))
        self.save()

    def remove(self, category: str, value: Any) -> None:
        cat = str(category).strip() or "keys"
        val = str(value).strip()
        self.items = [x for x in self.items if not (x.category == cat and x.value == val)]
        self.save()

    def clear(self) -> None:
        self.items = []
        self.save()
