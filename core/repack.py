from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .model import BlockInfo
from .json_ops import dump_json_compact, read_text_any, try_load_json
from .memory_codec import b64_encode, gzip_compress


@dataclass(frozen=True)
class PreflightItem:
    index: int
    offset: int
    stored_len: int
    new_len: int
    headroom: int
    out_name: str
    kind: str
    status: str  # OK / FAIL / SKIP / ERROR
    note: str = ""


def _build_new_b64_for_block(bi: BlockInfo, p: Path) -> bytes:
    """Return the base64 bytes to be written into the fixed-size region.

    - raw_gz: the file contains gzip member bytes already (we only base64 encode)
    - binary: the file contains raw payload bytes (we gzip+base64 encode)
    - text: the file contains UTF-16LE text (we minify JSON if possible, then gzip+base64 encode)
    """
    if bi.kind == "raw_gz":
        gz = p.read_bytes()
        return b64_encode(gz)

    if bi.kind == "binary":
        payload = p.read_bytes()
        gz = gzip_compress(payload, bi.gzip_mtime)
        return b64_encode(gz)

    # Default: text
    txt = read_text_any(p)

    # Opportunistically minify JSON to reduce size pressure on fixed regions.
    try:
        obj = try_load_json(txt)
        txt = dump_json_compact(obj)
    except Exception:
        pass

    payload = txt.encode("utf-16le")
    gz = gzip_compress(payload, bi.gzip_mtime)
    return b64_encode(gz)




def _load_manifest(extracted_dir: Path) -> Dict:
    """Load manifest.json using tolerant decoding."""
    manifest_path = extracted_dir / "manifest.json"
    txt = read_text_any(manifest_path)
    m = try_load_json(txt)
    if not isinstance(m, dict):
        raise ValueError("manifest.json did not parse as a JSON object")
    return m


def _build_new_bytes_for_fallen_block(bi: BlockInfo, p: Path) -> bytes:
    """Return UTF-16LE payload bytes for a FALLEN text segment."""
    txt = read_text_any(p)
    try:
        obj = try_load_json(txt)
        txt = dump_json_compact(obj)
    except Exception:
        pass
    return txt.encode("utf-16le")

def repack_preflight(base_memory_dat: Path, extracted_dir: Path, payloads_out: Optional[Dict[int, bytes]] = None) -> Tuple[List[PreflightItem], Path]:
    """Compute per-block headroom without writing an output file.

    Produces a report in extracted_dir and returns the parsed list for UI consumption.
    Supports both the standard H4sI base64(gzip) format and the FALLEN segment format.
    """
    manifest = _load_manifest(extracted_dir)
    container = str(manifest.get("container", "h4si"))
    blocks = [BlockInfo(**b) for b in manifest.get("blocks", [])]

    base_data = base_memory_dat.read_bytes()
    base_sig = hashlib.sha1(base_data).hexdigest()
    if manifest.get("base_sig") and manifest["base_sig"] != base_sig:
        raise ValueError("Base file does not match extracted manifest (signature mismatch). Please re-extract.")

    report_path = extracted_dir / "repack_preflight_report.txt"
    report_lines: List[str] = []
    report_lines.append(f"Base: {base_memory_dat.name} ({len(base_data)} bytes)")
    report_lines.append(f"Extracted: {extracted_dir}")
    report_lines.append(f"Container: {container}")
    report_lines.append("")

    items: List[PreflightItem] = []

    for bi in blocks:
        p = extracted_dir / bi.out_name
        if not p.exists():
            items.append(PreflightItem(bi.index, bi.offset, bi.stored_len, 0, bi.stored_len, bi.out_name, bi.kind, "SKIP", "missing extracted file"))
            continue
        try:
            if container == "fallen" or bi.kind == "fallen_text":
                new_payload = _build_new_bytes_for_fallen_block(bi, p)
                new_len = len(new_payload)
                if payloads_out is not None:
                    payloads_out[bi.index] = new_payload
            else:
                new_b64 = _build_new_b64_for_block(bi, p)
                new_len = len(new_b64)
                if payloads_out is not None:
                    payloads_out[bi.index] = new_b64
            headroom = bi.stored_len - new_len
            status = "OK" if headroom >= 0 else "FAIL"
            items.append(PreflightItem(bi.index, bi.offset, bi.stored_len, new_len, headroom, bi.out_name, bi.kind, status))
        except Exception as e:
            items.append(PreflightItem(bi.index, bi.offset, bi.stored_len, 0, bi.stored_len, bi.out_name, bi.kind, "ERROR", str(e)))

    worst = sorted([it for it in items if it.status in ("OK", "FAIL")], key=lambda x: x.headroom)[:12]
    fails = [it for it in items if it.status == "FAIL"]
    errors = [it for it in items if it.status == "ERROR"]

    report_lines.append(f"Blocks: {len(items)} | FAIL: {len(fails)} | ERROR: {len(errors)} | SKIP: {len([it for it in items if it.status=='SKIP'])}")
    report_lines.append("")
    report_lines.append("Worst headroom (lowest first):")
    if not worst:
        report_lines.append("  (none)")
    else:
        for it in worst:
            report_lines.append(f"  {it.index:02d} @0x{it.offset:08X}: new={it.new_len} stored={it.stored_len} headroom={it.headroom} [{it.status}] ({it.out_name})")

    report_lines.append("")
    if fails:
        report_lines.append("FAIL blocks:")
        for it in fails:
            report_lines.append(f"  {it.index:02d} @0x{it.offset:08X}: new={it.new_len} > stored={it.stored_len} by {-it.headroom} ({it.out_name})")
        report_lines.append("")
    if errors:
        report_lines.append("ERROR blocks:")
        for it in errors:
            report_lines.append(f"  {it.index:02d} @0x{it.offset:08X}: {it.error} ({it.out_name})")

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return items, report_path

def repack(base_memory_dat: Path, extracted_dir: Path, out_path: Path) -> Tuple[int, int, List[str], Path]:
    """Rebuild a patched save file from extracted blocks."""
    manifest = _load_manifest(extracted_dir)
    container = str(manifest.get("container", "h4si"))
    blocks = [BlockInfo(**b) for b in manifest.get("blocks", [])]

    base_data = base_memory_dat.read_bytes()
    base_sig = hashlib.sha1(base_data).hexdigest()
    if manifest.get("base_sig") and manifest["base_sig"] != base_sig:
        raise ValueError("Base file does not match extracted manifest (signature mismatch). Please re-extract.")

    out = bytearray(base_data)
    report_lines: List[str] = []
    warnings: List[str] = []
    ok = 0
    fail = 0

    report_lines.append(f"Base: {base_memory_dat.name} ({len(base_data)} bytes)")
    report_lines.append(f"Extracted: {extracted_dir}")
    report_lines.append(f"Output: {out_path}")
    report_lines.append(f"Container: {container}")
    report_lines.append("")

    for bi in blocks:
        p = extracted_dir / bi.out_name
        if not p.exists():
            report_lines.append(f"[SKIP] missing {bi.out_name}")
            continue

        try:
            if container == "fallen" or bi.kind == "fallen_text":
                payload = _build_new_bytes_for_fallen_block(bi, p)
                new_len = len(payload)
                if new_len > bi.stored_len:
                    fail += 1
                    msg = f"Block {bi.index:02d} @0x{bi.offset:08X} too large: {new_len} > {bi.stored_len} ({bi.out_name})"
                    warnings.append(msg)
                    report_lines.append(f"[FAIL] {msg}")
                    continue
                padded = payload + (b"\x00" * (bi.stored_len - new_len))
                out[bi.offset:bi.offset+bi.stored_len] = padded
                ok += 1
                report_lines.append(f"[OK] block {bi.index:02d} @0x{bi.offset:08X}: wrote {new_len}, padded {bi.stored_len-new_len}")
            else:
                new_b64 = _build_new_b64_for_block(bi, p)
                new_len = len(new_b64)
                if new_len > bi.stored_len:
                    fail += 1
                    msg = f"Block {bi.index:02d} @0x{bi.offset:08X} too large: {new_len} > {bi.stored_len} ({bi.out_name})"
                    warnings.append(msg)
                    report_lines.append(f"[FAIL] {msg}")
                    continue
                padded = new_b64 + (b" " * (bi.stored_len - new_len))
                out[bi.offset:bi.offset+bi.stored_len] = padded
                ok += 1
                report_lines.append(f"[OK] block {bi.index:02d} @0x{bi.offset:08X}: wrote {new_len}, padded {bi.stored_len-new_len}")

        except Exception as e:
            fail += 1
            msg = f"Block {bi.index:02d} @0x{bi.offset:08X} build failed: {e} ({bi.out_name})"
            warnings.append(msg)
            report_lines.append(f"[FAIL] {msg}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(out))

    report_path = out_path.with_suffix(out_path.suffix + ".rebuild_report.txt")
    report_lines.append("")
    report_lines.append(f"Blocks written: {ok}")
    report_lines.append(f"Blocks failed: {fail}")
    if warnings:
        report_lines.append("")
        report_lines.append("Warnings (first 12):")
        for w in warnings[:12]:
            report_lines.append(f"- {w}")

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return ok, fail, warnings, report_path
