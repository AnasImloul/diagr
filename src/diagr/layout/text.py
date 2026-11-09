from .metrics import WIDTHS

FALLBACK = 0.62


def text_width(s: str, size: float, weight: int = 400) -> float:
    table = WIDTHS[600 if weight >= 600 else 400]
    return sum(table.get(ch, FALLBACK * 1000) for ch in s) * size / 1000
