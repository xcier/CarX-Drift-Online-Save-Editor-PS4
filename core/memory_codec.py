from __future__ import annotations

import base64
import binascii
import io
import struct
import zlib
from typing import Optional, Tuple

# We decode base64 segments which typically start with ASCII "H4sI" (gzip header when base64'd).
# In some saves, the stored region can contain concatenated base64 strings or trailing bytes.
# These helpers are intentionally tolerant and return the *first* valid gzip member payload.

def _try_b64_decode(s: bytes, validate: bool) -> Optional[bytes]:
    try:
        return base64.b64decode(s, validate=validate)
    except (binascii.Error, ValueError):
        return None

def _trim_after_padding(s: bytes) -> Optional[bytes]:
    """If base64 contains extra data after '=' padding, trim to the last plausible padded boundary."""
    # Try the common case where the segment ends with '=' or '=='
    last_eq = s.rfind(b"=")
    if last_eq < 0:
        return None
    # Try trimming at a few candidate boundaries near the end
    for end in range(len(s), max(last_eq + 1, len(s) - 96), -1):
        raw = _try_b64_decode(s[:end], validate=True)
        if raw is not None:
            return s[:end]
    return None

def b64_decode_gz(b64_stripped: bytes) -> Optional[bytes]:
    """Decode base64 to raw gzip bytes. Returns None if decoding fails."""
    s = b64_stripped

    # First attempt: strict decode (fast and safest).
    raw = _try_b64_decode(s, validate=True)
    if raw is None:
        # If we have excess after padding, trim and retry.
        trimmed = _trim_after_padding(s)
        if trimmed is not None:
            raw = _try_b64_decode(trimmed, validate=True)

    # Fallback: relaxed decode with padding fix.
    if raw is None:
        pad = (-len(s)) % 4
        if pad:
            s += b"=" * pad
        raw = _try_b64_decode(s, validate=False)

    if raw is None or len(raw) < 10:
        return None
    # gzip magic
    if raw[0:2] != b"\x1f\x8b":
        return None
    return raw

def gzip_mtime(gz: bytes) -> int:
    if len(gz) < 10 or gz[0:2] != b"\x1f\x8b":
        return 0
    return struct.unpack("<I", gz[4:8])[0]

def gunzip(gz: bytes) -> bytes:
    """Decompress the first gzip member and ignore trailing junk bytes."""
    # zlib with gzip headers; unused_data captures any trailing non-gzip bytes.
    d = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    out = d.decompress(gz)
    return out

def gzip_compress(payload: bytes, mtime: int, level: int = 9) -> bytes:
    import gzip
    bio = io.BytesIO()
    with gzip.GzipFile(fileobj=bio, mode="wb", compresslevel=level, mtime=mtime) as gf:
        gf.write(payload)
    return bio.getvalue()

def b64_encode(gz: bytes) -> bytes:
    return base64.b64encode(gz)
