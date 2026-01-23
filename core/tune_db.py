from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write_json(path: Path, obj: object) -> None:
    """
    Atomically write JSON to disk (temp file in same directory, then replace).
    This avoids partial/corrupt JSON if the process is interrupted mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
    os.replace(tmp, path)


@dataclass
class TuneInfo:
    """Human-friendly metadata for a tune ID."""
    name: str = ""
    cars: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""


@dataclass
class TuneDb:
    """
    Persistent database for the *tune id* (the middle number in keys like 142_977_swap_2jz).

    File format (tunes_db.json):
    {
      "tunes": {
        "977": {"name":"...", "cars":["142"], "first_seen":"...", "last_seen":"..."},
        ...
      },
      "cars": {
        "142": ["977","199",...]
      }
    }
    """
    path: Path
    tunes: Dict[str, TuneInfo] = field(default_factory=dict)
    cars: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "TuneDb":
        path = Path(path)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                tunes_raw = raw.get("tunes", {}) or {}
                cars_raw = raw.get("cars", {}) or {}
                tunes: Dict[str, TuneInfo] = {}
                for tid, info in tunes_raw.items():
                    if not isinstance(info, dict):
                        continue
                    tunes[str(tid)] = TuneInfo(
                        name=str(info.get("name", "") or ""),
                        cars=[str(x) for x in (info.get("cars") or [])],
                        first_seen=str(info.get("first_seen", "") or ""),
                        last_seen=str(info.get("last_seen", "") or ""),
                    )
                cars: Dict[str, List[str]] = {}
                for cid, tlist in cars_raw.items():
                    if not isinstance(tlist, list):
                        continue
                    cars[str(cid)] = [str(x) for x in tlist]
                return cls(path=path, tunes=tunes, cars=cars)
            except Exception:
                # If the file is corrupt, keep a fresh DB in-memory; caller can resave.
                return cls(path=path)
        return cls(path=path)

    def save(self) -> None:
        payload = {
            "tunes": {
                tid: {
                    "name": info.name,
                    "cars": sorted(set(info.cars), key=_safe_int),
                    "first_seen": info.first_seen,
                    "last_seen": info.last_seen,
                }
                for tid, info in self.tunes.items()
            },
            "cars": {
                cid: sorted(set(tlist), key=_safe_int)
                for cid, tlist in self.cars.items()
            },
        }
        _atomic_write_json(self.path, payload)

    def observe(self, car_id: str, tune_id: str) -> None:
        car_id = str(car_id).strip()
        tune_id = str(tune_id).strip()
        if not car_id or not tune_id:
            return

        now = _utc_now_iso()

        # per-tune record
        info = self.tunes.get(tune_id)
        if info is None:
            info = TuneInfo(name="", cars=[car_id], first_seen=now, last_seen=now)
            self.tunes[tune_id] = info
        else:
            if car_id not in info.cars:
                info.cars.append(car_id)
            if not info.first_seen:
                info.first_seen = now
            info.last_seen = now

        # per-car index
        tlist = self.cars.get(car_id)
        if tlist is None:
            self.cars[car_id] = [tune_id]
        else:
            if tune_id not in tlist:
                tlist.append(tune_id)

    def tune_name(self, tune_id: str) -> str:
        t = self.tunes.get(str(tune_id))
        if not t:
            return ""
        return t.name.strip()

    def set_tune_name(self, tune_id: str, name: str) -> None:
        tune_id = str(tune_id).strip()
        if not tune_id:
            return
        info = self.tunes.get(tune_id)
        if info is None:
            info = TuneInfo(name=name.strip())
            self.tunes[tune_id] = info
        else:
            info.name = name.strip()
        now = _utc_now_iso()
        if not info.first_seen:
            info.first_seen = now
        info.last_seen = now

    def tunes_for_car(self, car_id: str) -> List[str]:
        return sorted(self.cars.get(str(car_id), []) or [], key=_safe_int)

    def all_car_ids(self) -> List[str]:
        return sorted(self.cars.keys(), key=_safe_int)

    def all_tune_ids(self) -> List[str]:
        return sorted(self.tunes.keys(), key=_safe_int)


def _safe_int(s: str) -> int:
    try:
        return int(str(s))
    except Exception:
        return 10**18
