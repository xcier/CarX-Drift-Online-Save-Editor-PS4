from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# NOTE: BlockInfo is serialized into manifest.json.
# When adding fields, always provide defaults so older manifests still load.

BlockKind = Literal["text", "binary", "raw_gz", "fallen_text"]


@dataclass
class BlockInfo:
    # Core positioning / sizing
    index: int
    offset: int
    stored_len: int
    gzip_mtime: int

    # Relative path under extracted_dir
    out_name: str

    # How to interpret / rebuild the block
    kind: BlockKind

    # Optional metadata
    note: str = ""

    # SHA1 of the *extracted output file* (used to detect untouched blocks)
    file_sha1: str = ""

    # SHA1 of the original region bytes in base memory.dat (offset..offset+stored_len)
    region_sha1: str = ""

    # Relative path to a stored copy of the original region bytes (for diagnostics / recovery)
    orig_region: str = ""

    # FALLEN container only: bytes reserved for the JSON payload (tail is preserved)
    payload_prefix_len: int = 0
