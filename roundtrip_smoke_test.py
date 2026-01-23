from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from core.extract import extract
from core.repack import repack


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def first_diff_offset(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return -1


def main() -> int:
    ap = argparse.ArgumentParser(description="CarX Drift PS4 editor: Extract -> Repack round-trip smoke test.")
    ap.add_argument("memory_dat", type=Path, help="Path to memory.dat (or memory*.dat).")
    ap.add_argument("--work-dir", type=Path, default=None, help="Optional work directory (will be created if missing).")
    ap.add_argument("--keep", action="store_true", help="Keep the extracted work dir on success.")
    args = ap.parse_args()

    memory_dat: Path = args.memory_dat
    if not memory_dat.exists():
        raise SystemExit(f"Not found: {memory_dat}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = args.work_dir or (memory_dat.parent / f"_roundtrip_smoke_{ts}")
    extracted_dir = work_dir / "extracted"
    out_path = work_dir / f"{memory_dat.stem}_roundtrip{memory_dat.suffix}"

    work_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] Extracting -> {extracted_dir}")
    extract(memory_dat, extracted_dir)

    print(f"[2/3] Repacking -> {out_path}")
    ok, fail, warnings, report_path = repack(memory_dat, extracted_dir, out_path)

    print(f"[3/3] Verifying byte-level equality")
    a = memory_dat.read_bytes()
    b = out_path.read_bytes()

    ha = sha256(memory_dat)
    hb = sha256(out_path)
    diff = first_diff_offset(a, b)

    report_lines = []
    report_lines.append("Round-trip smoke test report")
    report_lines.append(f"Input: {memory_dat}")
    report_lines.append(f"Output: {out_path}")
    report_lines.append("")
    report_lines.append(f"Blocks written: {ok}")
    report_lines.append(f"Blocks failed: {fail}")
    report_lines.append(f"Rebuild report: {report_path}")
    report_lines.append("")
    report_lines.append(f"Input sha256:  {ha}")
    report_lines.append(f"Output sha256: {hb}")
    report_lines.append(f"First diff offset: {diff}")
    if diff >= 0:
        report_lines.append(f"Input byte @diff: 0x{a[diff]:02X}")
        report_lines.append(f"Output byte @diff: 0x{b[diff]:02X}")
    report_lines.append("")
    if warnings:
        report_lines.append("Warnings:")
        report_lines.extend([f"- {w}" for w in warnings[:50]])

    report_file = work_dir / "roundtrip_report.txt"
    report_file.write_text("\n".join(report_lines), encoding="utf-8")

    if diff == -1 and fail == 0:
        print("PASS: output matches input exactly.")
        print(f"Report: {report_file}")
        if not args.keep:
            shutil.rmtree(work_dir, ignore_errors=True)
        return 0

    print("FAIL: output differs from input (or some blocks failed).")
    print(f"Report: {report_file}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
