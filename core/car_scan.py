from __future__ import annotations

"""High-signal scanners for CarX Drift PS4 extracted JSON blocks.

The editor already has a generic ID scanner (core.scan_ids) that finds carId,
availableCars, and m_cars. In real saves, however, ``m_cars`` can be empty even
when the player clearly has vehicles. Meanwhile, other structures (e.g.
``m_profilePerCar`` and ``m_carMileage``) reference most or all car IDs.

This module focuses on car *roster inference* and on extracting a few practical
per-car attributes that help build a clean, human-friendly ID database.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import re

from core.json_ops import read_text_any, try_load_json, find_first_keys
from core.scan_ids import scan_extracted_dir


@dataclass(frozen=True)
class CarRow:
    car_id: str
    owned: bool
    unlocked: bool
    mileage: Optional[float]
    profile_id: Optional[str]
    has_custom_setup: bool
    swap_count: int


_RE_CAR_PREFIX = re.compile(r"^(?P<car>\d+)_")
# Supports both formats observed in saves:
#   53_swap_2jz
#   9_35_swap_2jz
_RE_SWAP = re.compile(r"^(?P<car>\d+)(?:_(?P<tune>\d+))?_swap_(?P<engine>[A-Za-z0-9]+)$")


def _resolve_blocks_dir(work_dir: Path) -> Path:
    """Return the directory that contains blocks/.

    Supports both layouts:
      - <work_dir>/blocks
      - <work_dir>/extracted/blocks
    """
    if (work_dir / "blocks").exists():
        return work_dir / "blocks"
    if (work_dir / "extracted" / "blocks").exists():
        return work_dir / "extracted" / "blocks"
    return work_dir / "blocks"  # best-effort


def _iter_block_roots(blocks_dir: Path) -> Iterable[Tuple[str, Any]]:
    for p in sorted(blocks_dir.glob("*")):
        try:
            root = try_load_json(read_text_any(p))
        except Exception:
            continue
        if root is None:
            continue
        yield p.name, root


def scan_cars_from_workdir(work_dir: Path) -> List[CarRow]:
    """Scan the extracted blocks for a stable car roster and useful attributes."""

    blocks_dir = _resolve_blocks_dir(work_dir)
    if not blocks_dir.exists():
        return []

    # Reuse the generic scanner for owned/unlocked lists.
    generic = scan_extracted_dir(blocks_dir.parent)
    owned = set(generic.owned_cars or set())
    unlocked = set(generic.unlocked_cars or set())

    roster: Set[str] = set(generic.observed_cars or set())

    mileage_map: Dict[str, float] = {}
    profile_map: Dict[str, str] = {}
    custom_setup: Set[str] = set()
    swap_counts: Dict[str, int] = {}

    for _fname, root in _iter_block_roots(blocks_dir):
        if not isinstance(root, dict):
            continue

        # ------------------------ Per-car profile mapping (high-signal roster) ------------------------
        v = root.get("m_profilePerCar")
        if isinstance(v, dict):
            for car_id, prof_id in v.items():
                cid = str(car_id)
                if cid.isdigit():
                    roster.add(cid)
                    if prof_id is not None:
                        profile_map[cid] = str(prof_id)

        # ------------------------ Per-car mileage (another strong roster signal) ---------------------
        v = root.get("m_carMileage")
        if isinstance(v, dict):
            for car_id, miles in v.items():
                cid = str(car_id)
                if not cid.isdigit():
                    continue
                roster.add(cid)
                try:
                    mileage_map[cid] = float(str(miles))
                except Exception:
                    pass

        # ------------------------ Custom setups per car --------------------------------------------
        v = root.get("m_carsWithCustomSetups")
        if isinstance(v, dict):
            for car_id in v.keys():
                cid = str(car_id)
                if cid.isdigit():
                    roster.add(cid)
                    custom_setup.add(cid)

        # ------------------------ Engine swap keys (from m_items) -----------------------------------
        v = root.get("m_items")
        if isinstance(v, dict):
            for k in v.keys():
                ks = str(k)
                m = _RE_SWAP.match(ks)
                if not m:
                    # fallback: car prefix may still signal a car id, even if not a swap
                    m2 = _RE_CAR_PREFIX.match(ks)
                    if m2:
                        roster.add(m2.group("car"))
                    continue
                cid = m.group("car")
                roster.add(cid)
                swap_counts[cid] = swap_counts.get(cid, 0) + 1

        # ------------------------ lastCarId (current car) -------------------------------------------
        got = find_first_keys(root, ["lastCarId", "carId"])
        for key in ("lastCarId", "carId"):
            if key in got and got.get(key) is not None:
                cid = str(got.get(key))
                if cid.isdigit():
                    roster.add(cid)

    def sort_key(x: str) -> Tuple[int, str]:
        return (int(x), x) if x.isdigit() else (10**9, x)

    rows: List[CarRow] = []
    for cid in sorted(roster, key=sort_key):
        rows.append(
            CarRow(
                car_id=cid,
                owned=(cid in owned),
                unlocked=(cid in unlocked),
                mileage=mileage_map.get(cid),
                profile_id=profile_map.get(cid),
                has_custom_setup=(cid in custom_setup),
                swap_count=int(swap_counts.get(cid, 0)),
            )
        )
    return rows
