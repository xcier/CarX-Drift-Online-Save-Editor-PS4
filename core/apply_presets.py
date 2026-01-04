from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from .json_ops import read_text_any, write_text_utf16le, try_load_json, dump_json_compact, set_all_keys

def apply_updates_to_blocks(extracted_dir: Path, updates: Dict[str, object]) -> Tuple[int, List[str]]:
    warnings: List[str] = []
    total_assignments = 0

    blocks_dir = extracted_dir / "blocks"
    if not blocks_dir.exists():
        return 0, ["Missing blocks/ directory; run extract first."]

    for p in sorted(blocks_dir.glob("*.json")):
        try:
            txt = read_text_any(p)
            obj = try_load_json(txt)
        except Exception:
            continue

        n = set_all_keys(obj, updates)
        if n <= 0:
            continue

        new_txt = dump_json_compact(obj)
        write_text_utf16le(p, new_txt)
        total_assignments += n

    if total_assignments == 0:
        warnings.append("No matching keys found in any JSON blocks. The save may store these fields under different names.")
    return total_assignments, warnings
