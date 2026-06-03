"""
Reads active forecast files and returns the macro bias for a symbol.

A forecast is a `forecasts/*.md` file whose front matter lists per-instrument
bias as `direction [strength] [level]`:

    instruments:
      EUR/USD: -1                 # bare direction (legacy) → strength 1.0, FILTER
      XAU/USD: 0 0.0 LOCK         # block all new entries for the symbol
      BTC/USD: -1 0.5 PARAMETERS  # soft: only shrinks opposed trades

direction: 1 bullish, -1 bearish, 0 no direction
strength:  0..1 conviction (default 1.0)
level:     FILTER | PARAMETERS | LOCK (default FILTER)

Only forecasts with status "активный" inside their date window apply. When
several active forecasts name the same symbol, a manual file wins over an
auto-generated one (`origin: auto`), then the stronger level wins.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DIR = Path(__file__).parent

VALID_LEVELS = {"FILTER", "PARAMETERS", "LOCK"}
_LEVEL_RANK = {"LOCK": 3, "FILTER": 2, "PARAMETERS": 1}


@dataclass(frozen=True)
class MacroBias:
    direction: int      # 1 bullish, -1 bearish, 0 no direction
    strength: float     # 0..1 conviction
    level: str          # FILTER | PARAMETERS | LOCK
    source: str         # forecast file name, for logging


def get_macro_bias(symbol: str, today: date | None = None) -> MacroBias | None:
    """Strongest active macro bias for the symbol, or None if none applies."""
    if today is None:
        today = date.today()

    candidates: list[tuple[int, int, MacroBias]] = []
    for path in _DIR.glob("*.md"):
        meta = _parse_front_matter(path)
        if not meta or meta.get("status") != "активный":
            continue

        start = _parse_date(meta.get("period_start", ""))
        end   = _parse_date(meta.get("period_end", ""))
        if start is None or end is None or not (start <= today <= end):
            continue

        raw = meta.get("instruments", {}).get(symbol)
        if raw is None:
            continue

        mb = _parse_instrument(raw, source=path.name)
        manual = 0 if meta.get("origin", "manual") == "manual" else 1
        candidates.append((manual, -_LEVEL_RANK.get(mb.level, 0), mb))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))   # manual first, then stronger level
    return candidates[0][2]


def get_bias(symbol: str, today: date | None = None) -> int:
    """Backward-compatible direction only (1 / -1 / 0)."""
    mb = get_macro_bias(symbol, today)
    return mb.direction if mb else 0


def _parse_instrument(raw, source: str) -> MacroBias:
    parts = str(raw).split()
    try:
        direction = int(float(parts[0]))
    except (ValueError, IndexError):
        direction = 0
    strength = 1.0
    if len(parts) > 1:
        try:
            strength = float(parts[1])
        except ValueError:
            pass
    strength = max(0.0, min(1.0, strength))
    level = parts[2].upper() if len(parts) > 2 else "FILTER"
    if level not in VALID_LEVELS:
        level = "FILTER"
    return MacroBias(direction, strength, level, source)


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
