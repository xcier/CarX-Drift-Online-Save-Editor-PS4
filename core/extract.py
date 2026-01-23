from __future__ import annotations

import json
import hashlib
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

def scan_fallen_segments(data: bytes) -> List[Tuple[int, int, bytes]]:
    """Return list of (payload_offset, stored_len, payload_bytes) for FALLEN-container saves.

    The file contains multiple UTF-16LE JSON segments, each preceded by the sentinel
    bytes FALLEN\x00\x02. We treat the segment payload region as a fixed-size block.
    """
    segs: List[Tuple[int, int, bytes]] = []
    if not data.startswith(FALLEN_MAGIC):
        return segs
    # find all sentinels
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
        end = positions[i+1] if i + 1 < len(positions) else len(data)
        stored_len = end - start
        segs.append((start, stored_len, data[start:end]))
    return segs


def _is_b64_region_byte(b: int) -> bool:
    return b in BASE64_ALLOWED or b in BASE64_WS

def scan_blocks(data: bytes) -> List[Tuple[int, int, bytes]]:
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

def extract(memory_dat: Path, out_dir: Path) -> Path:
    data = memory_dat.read_bytes()
    out_blocks = out_dir / "blocks"

    # IMPORTANT: never merge blocks across extracts. Old blocks can cause
    # "saved but no change" symptoms if the repacker only writes blocks
    # referenced by the current manifest.
    if out_blocks.exists():
        shutil.rmtree(out_blocks, ignore_errors=True)
    out_blocks.mkdir(parents=True, exist_ok=True)

    infos: List[BlockInfo] = []
    idx = 0

    # Two supported container formats:
    #  - "h4si": fixed-size base64(gzip(utf-16le json)) regions inside a 32MB memory.dat
    #  - "fallen": SaveWizard-style container with FALLEN\x00\x02 sentinels delimiting UTF-16LE JSON segments
    container = "fallen" if data.startswith(FALLEN_MAGIC) else "h4si"

    if container == "fallen":
        for off, stored_len, payload_bytes in scan_fallen_segments(data):
            # Decode UTF-16LE segment and trim to the final closing brace.
            txt = payload_bytes.decode("utf-16le", errors="ignore")
            endj = txt.rfind("}")
            if endj != -1:
                txt = txt[: endj + 1]
            txt = txt.strip()

            # Pretty print JSON for readability when possible.
            ext = ".txt"
            note = "fallen_segment"
            try:
                obj = json.loads(txt)
                txt = json.dumps(obj, indent=2, ensure_ascii=False)
                ext = ".json"
            except Exception:
                pass

            name = f"block_{idx:02d}_off_{off:08X}{ext}"
            _write_text_utf16le(out_blocks / name, txt)
            infos.append(BlockInfo(idx, off, stored_len, 0, f"blocks/{name}", "fallen_text", note))
            idx += 1

    else:
        for off, stored_len, b64_stripped in scan_blocks(data):
            gz = b64_decode_gz(b64_stripped)
            if not gz:
                continue
            mtime = gzip_mtime(gz)
            payload = gunzip(gz)
            if not payload:
                continue

            kind = "binary"
            note = ""
            txt = None
            try:
                txt = payload.decode("utf-16le")
                kind = "text"
            except Exception:
                pass

            # If the decoded text looks like JSON, store a .json extension.
            if kind == "text" and txt is not None:
                ext = ".txt"
                try:
                    json.loads(txt)
                    ext = ".json"
                except Exception:
                    pass
                name = f"block_{idx:02d}_off_{off:08X}{ext}"
                _write_text_utf16le(out_blocks / name, txt)
                infos.append(BlockInfo(idx, off, stored_len, mtime, f"blocks/{name}", "text", note))
            else:
                name = f"block_{idx:02d}_off_{off:08X}.bin"
                (out_blocks / name).write_bytes(payload)
                infos.append(BlockInfo(idx, off, stored_len, mtime, f"blocks/{name}", "binary", note))
            idx += 1

    base_sig = hashlib.sha1(data).hexdigest()
    manifest = {
        "base_file": memory_dat.name,
        "file_size": len(data),
        "base_sig": base_sig,
        "container": container,
        "blocks": [asdict(b) for b in infos],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
