import os
import time
from io import StringIO
import requests
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

_no_key_warned_at: float = 0

SYMBOL_MAP_YAHOO = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CHF": "USDCHF=X",
    "EUR/CHF": "EURCHF=X",
    "USD/CAD": "USDCAD=X",
    "AUD/USD": "AUDUSD=X",
    "USD/JPY": "USDJPY=X",
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI/USD": "CL=F",
    "BRENT/USD": "BZ=F",
}

_YAHOO_PERIOD = {
    "15min": "60d",
    "1h":    "6mo",
    "4h":    "6mo",
    "1day":  "2y",
}

_TWELVE_INTERVAL = {
    "15min": "15min",
    "1h":    "1h",
    "4h":    "4h",
    "1day":  "1day",
}

# Alpha Vantage: forex/metals pairs only (no crypto on free tier)
_ALPHA_FX_MAP = {
    "EUR/USD": ("EUR", "USD"),
    "GBP/USD": ("GBP", "USD"),
    "USD/CHF": ("USD", "CHF"),
    "USD/JPY": ("USD", "JPY"),
    "USD/CAD": ("USD", "CAD"),
    "AUD/USD": ("AUD", "USD"),
    "XAU/USD": ("XAU", "USD"),
    "XAG/USD": ("XAG", "USD"),
}
_alpha_cache: dict = {}
_yahoo_cache: dict = {}
_twelve_cache: dict = {}

# Cache TTL = bar period: no new bar forms sooner, so no point fetching sooner
_BAR_TTL = {"15min": 900, "1h": 3600, "4h": 14400, "1day": 86400}

# Finage: free tier 1000 req/month — only used for XAG/USD (no other source covers it)
_FINAGE_MAP = {
    "XAG/USD": "XAGUSD",
}
_finage_cache: dict = {}
_FINAGE_CACHE_TTL = 14400  # 4 hours — matches bar period; ~12 req/day × 30 = 360/month

# Stooq: free, no key, CSV download
_STOOQ_MAP = {
    "EUR/USD": "eurusd",
    "GBP/USD": "gbpusd",
    "USD/CHF": "usdchf",
    "USD/JPY": "usdjpy",
    "USD/CAD": "usdcad",
    "AUD/USD": "audusd",
    "XAU/USD": "xauusd",
    "XAG/USD": "xagusd",
    "BTC/USD": "btcusd",
}

_STALE_HOURS = {"15min": 1, "1h": 2, "4h": 8, "1day": 48}


def fetch_ohlcv(symbol: str, interval: str = "4h", outputsize: int = 500) -> pd.DataFrame:
    frames = []
    for source in (_fetch_yahoo, _fetch_twelve, _fetch_alpha, _fetch_finage, _fetch_stooq):
        try:
            df = source(symbol, interval, outputsize)
            if not df.empty:
                frames.append(df)
        except Exception:
            continue

    if not frames:
        raise ValueError(f"No data for {symbol} from any source")

    now = pd.Timestamp.now('UTC').tz_convert(None)
    result = _merge(frames).iloc[-outputsize:]
    result = result[result.index <= now]

    if not result.empty:
        age_h = (now - result.index[-1]).total_seconds() / 3600
        limit_h = _STALE_HOURS.get(interval, 8)
        if age_h > limit_h:
            raise ValueError(f"{symbol} {interval}: last bar {result.index[-1]} is {age_h:.1f}h old — data too stale")

    return result


def _fetch_yahoo(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    cache_key = (symbol, interval)
    cached = _yahoo_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    ticker = SYMBOL_MAP_YAHOO.get(symbol, symbol)

    if interval == "4h":
        raw = yf.download(ticker, period="6mo", interval="1h",
                          auto_adjust=True, progress=False)
        df = _resample_4h(raw)
    elif interval == "15min":
        df = yf.download(ticker, period="60d", interval="15m",
                         auto_adjust=True, progress=False)
        df = _clean(df)
    else:
        yf_interval = "1h" if interval == "1h" else "1d"
        df = yf.download(ticker, period=_YAHOO_PERIOD.get(interval, "6mo"),
                         interval=yf_interval, auto_adjust=True, progress=False)
        df = _clean(df)

    _yahoo_cache[cache_key] = (df, time.time())
    return df


def _fetch_twelve(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    global _no_key_warned_at
    api_key = os.environ.get("TWELVE_DATA_API_KEY", "")
    if not api_key:
        if time.time() - _no_key_warned_at >= 600:
            print("⚠️  Twelve Data: пропал API ключ! Используется только Yahoo.")
            _no_key_warned_at = time.time()
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _twelve_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    resp = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol":     symbol,
            "interval":   _TWELVE_INTERVAL.get(interval, interval),
            "outputsize": 500,
            "timezone":   "UTC",
            "apikey":     api_key,
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("status") != "ok" or "values" not in data:
        return pd.DataFrame()

    df = pd.DataFrame(data["values"])
    df.index = pd.to_datetime(df["datetime"]).dt.tz_localize(None)
    df = df.drop(columns=["datetime"])
    df = df.astype(float).sort_index()

    _twelve_cache[cache_key] = (df, time.time())
    return df


def _fetch_alpha(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        return pd.DataFrame()

    if interval not in ("1h", "1day"):
        return pd.DataFrame()

    pair = _ALPHA_FX_MAP.get(symbol)
    if pair is None:
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _alpha_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    if interval == "1day":
        function, av_interval = "FX_DAILY", None
        ts_key = "Time Series FX (Daily)"
    else:
        function, av_interval = "FX_INTRADAY", "60min"
        ts_key = "Time Series FX (60min)"

    params = {
        "function":    function,
        "from_symbol": pair[0],
        "to_symbol":   pair[1],
        "outputsize":  "full",
        "apikey":      api_key,
    }
    if av_interval:
        params["interval"] = av_interval

    resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=15)
    data = resp.json()
    if ts_key not in data:
        return pd.DataFrame()

    df = pd.DataFrame(data[ts_key]).T
    df.index = pd.to_datetime(df.index)
    df.columns = [c.split(". ", 1)[1] for c in df.columns]
    df = df.astype(float).sort_index()
    df["volume"] = 0.0

    if interval == "4h":
        df = _resample_4h(df)

    _alpha_cache[cache_key] = (df, time.time())
    return df


def _fetch_finage(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    api_key = os.environ.get("FINAGE_API_KEY", "")
    if not api_key:
        return pd.DataFrame()

    ticker = _FINAGE_MAP.get(symbol)
    if ticker is None:
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _finage_cache.get(cache_key)
    if cached and time.time() - cached[1] < _FINAGE_CACHE_TTL:
        return cached[0]

    now = pd.Timestamp.now('UTC')
    from_date = (now - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    # Always fetch 1h bars — avoids bar-alignment gaps on session opens
    resp = requests.get(
        f"https://api.finage.co.uk/agg/forex/{ticker}/1/hour/{from_date}/{to_date}",
        params={"apikey": api_key},
        timeout=15,
    )
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()

    if interval == "4h":
        df = _resample_4h(df)
    elif interval == "1day":
        df = df.resample("1D").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

    _finage_cache[cache_key] = (df, time.time())
    return df


def _fetch_stooq(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    ticker = _STOOQ_MAP.get(symbol)
    if ticker is None:
        return pd.DataFrame()

    stooq_i = {"1h": "h", "4h": "h", "1day": "d"}.get(interval)
    if stooq_i is None:
        return pd.DataFrame()

    resp = requests.get(
        "https://stooq.com/q/d/l/",
        params={"s": ticker, "i": stooq_i},
        timeout=15,
    )
    if resp.status_code != 200:
        return pd.DataFrame()

    df = pd.read_csv(StringIO(resp.text))
    if df.empty or "Open" not in df.columns:
        return pd.DataFrame()

    df.columns = [c.lower() for c in df.columns]
    if "time" in df.columns:
        df.index = pd.to_datetime(df["date"] + " " + df["time"])
        df = df.drop(columns=["date", "time"])
    else:
        df.index = pd.to_datetime(df["date"])
        df = df.drop(columns=["date"])

    if "vol" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"vol": "volume"})
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df[["open", "high", "low", "close", "volume"]].dropna().astype(float).sort_index()

    if interval == "4h":
        df = _resample_4h(df)

    return df


def _merge(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if len(frames) == 1:
        return frames[0]

    # Normalize timestamps to minute precision to absorb small offsets between sources
    normalized = []
    for df in frames:
        df = df.copy()
        df.index = df.index.floor("min")
        normalized.append(df)

    idx = normalized[0].index
    for df in normalized[1:]:
        idx = idx.union(df.index)

    cols = pd.concat([df.reindex(idx) for df in normalized], axis=1, keys=range(len(normalized)))

    result = pd.DataFrame(index=idx)
    for col in ("open", "close", "volume"):
        result[col] = cols.xs(col, axis=1, level=1).mean(axis=1)
    result["high"] = cols.xs("high", axis=1, level=1).max(axis=1)
    result["low"]  = cols.xs("low",  axis=1, level=1).min(axis=1)

    return result.dropna(subset=["close"]).astype(float)


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = _clean(df)
    return df.resample("4h").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_convert(None) if idx.tz is not None else idx
    return df[["open", "high", "low", "close", "volume"]].dropna()
