from __future__ import annotations

import json
from pathlib import Path

from .fs_atomic import atomic_write_bytes

from typing import Any, Dict, List, Tuple, Set

def read_text_any(path: Path) -> str:
    """Read a text file that may be UTF-8 or UTF-16LE.

    Our extracted JSON block files are UTF-16LE; manifest.json and most config
    files are UTF-8. Prefer UTF-8 unless the byte pattern strongly indicates
    UTF-16LE (BOM or high NUL-byte ratio).
    """
    b = path.read_bytes()

    # UTF-16LE BOM
    if b.startswith(b"\xff\xfe"):
        try:
            return b.decode("utf-16le")
        except UnicodeDecodeError:
            pass

    # Heuristic: lots of NUL bytes suggests UTF-16LE
    nul = b.count(b"\x00")
    if nul > max(16, len(b) // 10):
        try:
            return b.decode("utf-16le")
        except UnicodeDecodeError:
            pass

    # Prefer UTF-8
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback to UTF-16LE
        try:
            return b.decode("utf-16le")
        except UnicodeDecodeError:
            return b.decode("utf-8", errors="replace")

def write_text_utf16le(path: Path, s: str) -> None:
    """Write text as UTF-16LE (no newlines translation) using an atomic write."""
    data = s.encode("utf-16le")
    atomic_write_bytes(path, data)

def try_load_json(text: str) -> Any:
    # tolerate UTF-8 BOM
    if text and text[0] == "\ufeff":
        text = text[1:]
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


def collect_keys_recursive(obj: Any, out: Set[str]) -> None:
    """Collect all dict keys (string keys) recursively."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                out.add(k)
            collect_keys_recursive(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_keys_recursive(v, out)


def set_or_create_root_keys(obj: Any, updates: Dict[str, Any]) -> int:
    """Ensure keys exist at the root dict; set them to provided values.
    Returns number of assignments performed (including overwrites).
    """
    if not isinstance(obj, dict):
        return 0
    n = 0
    for k, v in updates.items():
        obj[k] = v
        n += 1
    return n


def json_path_parse(path: str) -> List[Any]:
    """Parse a simple JSONPath-like string used by our UI: $ .key [index]"""
    if not path or path == "$":
        return []
    if not path.startswith("$"):
        raise ValueError("Path must start with '$'")
    i = 1
    tokens: List[Any] = []
    while i < len(path):
        if path[i] == '.':
            i += 1
            start = i
            while i < len(path) and path[i] not in '.[':
                i += 1
            key = path[start:i]
            if not key:
                raise ValueError(f"Bad path near {path[start:]}")
            tokens.append(key)
        elif path[i] == '[':
            i += 1
            start = i
            while i < len(path) and path[i] != ']':
                i += 1
            if i >= len(path) or path[i] != ']':
                raise ValueError("Unclosed [")
            idx_s = path[start:i]
            i += 1
            try:
                idx = int(idx_s)
            except Exception as e:
                raise ValueError(f"Bad index: {idx_s}") from e
            tokens.append(idx)
        else:
            raise ValueError(f"Unexpected char in path: {path[i]}")
    return tokens


def json_path_get(obj: Any, path: str) -> Any:
    cur = obj
    for t in json_path_parse(path):
        if isinstance(t, int):
            cur = cur[t]
        else:
            cur = cur[t]
    return cur


def json_path_set(obj: Any, path: str, value: Any) -> None:
    toks = json_path_parse(path)
    if not toks:
        raise ValueError("Cannot set root '$' directly")
    cur = obj
    for t in toks[:-1]:
        cur = cur[t] if isinstance(t, int) else cur[t]
    last = toks[-1]
    if isinstance(last, int):
        cur[last] = value
    else:
        cur[last] = value

def set_first_keys(obj: Any, updates: Dict[str, Any]) -> int:
    """Set only the first occurrence of each key in `updates`, depth-first.

    This avoids overwriting multiple copies of the same logical field that may
    exist in different sub-objects (a common cause of 'reverts' when the game
    reads a different container).
    """
    remaining = set(updates.keys())
    changed = 0

    def walk(x: Any) -> None:
        nonlocal changed, remaining
        if not remaining:
            return
        if isinstance(x, dict):
            # Update keys at this level first
            for k in list(x.keys()):
                if k in remaining:
                    x[k] = updates[k]
                    remaining.remove(k)
                    changed += 1
                    if not remaining:
                        return
            # Recurse into values
            for v in x.values():
                walk(v)
                if not remaining:
                    return
        elif isinstance(x, list):
            for v in x:
                walk(v)
                if not remaining:
                    return

    walk(obj)
    return changed
