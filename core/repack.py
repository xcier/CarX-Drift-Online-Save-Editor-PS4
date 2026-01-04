from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from .model import BlockInfo
from .json_ops import read_text_any
from .memory_codec import gzip_compress, b64_encode

def repack(base_memory_dat: Path, extracted_dir: Path, out_memory_dat: Path) -> Tuple[int, int, List[str], Path]:
    manifest_path = extracted_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    blocks = [BlockInfo(**b) for b in manifest["blocks"]]

    base = bytearray(base_memory_dat.read_bytes())
    ok = 0
    fail = 0
    warnings: List[str] = []

    report_lines: List[str] = []
    report_lines.append(f"Base: {base_memory_dat.name} ({len(base)} bytes)")
    report_lines.append(f"Extracted: {extracted_dir}")
    report_lines.append(f"Output: {out_memory_dat}")
    report_lines.append("")

    for bi in blocks:
        p = extracted_dir / bi.out_name
        if not p.exists():
            report_lines.append(f"[SKIP] missing {bi.out_name}")
            continue

        if bi.kind == "raw_gz":
            gz = p.read_bytes()
            new_b64 = b64_encode(gz)
        elif bi.kind == "binary":
            payload = p.read_bytes()
            gz = gzip_compress(payload, bi.gzip_mtime)
            new_b64 = b64_encode(gz)
        else:
            txt = read_text_any(p)
            payload = txt.encode("utf-16le")
            gz = gzip_compress(payload, bi.gzip_mtime)
            new_b64 = b64_encode(gz)

        if len(new_b64) > bi.stored_len:
            fail += 1
            msg = (f"Block {bi.index:02d} @0x{bi.offset:08X} too large: "
                   f"{len(new_b64)} > {bi.stored_len} ({bi.out_name})")
            warnings.append(msg)
            report_lines.append(f"[FAIL] {msg}")
            continue

        pad = bi.stored_len - len(new_b64)
        region = new_b64 + (b" " * pad) if pad else new_b64
        base[bi.offset: bi.offset + bi.stored_len] = region

        ok += 1
        report_lines.append(f"[OK] block {bi.index:02d} @0x{bi.offset:08X}: wrote {len(new_b64)}, padded {pad}")

    out_memory_dat.write_bytes(bytes(base))
    report_path = out_memory_dat.with_suffix(out_memory_dat.suffix + ".rebuild_report.txt")
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return ok, fail, warnings, report_path
