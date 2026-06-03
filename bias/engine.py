"""
Macro-bias resolver: turns the macro forecast for a symbol (forecasts/*.md via
forecasts.reader) into a trade decision. The forecast is the single source of
truth; this module only interprets it.

Levels:
  FILTER     — hard gate: block trades opposed to the bias (legacy behaviour).
  PARAMETERS — soft: never blocks, but shrinks the size of opposed trades by
               `strength` (down to a floor). Aligned trades pass at full size.
  LOCK       — block all new entries for the symbol.

Bias only ever dampens or blocks — it never inflates lots beyond the risk
profile (config/profiles.py stays the ceiling).
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date

from forecasts.reader import MacroBias, get_macro_bias
from .surprise import surprise_bias

OPPOSED_FLOOR = 0.3   # smallest size multiplier for a PARAMETERS trade against bias


@dataclass(frozen=True)
class BiasDecision:
    allow: bool
    size_mult: float
    reason: str


_PASS = BiasDecision(True, 1.0, "")


def resolve_bias(symbol: str, action: str, today: date | None = None) -> BiasDecision:
    """Resolve the macro bias for `symbol` against a BUY/SELL `action`, combining
    the daily/manual forecast with the intraday post-release price reaction.
    Sources compose multiplicatively — bias only ever dampens, never inflates."""
    file_dec = _decide(get_macro_bias(symbol, today), action)
    try:
        surp = surprise_bias(symbol)
    except Exception:
        surp = None
    surp_dec = _decide(surp, action)

    allow = file_dec.allow and surp_dec.allow
    mult = round(file_dec.size_mult * surp_dec.size_mult, 2)
    reason = "; ".join(r for r in (file_dec.reason, surp_dec.reason) if r)
    return BiasDecision(allow, mult, reason)


def _decide(mb: MacroBias | None, action: str) -> BiasDecision:
    if mb is None:
        return _PASS
    if mb.level == "LOCK":
        return BiasDecision(False, 0.0, f"macro LOCK ({mb.source})")

    want = 1 if action == "BUY" else -1
    opposed = mb.direction != 0 and want != mb.direction

    if mb.level == "FILTER":
        if opposed:
            return BiasDecision(
                False, 0.0,
                f"macro FILTER vs {action} (dir={mb.direction}, {mb.source})",
            )
        return _PASS

    # PARAMETERS — soft: shrink opposed trades, never block
    if opposed:
        mult = round(max(OPPOSED_FLOOR, 1.0 - mb.strength), 2)
        return BiasDecision(
            True, mult,
            f"macro PARAMETERS softens {action} ×{mult} "
            f"(str={mb.strength}, {mb.source})",
        )
    return _PASS
