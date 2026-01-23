#!/usr/bin/env python3
"""Fix Python source files that accidentally got saved with NUL bytes (often UTF-16LE).

Run:
    python tools/fix_null_bytes.py

It will rewrite affected *.py files as UTF-8 (no BOM) and keep a *.bak copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

def fix_file(p: Path) -> bool:
    b = p.read_bytes()
    if b.count(b"\x00") == 0:
        return False

    # Try UTF-16LE decode first (common when Notepad saves as Unicode)
    text = None
    try:
        text = b.decode("utf-16le")
    except Exception:
        # Fallback: remove NUL bytes (best effort)
        try:
            text = b.replace(b"\x00", b"").decode("utf-8", errors="replace")
        except Exception:
            return False

    bak = p.with_suffix(p.suffix + ".bak")
    if not bak.exists():
        bak.write_bytes(b)

    # Normalize line endings and write UTF-8
    p.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    return True

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    py_files = [p for p in root.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts]
    changed = 0
    for p in py_files:
        try:
            if fix_file(p):
                print(f"[fixed] {p.relative_to(root)}")
                changed += 1
        except Exception as e:
            print(f"[error] {p}: {e}")

    if changed == 0:
        print("No NUL-byte Python files found.")
    else:
        print(f"Fixed {changed} file(s).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
