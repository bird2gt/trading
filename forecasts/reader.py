"""
Reads active forecast files and returns per-symbol bias.

Bias: 1 = bullish, -1 = bearish, 0 = no active forecast.
Only forecasts with status "активный" affect trades.
"""

from __future__ import annotations
from datetime import date
from pathlib import Path

_DIR = Path(__file__).parent


def get_bias(symbol: str, today: date | None = None) -> int:
    if today is None:
        today = date.today()

    for path in _DIR.glob("*.md"):
        meta = _parse_front_matter(path)
        if not meta or meta.get("status") != "активный":
            continue

        start = _parse_date(meta.get("period_start", ""))
        end   = _parse_date(meta.get("period_end", ""))
        if start is None or end is None or not (start <= today <= end):
            continue

        bias = meta.get("instruments", {}).get(symbol)
        if bias is not None:
            return int(bias)

    return 0


def _parse_front_matter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None

    result: dict = {}
    current_key: str | None = None

    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and current_key and ":" in line:
            k, _, v = line.strip().partition(":")
            result[current_key][k.strip()] = v.strip()
        elif ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v:
                result[k] = v
                current_key = None
            else:
                result[k] = {}
                current_key = k

    return result


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None
