from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import re

from core.json_ops import read_text_any, try_load_json

_ID_RE = re.compile(r"^\d+$")

def _is_id_str(x: Any) -> bool:
    if isinstance(x, int):
        return x >= 0
    if isinstance(x, str):
        return bool(_ID_RE.match(x.strip()))
    return False

def _as_id_str(x: Any) -> Optional[str]:
    if isinstance(x, int):
        return str(x)
    if isinstance(x, str):
        s = x.strip()
        if _ID_RE.match(s):
            return s
    return None

def _walk(obj: Any) -> Iterable[Tuple[List[str], Any]]:
    stack: List[Tuple[List[str], Any]] = [([], obj)]
    while stack:
        path, cur = stack.pop()
        yield path, cur
        if isinstance(cur, dict):
            for k, v in cur.items():
                stack.append((path + [str(k)], v))
        elif isinstance(cur, list):
            for i, v in enumerate(cur):
                stack.append((path + [str(i)], v))

@dataclass
class ScanResult:
    observed_cars: Set[str]
    observed_tracks: Set[str]
    unlocked_cars: Set[str]
    unlocked_tracks: Set[str]
    owned_cars: Set[str]
    sources: Dict[str, Set[str]]

def scan_extracted_dir(extracted_dir: Path) -> ScanResult:
    blocks_dir = extracted_dir / "blocks"
    observed_cars: Set[str] = set()
    observed_tracks: Set[str] = set()
    unlocked_cars: Set[str] = set()
    unlocked_tracks: Set[str] = set()
    owned_cars: Set[str] = set()
    sources: Dict[str, Set[str]] = {}

    if not blocks_dir.exists():
        return ScanResult(observed_cars, observed_tracks, unlocked_cars, unlocked_tracks, owned_cars, sources)

    def tag(kind: str, _id: str, src: str) -> None:
        key = f"{kind}:{_id}"
        sources.setdefault(key, set()).add(src)

    alt_unlocked_cars: Optional[Set[str]] = None
    alt_unlocked_tracks: Optional[Set[str]] = None

    for p in sorted(blocks_dir.glob("*")):
        try:
            root = try_load_json(read_text_any(p))
            if root is None:
                continue
        except Exception:
            continue

        for path, val in _walk(root):
            if not path:
                continue
            k = path[-1].lower()

            if k in ("carid", "lastcarid"):
                sid = _as_id_str(val)
                if sid is not None:
                    observed_cars.add(sid)
                    tag("cars", sid, path[-1])

            if k in ("trackid", "lasttrackid"):
                sid = _as_id_str(val)
                if sid is not None:
                    observed_tracks.add(sid)
                    tag("tracks", sid, path[-1])

            if k in ("m_cars", "mcars") and isinstance(val, list):
                ids = {_as_id_str(x) for x in val}
                ids = {x for x in ids if x is not None}
                if ids:
                    owned_cars |= ids
                    observed_cars |= ids
                    for sid in ids:
                        tag("cars", sid, path[-1])

            if k == "availablecars" and isinstance(val, list):
                ids = {_as_id_str(x) for x in val}
                ids = {x for x in ids if x is not None}
                unlocked_cars |= ids
                observed_cars |= ids
                for sid in ids:
                    tag("cars", sid, path[-1])

            if k == "availabletracks" and isinstance(val, list):
                ids = {_as_id_str(x) for x in val}
                ids = {x for x in ids if x is not None}
                unlocked_tracks |= ids
                observed_tracks |= ids
                for sid in ids:
                    tag("tracks", sid, path[-1])

            if k == "carids" and isinstance(val, list):
                # Some CarX saves store unlock lists as carIds/trackIds
                ids = {_as_id_str(x) for x in val}
                ids = {x for x in ids if x is not None}
                unlocked_cars |= ids
                observed_cars |= ids
                for sid in ids:
                    tag("cars", sid, path[-1])

            if k == "trackids" and isinstance(val, list):
                ids = {_as_id_str(x) for x in val}
                ids = {x for x in ids if x is not None}
                unlocked_tracks |= ids
                observed_tracks |= ids
                for sid in ids:
                    tag("tracks", sid, path[-1])


            if isinstance(val, list) and val and all(_is_id_str(x) for x in val):
                if ("avail" in k or "unlock" in k) and "car" in k and k != "availablecars":
                    ids = {_as_id_str(x) for x in val}
                    ids = {x for x in ids if x is not None}
                    if ids:
                        alt_unlocked_cars = ids if alt_unlocked_cars is None else (alt_unlocked_cars | ids)
                        for sid in ids:
                            tag("cars", sid, path[-1])

                if ("avail" in k or "unlock" in k) and "track" in k and k != "availabletracks":
                    ids = {_as_id_str(x) for x in val}
                    ids = {x for x in ids if x is not None}
                    if ids:
                        alt_unlocked_tracks = ids if alt_unlocked_tracks is None else (alt_unlocked_tracks | ids)
                        for sid in ids:
                            tag("tracks", sid, path[-1])

            if isinstance(val, list) and val and all(_is_id_str(x) for x in val):
                if "car" in k:
                    ids = {_as_id_str(x) for x in val}
                    ids = {x for x in ids if x is not None}
                    observed_cars |= ids
                    for sid in ids:
                        tag("cars", sid, path[-1])
                if "track" in k:
                    ids = {_as_id_str(x) for x in val}
                    ids = {x for x in ids if x is not None}
                    observed_tracks |= ids
                    for sid in ids:
                        tag("tracks", sid, path[-1])

    if not unlocked_cars and alt_unlocked_cars:
        unlocked_cars = alt_unlocked_cars
    if not unlocked_tracks and alt_unlocked_tracks:
        unlocked_tracks = alt_unlocked_tracks

    return ScanResult(observed_cars, observed_tracks, unlocked_cars, unlocked_tracks, owned_cars, sources)
