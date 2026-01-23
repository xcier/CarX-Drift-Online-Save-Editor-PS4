from __future__ import annotations

import json

from .app_paths import get_writable_data_dir
from .fs_atomic import atomic_write_json

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class IdDatabase:
    """Lightweight, user-editable ID database.

    This is intentionally **mutable** so all UI tabs can share a single
    instance and immediately reflect updates (e.g., when naming the current
    car in the Favorites tab).
    """

    key_labels: Dict[str, str]
    cars: Dict[str, str]
    tracks: Dict[str, str]

    # Path used for persistence when loaded via :meth:`load_default`.
    _path: Optional[Path] = None

    @classmethod
    def load_default(cls, base_dir: Path) -> "IdDatabase":
        """Load database from <base_dir>/data/id_database.json.

        base_dir should be the project root (folder containing app.py).
        """
        # Primary storage is a per-user writable directory (Qt AppData) unless
        # portable mode is enabled. However, for development (and for "drop-in"
        # updates like importing car names), we also keep a copy in <base_dir>/data.
        #
        # To avoid confusing "why didn't my updated id_database.json apply?" cases,
        # we *merge* the project-local database into the writable one on load.
        data_dir = get_writable_data_dir(base_dir)
        path = data_dir / "id_database.json"

        def _load_json(p: Path) -> dict:
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}

        raw_user = _load_json(path) if path.exists() else {}

        # Project-local "seed" database.
        seed_path = Path(base_dir) / "data" / "id_database.json"
        raw_seed = _load_json(seed_path) if seed_path.exists() else {}

        user_key_labels = dict(raw_user.get("key_labels", {}) or {})
        user_cars = dict(raw_user.get("cars", {}) or {})
        user_tracks = dict(raw_user.get("tracks", {}) or {})

        seed_key_labels = dict(raw_seed.get("key_labels", {}) or {})
        seed_cars = dict(raw_seed.get("cars", {}) or {})
        seed_tracks = dict(raw_seed.get("tracks", {}) or {})

        def _is_placeholder(val: str, kind: str, k: str) -> bool:
            # Our default fallbacks are "Car <id>" / "Track <id>".
            v = str(val)
            if kind == "car" and v == f"Car {k}":
                return True
            if kind == "track" and v == f"Track {k}":
                return True
            return False

        # Merge: seed fills missing keys, and can replace placeholder values.
        changed = False
        for k, v in seed_key_labels.items():
            if k not in user_key_labels and v:
                user_key_labels[k] = v
                changed = True
        for k, v in seed_cars.items():
            if not v:
                continue
            if (k not in user_cars) or _is_placeholder(user_cars.get(k, ""), "car", k):
                if user_cars.get(k) != v:
                    user_cars[k] = v
                    changed = True
        for k, v in seed_tracks.items():
            if not v:
                continue
            if (k not in user_tracks) or _is_placeholder(user_tracks.get(k, ""), "track", k):
                if user_tracks.get(k) != v:
                    user_tracks[k] = v
                    changed = True

        db = cls(key_labels=user_key_labels, cars=user_cars, tracks=user_tracks, _path=path)

        # If we merged anything, persist back to the writable DB so every tab
        # sees the updated mapping immediately.
        if changed:
            db.save()
        return db

    def save(self) -> None:
        """Persist the database back to ``data/id_database.json``.

        Non-fatal on IO errors (UI should not crash due to disk issues).
        """
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                self._path,
                {
                    "key_labels": self.key_labels or {},
                    "cars": self.cars or {},
                    "tracks": self.tracks or {},
                },
                encoding="utf-8",
                indent=2,
                ensure_ascii=False,
            )
        except Exception:
            pass

    def set_key_label(self, key: str, label: str) -> None:
        k = str(key)
        self.key_labels[k] = str(label)
        self.save()

    def set_car_label(self, car_id: Any, name: str) -> None:
        s = str(car_id)
        self.cars[s] = str(name)
        self.save()

    def set_track_label(self, track_id: Any, name: str) -> None:
        s = str(track_id)
        self.tracks[s] = str(name)
        self.save()

    def label_key(self, key: str) -> str:
        return self.key_labels.get(key, key)

    def label_car(self, car_id: Any) -> str:
        s = str(car_id)
        return self.cars.get(s, f"Car {s}")

    def label_track(self, track_id: Any) -> str:
        s = str(track_id)
        return self.tracks.get(s, f"Track {s}")
