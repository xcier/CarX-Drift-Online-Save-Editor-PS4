from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any, Optional

from .json_ops import (
    read_text_any,
    write_text_utf16le,
    try_load_json,
    dump_json_compact,
    set_all_keys,
    set_first_keys,
)

@dataclass
class BlockMatch:
    path: Path
    score: int
    present_keys: Set[str]

def _collect_keys(obj: Any, out: Set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                out.add(k)
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_keys(v, out)

def _score_block(obj: Any, update_keys: Set[str]) -> BlockMatch:
    present: Set[str] = set()
    _collect_keys(obj, present)
    score = sum(1 for k in update_keys if k in present)
    return score, present

def apply_updates_to_blocks(
    extracted_dir: Path,
    updates: Dict[str, object],
    *,
    target_best_only: bool = True,
    per_key_target: bool = True,
    create_missing_root: bool = False,
    update_all_occurrences: bool = True,
) -> Tuple[int, List[str], List[str]]:
    """
    Apply updates into extracted UTF-16LE JSON blocks.

    Behavior:
      - Builds a set of candidate blocks that parse as JSON.
      - Scores blocks by how many update keys they contain.
      - If per_key_target=True (recommended): chooses the best block per key and applies only that key there.
      - If create_missing_root=True: when a key is not found in any block, it is created at the root of the best block.

    Returns:
      (total_assignments, warnings, touched_files)
    """
    setter = set_all_keys if update_all_occurrences else set_first_keys

    warnings: List[str] = []
    touched: List[str] = []
    total_assignments = 0

    blocks_dir = extracted_dir / "blocks"
    if not blocks_dir.exists():
        return 0, ["Missing blocks/ directory; run extract first."], []

    update_keys = set(updates.keys())
    candidates: List[Tuple[Path, int, Set[str], Any]] = []

    # Load all extracted files; keep only those that parse as JSON.
    for p in sorted(blocks_dir.glob("*")):
        try:
            txt = read_text_any(p)
            obj = try_load_json(txt)
            if obj is None:
                continue
        except Exception:
            continue

        present: Set[str] = set()
        _collect_keys(obj, present)
        score = sum(1 for k in update_keys if k in present)
        if score > 0:
            candidates.append((p, score, present, obj))

    if not candidates:
        return 0, ["No JSON blocks contained any of the requested keys. The save may store fields under different names."], []

    # Sort by score desc, then by filename for stability.
    candidates.sort(key=lambda t: (-t[1], t[0].name))
    best_score = candidates[0][1]
    best = [c for c in candidates if c[1] == best_score]

    if best_score < len(update_keys):
        warnings.append(
            f"Best match score {best_score}/{len(update_keys)}. Some keys may live in other blocks; "
            f"per_key_target={'on' if per_key_target else 'off'}."
        )

    def _anchor_score(present: Set[str]) -> int:
        anchors = {
            "coins", "ratingPoints", "playerExp",
            "availableCars", "availableTracks", "availableProfiles",
            "m_items", "m_cars",
            "m_completedTasks", "m_slotLimitPerCar",
            "<quests>k__BackingField", "hasUpdatedQuests",
        }
        return sum(1 for a in anchors if a in present)

    # Decide which block(s) to touch.
    assignments_by_path: Dict[Path, Dict[str, Any]] = {}

    if per_key_target:
        for k, v in updates.items():
            cands = [c for c in candidates if k in c[2]]
            if not cands:
                if create_missing_root and best:
                    assignments_by_path.setdefault(best[0][0], {})[k] = v
                continue
            cands.sort(key=lambda t: (-t[1], -_anchor_score(t[2]), t[0].name))
            assignments_by_path.setdefault(cands[0][0], {})[k] = v
    else:
        targets = [best[0]] if target_best_only else best
        for p, score, present, obj in targets:
            assignments_by_path.setdefault(p, {}).update(updates)

    # Apply updates
    for p, kv in assignments_by_path.items():
        try:
            txt0 = read_text_any(p)
            obj0 = try_load_json(txt0)
            if obj0 is None:
                continue

            n = setter(obj0, kv)

            if create_missing_root and isinstance(obj0, dict):
                present_keys: Set[str] = set()
                _collect_keys(obj0, present_keys)
                for k, v in kv.items():
                    if k not in present_keys:
                        obj0[k] = v
                        n += 1

            if n <= 0:
                continue

            new_txt = dump_json_compact(obj0)
            write_text_utf16le(p, new_txt)
            total_assignments += n
            touched.append(str(p))
        except Exception:
            continue

    if total_assignments == 0:
        warnings.append("No assignments were performed even though matching keys were detected.")
    return total_assignments, warnings, touched