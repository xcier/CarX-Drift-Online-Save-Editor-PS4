from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .app_paths import get_writable_data_dir
from .fs_atomic import atomic_write_json


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class TuneRecord:
    tune_id: str
    name: str = ""
    cars: Set[str] = None
    first_seen: str = ""
    last_seen: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "name": self.name or "",
            "cars": sorted(list(self.cars or set())),
            "first_seen": self.first_seen or "",
            "last_seen": self.last_seen or "",
        }

    @staticmethod
    def from_json(tune_id: str, obj: Dict[str, Any]) -> "TuneRecord":
        cars = set(str(x) for x in (obj.get("cars") or []))
        return TuneRecord(
            tune_id=str(tune_id),
            name=str(obj.get("name") or ""),
            cars=cars,
            first_seen=str(obj.get("first_seen") or ""),
            last_seen=str(obj.get("last_seen") or ""),
        )


class TunesDb:
    """Persistent database for 'tune IDs' (the middle number in CAR_TUNE_swap_ENGINE keys)."""

    def __init__(self, base_dir: Path, *, filename: str = "tunes_db.json") -> None:
        self._base_dir = Path(base_dir)
        self._data_dir = get_writable_data_dir(self._base_dir)
        self._path = self._data_dir / filename
        self._tunes: Dict[str, TuneRecord] = {}
        self._car_to_tunes: Dict[str, Set[str]] = {}
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        self._tunes = {}
        self._car_to_tunes = {}
        if not self._path.exists():
            return
        try:
            import json
            obj = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return

        tunes = obj.get("tunes") or {}
        cars = obj.get("cars") or {}

        for tid, rec in tunes.items():
            tr = TuneRecord.from_json(str(tid), rec if isinstance(rec, dict) else {})
            self._tunes[tr.tune_id] = tr

        for car, tids in cars.items():
            self._car_to_tunes[str(car)] = set(str(x) for x in (tids or []))

        # Ensure consistency
        for tid, tr in self._tunes.items():
            for car in (tr.cars or set()):
                self._car_to_tunes.setdefault(car, set()).add(tid)

    def save(self) -> None:
        out_tunes = {tid: tr.to_json() for tid, tr in sorted(self._tunes.items(), key=lambda kv: kv[0])}
        out_cars = {cid: sorted(list(tids)) for cid, tids in sorted(self._car_to_tunes.items(), key=lambda kv: kv[0])}
        obj = {"tunes": out_tunes, "cars": out_cars}
        atomic_write_json(self._path, obj, indent=2, ensure_ascii=False)

    def observe(self, car_id: str, tune_id: str) -> None:
        car_id = str(car_id)
        tune_id = str(tune_id)
        now = _utc_now_iso()

        tr = self._tunes.get(tune_id)
        if tr is None:
            tr = TuneRecord(tune_id=tune_id, name="", cars=set(), first_seen=now, last_seen=now)
            self._tunes[tune_id] = tr

        tr.cars = tr.cars or set()
        tr.cars.add(car_id)
        if not tr.first_seen:
            tr.first_seen = now
        tr.last_seen = now

        self._car_to_tunes.setdefault(car_id, set()).add(tune_id)

    def set_name(self, tune_id: str, name: str) -> None:
        tune_id = str(tune_id)
        tr = self._tunes.get(tune_id)
        if tr is None:
            tr = TuneRecord(tune_id=tune_id, name="", cars=set(), first_seen=_utc_now_iso(), last_seen=_utc_now_iso())
            self._tunes[tune_id] = tr
        tr.name = name or ""
        self.save()

    def get_name(self, tune_id: str) -> str:
        tr = self._tunes.get(str(tune_id))
        return tr.name if tr else ""

    def tunes_for_car(self, car_id: str) -> List[str]:
        tids = self._car_to_tunes.get(str(car_id)) or set()
        return sorted(list(tids), key=lambda x: int(x) if x.isdigit() else x)

    def all_cars(self) -> List[str]:
        return sorted(list(self._car_to_tunes.keys()), key=lambda x: int(x) if x.isdigit() else x)

    def all_tunes(self) -> List[str]:
        return sorted(list(self._tunes.keys()), key=lambda x: int(x) if x.isdigit() else x)
