from __future__ import annotations

import json
import hashlib
import struct
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import List, Tuple

from .model import BlockInfo
from .memory_codec import b64_decode_gz, gzip_mtime, gunzip

H4SI = b"H4sI"
BASE64_ALLOWED = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
BASE64_WS = set(b" \t\r\n")

FALLEN_MAGIC = b"FALLEN"
FALLEN_SENTINEL = b"FALLEN\x00\x02"


def _sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _sha1_file(p: Path) -> str:
    return _sha1_bytes(p.read_bytes())


def scan_fallen_segments(data: bytes) -> List[Tuple[int, int, bytes]]:
    """Return list of (payload_offset, stored_len, payload_bytes) for FALLEN-container saves.

    Observed format (Save Wizard style):
      - File starts with b"FALLEN"
      - A 24-byte header, then a table of N entries (16 bytes each)
      - Each entry includes (id, type, length, payload_offset)
      - The payload is preceded by an 8-byte marker of the form b"FALLEN\x00X"
        where X appears to indicate marker type:
          - X == 0x02 : primary UTF-16LE JSON-ish segment (what we extract/edit)
          - X == 0x00 : auxiliary ASCII-ish tail chunks embedded inside some segments

    For robustness, we prefer the header table when it parses cleanly, and fall back to
    sentinel scanning (b"FALLEN\x00\x02") if the table is unavailable.
    """
    segs: List[Tuple[int, int, bytes]] = []
    if not data.startswith(FALLEN_MAGIC):
        return segs

    # --- Try table-driven parse (preferred) ---
    try:
        if len(data) >= 24:
            base_len = struct.unpack_from("<I", data, 8)[0]
            entry_count = struct.unpack_from("<I", data, 16)[0]

            # Basic sanity: base_len should be at least 24 and table must fit in file.
            if 24 <= base_len <= 0x10000 and entry_count <= 0x10000:
                table_end = base_len + entry_count * 16
                if table_end <= len(data) and base_len >= 24:
                    for i in range(entry_count):
                        off = base_len + i * 16
                        _id, _typ, seg_len, payload_off = struct.unpack_from("<IIII", data, off)
                        if payload_off == 0 or seg_len == 0:
                            continue
                        if payload_off + seg_len > len(data) or payload_off < 8:
                            continue
                        marker = data[payload_off - 8 : payload_off]
                        # Only expose primary 0x02 segments as editable blocks.
                        if marker == FALLEN_SENTINEL:
                            segs.append((payload_off, seg_len, data[payload_off : payload_off + seg_len]))
                    if segs:
                        return segs
    except Exception:
        pass

    # --- Fallback: scan by sentinel delimiters ---
    positions: List[int] = []
    pos = 0
    while True:
        off = data.find(FALLEN_SENTINEL, pos)
        if off < 0:
            break
        positions.append(off)
        pos = off + len(FALLEN_SENTINEL)

    for i, off in enumerate(positions):
        start = off + len(FALLEN_SENTINEL)
        end = positions[i + 1] if i + 1 < len(positions) else len(data)
        stored_len = end - start
        segs.append((start, stored_len, data[start:end]))
    return segs

    positions: List[int] = []
    pos = 0
    while True:
        off = data.find(FALLEN_SENTINEL, pos)
        if off < 0:
            break
        positions.append(off)
        pos = off + len(FALLEN_SENTINEL)

    for i, off in enumerate(positions):
        start = off + len(FALLEN_SENTINEL)
        end = positions[i + 1] if i + 1 < len(positions) else len(data)
        stored_len = end - start
        segs.append((start, stored_len, data[start:end]))
    return segs


def _is_b64_region_byte(b: int) -> bool:
    return b in BASE64_ALLOWED or b in BASE64_WS


def scan_blocks(data: bytes) -> List[Tuple[int, int, bytes]]:
    """Scan for base64(gzip) regions anchored by the H4sI prefix."""
    blocks: List[Tuple[int, int, bytes]] = []
    pos = 0
    while True:
        off = data.find(H4SI, pos)
        if off < 0:
            break
        j = off
        while j < len(data) and _is_b64_region_byte(data[j]):
            j += 1
        stored = data[off:j]
        stripped = b"".join(stored.split())
        if len(stripped) >= 16:
            blocks.append((off, len(stored), stripped))
        pos = off + 4
    return blocks


def _write_text_utf16le(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-16le", newline="")


def _fallen_trim_json_text(payload_bytes: bytes) -> tuple[str, int]:
    """Decode payload bytes as UTF-16LE, and trim to the last plausible JSON terminator.

    Returns (trimmed_text, payload_prefix_len_bytes).

    payload_prefix_len_bytes is the number of bytes reserved for the JSON-ish prefix,
    allowing us to preserve any trailing bytes that Save Wizard / the game may have left
    behind in the segment.

    Some observed segments embed auxiliary data blocks starting with markers like
    b"FALLEN\x00\x00". In those cases, we cap the editable prefix at the first embedded
    marker to avoid overwriting the tail when the user edits the JSON.
    """
    txt_all = payload_bytes.decode("utf-16le", errors="ignore")

    # Detect embedded markers in raw bytes that indicate the start of a tail region.
    marker_candidates = (
        b"FALLEN\x00\x00",
        b"FALLEN\x00\x01",
        b"FALLEN\x00\x03",
    )
    marker_pos = -1
    for mk in marker_candidates:
        p = payload_bytes.find(mk)
        if p != -1 and (marker_pos == -1 or p < marker_pos):
            marker_pos = p

    rbrace = txt_all.rfind("}")
    rbrack = txt_all.rfind("]")
    endj = max(rbrace, rbrack)

    if endj == -1:
        trimmed = txt_all.rstrip("\x00").strip()
        prefix_len = 0
        if marker_pos > 0:
            prefix_len = marker_pos
        if prefix_len % 2 == 1:
            prefix_len -= 1
        return trimmed, prefix_len

    trimmed = txt_all[: endj + 1].strip()
    prefix_len = min(len(payload_bytes), (endj + 1) * 2)

    # If an embedded marker appears before the computed JSON end, clamp to it.
    if marker_pos > 0 and marker_pos < prefix_len:
        prefix_len = marker_pos

    if prefix_len % 2 == 1:
        prefix_len -= 1
    return trimmed, prefix_len


def extract(memory_dat: Path, out_dir: Path) -> Path:
    data = memory_dat.read_bytes()
    out_blocks = out_dir / "blocks"
    out_orig = out_dir / "orig_regions"

    # IMPORTANT: never merge blocks across extracts. Old blocks can cause
    # "saved but no change" symptoms if the repacker only writes blocks
    # referenced by the current manifest.
    if out_blocks.exists():
        shutil.rmtree(out_blocks, ignore_errors=True)
    if out_orig.exists():
        shutil.rmtree(out_orig, ignore_errors=True)
    out_blocks.mkdir(parents=True, exist_ok=True)
    out_orig.mkdir(parents=True, exist_ok=True)

    infos: List[BlockInfo] = []
    idx = 0

    # Two supported container formats:
    #  - "h4si": base64(gzip(utf-16le json)) regions inside a larger memory.dat
    #  - "fallen": Save Wizard-style container with FALLEN\x00\x02 sentinels delimiting UTF-16LE-ish segments
    container = "fallen" if data.startswith(FALLEN_MAGIC) else "h4si"

    container_info: dict = {}
    if container == "fallen":
        first = data.find(FALLEN_SENTINEL)
        if first >= 0:
            container_info["header_len"] = first
        container_info["sentinel_count"] = data.count(FALLEN_SENTINEL)


        # Parse and report the FALLEN header table when present (observed in Save Wizard "FALLEN" saves).
        try:
            if len(data) >= 24:
                base_len = struct.unpack_from("<I", data, 8)[0]
                version = struct.unpack_from("<I", data, 12)[0]
                entry_count = struct.unpack_from("<I", data, 16)[0]
                flags_be = struct.unpack_from(">I", data, 20)[0]
                flags_le = struct.unpack_from("<I", data, 20)[0]
                table_end = base_len + entry_count * 16
                if 24 <= base_len <= 0x10000 and entry_count <= 0x10000 and table_end <= len(data):
                    container_info["header_base_len"] = int(base_len)
                    container_info["version"] = int(version)
                    container_info["table_entry_count"] = int(entry_count)
                    # Field at +0x14 appears big-endian in observed samples; include both views for diagnostics.
                    container_info["flags_be"] = int(flags_be)
                    container_info["flags_le"] = int(flags_le)

                    # Count marker types referenced by the table (0x02 primary, 0x00 aux, etc.).
                    type_counts: dict[str, int] = {}
                    for i in range(entry_count):
                        off = base_len + i * 16
                        _id, _typ, seg_len, payload_off = struct.unpack_from("<IIII", data, off)
                        if payload_off < 8 or payload_off + seg_len > len(data) or seg_len == 0:
                            continue
                        marker = data[payload_off - 8 : payload_off]
                        key = marker.hex() if marker.startswith(FALLEN_MAGIC) else "unknown"
                        type_counts[key] = type_counts.get(key, 0) + 1
                    container_info["table_marker_counts"] = type_counts
        except Exception:
            pass

        seg_lens: List[int] = []
        json_ok = 0

        for off, stored_len, payload_bytes in scan_fallen_segments(data):
            seg_lens.append(stored_len)

            # Persist a copy of the original payload region for diagnostics/recovery.
            region_bytes = payload_bytes
            orig_name = f"orig_{idx:02d}_off_{off:08X}.bin"
            (out_orig / orig_name).write_bytes(region_bytes)

            txt, prefix_len = _fallen_trim_json_text(payload_bytes)

            # Pretty print JSON for readability when possible.
            ext = ".txt"
            note = "fallen_segment"
            try:
                obj = json.loads(txt)
                txt = json.dumps(obj, indent=2, ensure_ascii=False)
                ext = ".json"
                json_ok += 1
            except Exception:
                pass

            name = f"block_{idx:02d}_off_{off:08X}{ext}"
            out_path = out_blocks / name
            _write_text_utf16le(out_path, txt)

            infos.append(
                BlockInfo(
                    index=idx,
                    offset=off,
                    stored_len=stored_len,
                    gzip_mtime=0,
                    out_name=f"blocks/{name}",
                    kind="fallen_text",
                    note=note,
                    file_sha1=_sha1_file(out_path),
                    region_sha1=_sha1_bytes(region_bytes),
                    orig_region=f"orig_regions/{orig_name}",
                    payload_prefix_len=prefix_len,
                )
            )
            idx += 1

        container_info["segment_count"] = len(seg_lens)
        container_info["json_parse_ok"] = json_ok
        if seg_lens:
            container_info["segment_len_min"] = min(seg_lens)
            container_info["segment_len_max"] = max(seg_lens)
            container_info["segment_len_unique"] = len(set(seg_lens))

    else:
        for off, stored_len, b64_stripped in scan_blocks(data):
            gz = b64_decode_gz(b64_stripped)
            if not gz:
                continue
            mtime = gzip_mtime(gz)
            payload = gunzip(gz)
            if not payload:
                continue

            # Persist a copy of the original stored region (including whitespace).
            region_bytes = data[off : off + stored_len]
            orig_name = f"orig_{idx:02d}_off_{off:08X}.bin"
            (out_orig / orig_name).write_bytes(region_bytes)

            kind = "binary"
            note = ""
            txt = None
            try:
                txt = payload.decode("utf-16le")
                kind = "text"
            except Exception:
                pass

            if kind == "text" and txt is not None:
                ext = ".txt"
                try:
                    json.loads(txt)
                    ext = ".json"
                except Exception:
                    pass
                name = f"block_{idx:02d}_off_{off:08X}{ext}"
                out_path = out_blocks / name
                _write_text_utf16le(out_path, txt)
                file_sha1 = _sha1_file(out_path)
            else:
                name = f"block_{idx:02d}_off_{off:08X}.bin"
                out_path = out_blocks / name
                out_path.write_bytes(payload)
                file_sha1 = _sha1_file(out_path)

            infos.append(
                BlockInfo(
                    index=idx,
                    offset=off,
                    stored_len=stored_len,
                    gzip_mtime=mtime,
                    out_name=f"blocks/{name}",
                    kind=kind,  # type: ignore[arg-type]
                    note=note,
                    file_sha1=file_sha1,
                    region_sha1=_sha1_bytes(region_bytes),
                    orig_region=f"orig_regions/{orig_name}",
                    payload_prefix_len=0,
                )
            )
            idx += 1

    base_sig = hashlib.sha1(data).hexdigest()
    manifest = {
        "base_file": memory_dat.name,
        "file_size": len(data),
        "base_sig": base_sig,
        "container": container,
        "container_info": container_info,
        "blocks": [asdict(b) for b in infos],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
