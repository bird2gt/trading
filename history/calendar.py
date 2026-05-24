"""
Economic calendar guard — blocks new trades around high-impact events.

Data source: ForexFactory (unofficial JSON feed, updated weekly).
"""

import time
import requests
from datetime import datetime, timezone, timedelta

_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_HEADERS   = {"User-Agent": "Mozilla/5.0"}

_cache: tuple[list, float] = ([], 0.0)
_CACHE_TTL = 1800  # re-fetch every 30 minutes

# Which currencies to watch per symbol
_CURRENCIES = {
    "EUR/USD": {"EUR", "USD"},
    "USD/CHF": {"USD", "CHF"},
    "GBP/USD": {"GBP", "USD"},
    "USD/JPY": {"USD", "JPY"},
    "BTC/USD": {"USD"},
    "XAU/USD": {"USD"},
    "XAG/USD": {"USD"},
}

HOURS_BEFORE = 2   # block N hours before event
HOURS_AFTER  = 1   # block N hours after event


def is_high_impact_soon(symbol: str) -> tuple[bool, str]:
    """
    Returns (True, event_title) if a high-impact event for this symbol
    falls within the block window, otherwise (False, "").
    """
    currencies = _CURRENCIES.get(symbol, set())
    if not currencies:
        return False, ""

    now = datetime.now(timezone.utc)
    events = _fetch_events()

    for ev in events:
        if ev.get("impact") != "High":
            continue
        if ev.get("country") not in currencies:
            continue

        ev_time = _parse_time(ev.get("date", ""))
        if ev_time is None:
            continue

        delta = (ev_time - now).total_seconds() / 3600
        if -HOURS_AFTER <= delta <= HOURS_BEFORE:
            return True, ev.get("title", "event")

    return False, ""


def _fetch_events() -> list:
    global _cache
    events, fetched_at = _cache

    if time.time() - fetched_at < _CACHE_TTL:
        return events

    try:
        resp = requests.get(_FEED_URL, headers=_HEADERS, timeout=10)
        events = resp.json()
        _cache = (events, time.time())
    except Exception:
        pass  # keep stale cache on error

    return events


def _parse_time(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None
