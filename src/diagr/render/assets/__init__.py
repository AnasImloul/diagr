"""The page's stylesheet and scripts, inlined into each HTML page."""

from __future__ import annotations

from pathlib import Path

FOLDER = Path(__file__).resolve().parent


def script(name: str) -> str:
    """The script file name, as an inline <script>."""
    return f"<script>\n{(FOLDER / name).read_text(encoding='utf-8')}</script>"
