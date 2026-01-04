from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

BlockKind = Literal["text", "binary", "raw_gz"]

@dataclass
class BlockInfo:
    index: int
    offset: int
    stored_len: int
    gzip_mtime: int
    out_name: str     # relative path under extracted_dir
    kind: BlockKind
    note: str = ""
