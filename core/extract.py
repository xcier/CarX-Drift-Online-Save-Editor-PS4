from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Tuple

from .model import BlockInfo
from .memory_codec import b64_decode_gz, gzip_mtime, gunzip

H4SI = b"H4sI"
BASE64_ALLOWED = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
BASE64_WS = set(b" \t\r\n")

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
    out_blocks.mkdir(parents=True, exist_ok=True)

    infos: List[BlockInfo] = []
    idx = 0
    for off, stored_len, b64_stripped in scan_blocks(data):
        gz = b64_decode_gz(b64_stripped)
        if not gz:
            continue

        mtime = gzip_mtime(gz)

        try:
            payload = gunzip(gz)
        except Exception as e:
            name = f"block_{idx:02d}_off_{off:08X}.raw_gz"
            (out_blocks / name).write_bytes(gz)
            infos.append(BlockInfo(idx, off, stored_len, mtime, f"blocks/{name}", "raw_gz", f"gunzip failed: {e}"))
            idx += 1
            continue

        # Try UTF-16LE text first
        kind = "binary"
        note = ""
        try:
            txt = payload.decode("utf-16le")
            kind = "text"
        except UnicodeDecodeError:
            txt = None

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

    manifest = {
        "base_file": memory_dat.name,
        "file_size": len(data),
        "blocks": [asdict(b) for b in infos],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
