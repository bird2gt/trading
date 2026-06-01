"""
Crypto Fear & Greed Index — Alternative.me public API.
Returns daily values 0-100: 0=Extreme Fear, 100=Extreme Greed.
"""
import time
import requests
import pandas as pd

_URL = "https://api.alternative.me/fng/?limit={limit}&format=json"
_cache: pd.DataFrame | None = None
_cache_ts: float = 0.0
CACHE_TTL = 3600  # 1 hour


def fetch_history(days: int = 500) -> pd.DataFrame:
    """Returns DataFrame indexed by date with columns: value, classification."""
    global _cache, _cache_ts
    if _cache is not None and time.time() - _cache_ts < CACHE_TTL:
        return _cache

    resp = requests.get(_URL.format(limit=days), timeout=10)
    resp.raise_for_status()
    records = resp.json()["data"]

    df = pd.DataFrame(records)
    df["value"] = df["value"].astype(int)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s").dt.date
    df = df.set_index("date")[["value", "value_classification"]].sort_index()

    _cache = df
    _cache_ts = time.time()
    return df


def get_value(date) -> int | None:
    """Returns F&G value (0-100) for a given date, or None if unavailable."""
    try:
        df = fetch_history()
        d = date.date() if hasattr(date, "date") else date
        if d in df.index:
            return int(df.loc[d, "value"])
        # fall back to nearest prior day (weekends/gaps)
        prior = [x for x in df.index if x <= d]
        return int(df.loc[prior[-1], "value"]) if prior else None
    except Exception:
        return None
