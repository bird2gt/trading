"""
Intraday surprise layer (price-reaction proxy).

The ForexFactory feed carries no `actual` values, so instead of "actual vs
forecast" we read the market's own reaction: after a scheduled high-impact
event for one of a pair's currencies, measure how far the pair moved in the
release window (in units of its normal 15m volatility). A significant move
sets a short, decaying soft bias (PARAMETERS) leaning with that move.

The expensive path (15m OHLCV fetch) only runs when a relevant event actually
fired within the TTL — otherwise the calendar check returns instantly.
"""

from __future__ import annotations
from datetime import datetime, timezone

import pandas as pd

from forecasts.reader import MacroBias
from history.calendar import recent_high_impact_events
from history.fetcher import fetch_ohlcv

TTL_HOURS = 6.0          # how long a release keeps leaning (linear decay to 0)
REACTION_CANDLES = 3     # 15m bars after the release that count as the reaction (~45m)
SIGMA_LOOKBACK = 96      # 15m bars (~24h) used to estimate normal volatility
Z_MIN = 2.0              # ignore moves smaller than this many normal-15m sigmas
Z_SCALE = 5.0            # z above Z_MIN that maps to full strength
CAP = 0.8               # max conviction from a single release

# short memo so per-symbol resolve calls within/between cycles don't refetch
_CACHE_TTL = 180.0
_cache: dict[str, tuple[float, MacroBias | None]] = {}


def surprise_bias(symbol: str, now: datetime | None = None,
                  df15: pd.DataFrame | None = None) -> MacroBias | None:
    """Soft bias from the latest post-release price reaction, or None."""
    now = now or datetime.now(timezone.utc)

    cached = _cache.get(symbol)
    if cached and df15 is None and (now.timestamp() - cached[0]) < _CACHE_TTL:
        return cached[1]

    events = recent_high_impact_events(symbol, TTL_HOURS)
    if not events:
        _cache[symbol] = (now.timestamp(), None)
        return None

    ev = events[0]  # most recent release
    if df15 is None:
        try:
            df15 = fetch_ohlcv(symbol, outputsize=200, interval="15min")
        except Exception:
            return None  # don't cache failures; retry next cycle

    lean = _reaction(df15, ev["time"], now)
    result = None
    if lean is not None:
        direction, strength = lean
        if direction != 0 and strength > 0:
            result = MacroBias(direction, strength, "PARAMETERS",
                               f"surprise {ev['title']} @ {ev['time']:%H:%MZ}")
    _cache[symbol] = (now.timestamp(), result)
    return result


def _reaction(df15: pd.DataFrame | None, event_time: datetime,
              now: datetime) -> tuple[int, float] | None:
    """(direction, strength) from the pair's move across the release window,
    sized in normal-15m sigmas and decayed by age. None if insignificant."""
    if df15 is None or df15.empty:
        return None

    # Normalise both the index and the comparison times to naive UTC.
    times = df15.index
    if getattr(times, "tz", None) is not None:
        times = times.tz_convert("UTC").tz_localize(None)
    ev = event_time.astimezone(timezone.utc).replace(tzinfo=None)
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)

    pre_mask = times <= pd.Timestamp(ev)
    pre_pos = int(pre_mask.sum()) - 1
    if pre_pos < 1:
        return None  # release not covered by the data we have

    close = df15["close"].reset_index(drop=True)
    pre_close = close.iloc[pre_pos]
    post_pos = min(pre_pos + REACTION_CANDLES, len(close) - 1)
    if post_pos <= pre_pos or pre_close <= 0:
        return None  # reaction window not formed yet

    reaction = (close.iloc[post_pos] - pre_close) / pre_close
    sigma = close.pct_change().iloc[max(0, pre_pos - SIGMA_LOOKBACK):pre_pos].std()
    if pd.isna(sigma) or sigma == 0 or pd.isna(reaction):
        return None

    z = reaction / sigma
    if abs(z) < Z_MIN:
        return None

    age_h = (now_naive - ev).total_seconds() / 3600
    decay = max(0.0, 1.0 - age_h / TTL_HOURS)
    strength = min((abs(z) - Z_MIN) / Z_SCALE, CAP) * decay
    if strength <= 0:
        return None

    return (1 if reaction > 0 else -1), round(strength, 2)
