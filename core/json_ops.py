from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

def read_text_any(path: Path) -> str:
    b = path.read_bytes()
    if b.count(b"\x00") > max(8, len(b)//20):
        try:
            return b.decode("utf-16le")
        except UnicodeDecodeError:
            pass
    try:
        return b.decode("utf-16le")
    except UnicodeDecodeError:
        return b.decode("utf-8", errors="replace")

def write_text_utf16le(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-16le", newline="")

def try_load_json(text: str) -> Any:
    return json.loads(text)

def dump_json_compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def set_all_keys(obj: Any, updates: Dict[str, Any]) -> int:
    changed = 0
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in updates:
                obj[k] = updates[k]
                changed += 1
            changed += set_all_keys(obj[k], updates)
    elif isinstance(obj, list):
        for v in obj:
            changed += set_all_keys(v, updates)
    return changed


def find_first_keys(obj: Any, keys: List[str]) -> Dict[str, Any]:
    """Return a mapping of key->value for the *first* occurrence of each key found in obj.

    Traversal is depth-first. Only dict keys are considered. Once a key is found, it is not
    overwritten by later occurrences.

    This is used by the UI to populate form fields from the extracted save data.
    """
    remaining = set(keys)
    found: Dict[str, Any] = {}

    def _walk(x: Any) -> None:
        nonlocal remaining
        if not remaining:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                if k in remaining:
                    found[k] = v
                    remaining.remove(k)
                    if not remaining:
                        return
                _walk(v)
                if not remaining:
                    return
        elif isinstance(x, list):
            for v in x:
                _walk(v)
                if not remaining:
                    return

    _walk(obj)
    return found
