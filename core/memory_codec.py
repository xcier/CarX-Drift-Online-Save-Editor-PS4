from __future__ import annotations

import base64
import binascii
import gzip
import io
import struct
from typing import Optional

def b64_decode_gz(b64_stripped: bytes) -> Optional[bytes]:
    s = b64_stripped
    pad = (-len(s)) % 4
    if pad:
        s += b"=" * pad
    try:
        raw = base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        return None
    if len(raw) >= 2 and raw[0:2] == b"\x1f\x8b":
        return raw
    return None

def gzip_mtime(gz: bytes) -> int:
    if len(gz) < 10 or gz[0:2] != b"\x1f\x8b":
        return 0
    return struct.unpack("<I", gz[4:8])[0]

def gunzip(gz: bytes) -> bytes:
    return gzip.decompress(gz)

def gzip_compress(payload: bytes, mtime: int, level: int = 9) -> bytes:
    bio = io.BytesIO()
    with gzip.GzipFile(fileobj=bio, mode="wb", compresslevel=level, mtime=mtime) as gf:
        gf.write(payload)
    return bio.getvalue()

def b64_encode(gz: bytes) -> bytes:
    return base64.b64encode(gz)
