from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ParsedNumber:
    raw: str
    digits: str

    def as_int(self, default: int = 0) -> int:
        try:
            if self.digits == "":
                return default
            return int(self.digits)
        except Exception:
            return default


def digits_only(text: str) -> str:
    """Strip commas/underscores and keep only digits.

    CarX saves often store numeric values as digit-strings.
    """
    s = (text or "").strip().replace(",", "").replace("_", "")
    return "".join(ch for ch in s if ch.isdigit())


def parse_numeric_string(text: str, *, default: str = "") -> str:
    d = digits_only(text)
    return d if d != "" else default


def parse_int(text: str, *, default: int = 0) -> int:
    d = digits_only(text)
    if d == "":
        return default
    try:
        return int(d)
    except Exception:
        return default


def boolish_to_str(v: Any, *, default: str = "False") -> str:
    """Convert a variety of bool-like values to canonical "True"/"False" strings."""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return "True" if int(v) != 0 else "False"
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "1", "yes", "y", "on"}:
            return "True"
        if s in {"false", "0", "no", "n", "off"}:
            return "False"
    return default


def str_to_bool(v: Any, *, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return int(v) != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "1", "yes", "y", "on"}:
            return True
        if s in {"false", "0", "no", "n", "off"}:
            return False
    return default


def format_number_like(v: Any) -> str:
    """Human-friendly formatting for UI (comma separated) while preserving values."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not v.is_integer():
            return str(v)
        try:
            return f"{int(v):,}"
        except Exception:
            return str(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            try:
                return f"{int(s):,}"
            except Exception:
                return s
        return s
    return str(v)
