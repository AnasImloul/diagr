import unicodedata
from functools import cache

from .metrics import WIDTHS

FALLBACK = 0.62


@cache
def _advance(ch: str, weight: int) -> float:
    """A character's width per 1000 units of font size: from the table, or as wide as a square for the wide characters
    of CJK and emoji, nothing for a combining mark, and FALLBACK for anything else the table lacks."""
    table = WIDTHS[weight]
    if ch in table:
        return table[ch]
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1000
    return FALLBACK * 1000


def text_width(s: str, size: float, weight: int = 400) -> float:
    w = 600 if weight >= 600 else 400
    return sum(_advance(ch, w) for ch in s) * size / 1000
