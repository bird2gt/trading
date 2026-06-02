import os
import time
from io import StringIO
from pathlib import Path
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

# Binance: free, no key — crypto only, all intervals, up to 1000 bars
_BINANCE_MAP = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
}
_BINANCE_INTERVAL = {
    "15min": "15m",
    "1h":    "1h",
    "4h":    "4h",
    "1day":  "1d",
}
_binance_cache: dict = {}

# Tiingo: free key — crypto all intervals, forex daily only
_TIINGO_CRYPTO_MAP = {
    "BTC/USD": "btcusd",
    "ETH/USD": "ethusd",
}
_TIINGO_FX_MAP = {
    "EUR/USD": "eurusd",
    "GBP/USD": "gbpusd",
    "USD/CHF": "usdchf",
    "USD/JPY": "usdjpy",
    "USD/CAD": "usdcad",
    "AUD/USD": "audusd",
    "EUR/CHF": "eurchf",
}
_TIINGO_RESAMPLE = {
    "15min": "15min",
    "1h":    "1hour",
    "4h":    "4hour",
    "1day":  "1day",
}
_tiingo_cache: dict = {}

# Polygon: free key, 5 req/min — forex + crypto + metals daily; intraday on paid
_POLYGON_MAP = {
    "EUR/USD":  "C:EURUSD",
    "GBP/USD":  "C:GBPUSD",
    "USD/CHF":  "C:USDCHF",
    "USD/JPY":  "C:USDJPY",
    "USD/CAD":  "C:USDCAD",
    "AUD/USD":  "C:AUDUSD",
    "EUR/CHF":  "C:EURCHF",
    "XAU/USD":  "C:XAUUSD",
    "XAG/USD":  "C:XAGUSD",
    "BTC/USD":  "X:BTCUSD",
    "ETH/USD":  "X:ETHUSD",
    "WTI/USD":  "C:WTIUSD",
    "BRENT/USD": "C:BCOUSD",
}
_POLYGON_TIMESPAN = {
    "15min": (15, "minute"),
    "1h":    (1,  "hour"),
    "4h":    (4,  "hour"),
    "1day":  (1,  "day"),
}
_polygon_cache: dict = {}
_polygon_last_req: float = 0.0
_POLYGON_MIN_GAP = 12.5  # 5 req/min

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
_stooq_disabled_until: float = 0.0
_STOOQ_TIMEOUT = 5
_STOOQ_FAILURE_TTL = 1800

_STALE_HOURS = {"15min": 1, "1h": 2, "4h": 8, "1day": 48}


_source_warn_at: dict[tuple, float] = {}
_SOURCE_WARN_TTL = 600  # warn at most once per 10 min per (source, symbol, interval)


_SOURCE_PRIORITY = {
    "crypto": ("_fetch_recorded", "_fetch_binance", "_fetch_tiingo", "_fetch_twelve", "_fetch_yahoo", "_fetch_polygon", "_fetch_stooq"),
    "metal":  ("_fetch_recorded", "_fetch_twelve", "_fetch_alpha", "_fetch_finage", "_fetch_polygon", "_fetch_stooq"),
    "forex":  ("_fetch_recorded", "_fetch_twelve", "_fetch_alpha", "_fetch_stooq", "_fetch_yahoo", "_fetch_polygon", "_fetch_tiingo"),
    "other":  ("_fetch_recorded", "_fetch_yahoo", "_fetch_twelve", "_fetch_polygon", "_fetch_stooq"),
}

_DEFAULT_OHLCV_RECORD_DIR = Path(__file__).resolve().parent.parent / "data" / "ohlcv"
_OHLCV_RECORD_DIR = Path(os.environ.get("OHLCV_RECORD_DIR", str(_DEFAULT_OHLCV_RECORD_DIR)))
_OHLCV_SECRET_ENV = (
    "TWELVE_DATA_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "FINAGE_API_KEY",
    "POLYGON_API_KEY",
    "TIINGO_API_KEY",
)


def fetch_ohlcv(symbol: str, interval: str = "4h", outputsize: int = 500) -> pd.DataFrame:
    frames = []
    for source in (_fetch_recorded, _fetch_yahoo, _fetch_binance, _fetch_twelve, _fetch_tiingo,
                   _fetch_alpha, _fetch_finage, _fetch_polygon, _fetch_stooq):
        source_name = source.__name__
        if symbol in {"XAU/USD", "XAG/USD"} and source_name == "_fetch_yahoo":
            continue
        try:
            df = source(symbol, interval, outputsize)
            if not df.empty:
                frames.append((source_name, df))
        except Exception as e:
            key = (source_name, symbol, interval)
            now = time.time()
            if now - _source_warn_at.get(key, 0) >= _SOURCE_WARN_TTL:
                print(f"[WARN] {source_name}({symbol}, {interval}): {type(e).__name__}: {_mask_secrets(str(e))}")
                _source_warn_at[key] = now
            continue

    if not frames:
        raise ValueError(f"No data for {symbol} from any source")

    now = pd.Timestamp.now('UTC').tz_convert(None)
    result = _select_frame(symbol, interval, outputsize, frames, now)
    if interval == "4h":
        # The selected source may phase 4h bars off the even grid (Twelve Data starts at 01:00,
        # so hours land on {1,5,9,13,17,21}). Snap to the canonical {0,4,8,12,16,20} grid so
        # MetalsSession's session-hour gate ({8,12,16}) matches; otherwise metals never trigger.
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in result.columns:
            agg["volume"] = "sum"
        result = result.resample("4h", origin="epoch").agg(agg).dropna()
    _record_ohlcv(symbol, interval, result)
    return result


def _recording_enabled() -> bool:
    return os.environ.get("OHLCV_RECORDING_ENABLED", "1").lower() not in {"0", "false", "no"}


def _recording_start() -> pd.Timestamp:
    raw = os.environ.get("OHLCV_RECORDING_START", "")
    if raw:
        ts = pd.Timestamp(raw)
        return ts.tz_convert(None) if ts.tzinfo is not None else ts
    return pd.Timestamp.now("UTC").normalize().tz_convert(None)


def _ohlcv_path(symbol: str, interval: str) -> Path:
    safe_symbol = symbol.replace("/", "_").replace(" ", "_")
    return _OHLCV_RECORD_DIR / safe_symbol / f"{interval}.csv"


def _read_recorded_ohlcv(symbol: str, interval: str) -> pd.DataFrame:
    path = _ohlcv_path(symbol, interval)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["datetime"])
    if df.empty or "datetime" not in df.columns:
        return pd.DataFrame()
    df = df.set_index("datetime").sort_index()
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _fetch_recorded(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    df = _read_recorded_ohlcv(symbol, interval)
    if df.empty or len(df) < outputsize:
        return pd.DataFrame()
    return df.iloc[-outputsize:]


def _record_ohlcv(symbol: str, interval: str, df: pd.DataFrame) -> None:
    if not _recording_enabled() or df.empty:
        return
    try:
        to_store = df.copy()
        if "volume" not in to_store.columns:
            to_store["volume"] = 0.0
        to_store = to_store[["open", "high", "low", "close", "volume"]]
        to_store = to_store[to_store.index >= _recording_start()].dropna(subset=["open", "high", "low", "close"])
        if to_store.empty:
            return

        path = _ohlcv_path(symbol, interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_recorded_ohlcv(symbol, interval)
        combined = pd.concat([existing, to_store])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        combined.to_csv(path, index_label="datetime")
    except Exception as e:
        key = ("record_ohlcv", symbol, interval)
        now = time.time()
        if now - _source_warn_at.get(key, 0) >= _SOURCE_WARN_TTL:
            print(f"[WARN] record_ohlcv({symbol}, {interval}): {type(e).__name__}: {e}")
            _source_warn_at[key] = now


def _mask_secrets(text: str) -> str:
    for name in _OHLCV_SECRET_ENV:
        secret = os.environ.get(name, "")
        if secret:
            text = text.replace(secret, "***")
    return text


def _fetch_yahoo(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    cache_key = (symbol, interval)
    cached = _yahoo_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    ticker = SYMBOL_MAP_YAHOO.get(symbol, symbol)

    if interval == "4h":
        raw = yf.download(ticker, period="730d", interval="1h",
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
            "outputsize": min(outputsize, 5000),
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

    if interval not in ("1h", "4h", "1day"):
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

    if interval == "15min":
        return pd.DataFrame()

    ticker = _FINAGE_MAP.get(symbol)
    if ticker is None:
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _finage_cache.get(cache_key)
    if cached and time.time() - cached[1] < _FINAGE_CACHE_TTL:
        return cached[0]

    now = pd.Timestamp.now("UTC")
    days_back = _finage_days_back(interval, outputsize)
    results = _fetch_finage_results(ticker, api_key, now - pd.Timedelta(days=days_back), now + pd.Timedelta(days=1))
    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert(None)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    if interval == "4h":
        df = _resample_4h(df)
    elif interval == "1day":
        df = df.resample("1D").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

    _finage_cache[cache_key] = (df, time.time())
    return df


def _finage_days_back(interval: str, outputsize: int) -> int:
    bars = max(int(outputsize or 1), 1)
    if interval == "4h":
        return max(14, int(bars * 4 / 24) + 14)
    if interval == "1h":
        return max(7, int(bars / 24) + 7)
    if interval == "1day":
        return max(30, bars + 14)
    return 30


def _fetch_finage_results(ticker: str, api_key: str, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    chunks = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + pd.Timedelta(days=30), end)
        from_date = cursor.strftime("%Y-%m-%d")
        to_date = chunk_end.strftime("%Y-%m-%d")
        for attempt in range(2):
            try:
                resp = requests.get(
                    f"https://api.finage.co.uk/agg/forex/{ticker}/1/hour/{from_date}/{to_date}",
                    params={"apikey": api_key},
                    timeout=30,
                )
                data = resp.json()
                chunks.extend(data.get("results") or [])
                break
            except requests.RequestException:
                if attempt == 1:
                    pass
        cursor = chunk_end
    return chunks


def _fetch_stooq(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    global _stooq_disabled_until
    if time.time() < _stooq_disabled_until:
        return pd.DataFrame()

    ticker = _STOOQ_MAP.get(symbol)
    if ticker is None:
        return pd.DataFrame()

    stooq_i = {"1h": "h", "4h": "h", "1day": "d"}.get(interval)
    if stooq_i is None:
        return pd.DataFrame()

    try:
        resp = requests.get(
            "https://stooq.com/q/d/l/",
            params={"s": ticker, "i": stooq_i},
            timeout=_STOOQ_TIMEOUT,
        )
    except requests.RequestException:
        _stooq_disabled_until = time.time() + _STOOQ_FAILURE_TTL
        return pd.DataFrame()

    if resp.status_code != 200:
        return pd.DataFrame()
    if not resp.text.lstrip().lower().startswith("date,"):
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


def _fetch_binance(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    ticker = _BINANCE_MAP.get(symbol)
    if ticker is None:
        return pd.DataFrame()

    binance_i = _BINANCE_INTERVAL.get(interval)
    if binance_i is None:
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _binance_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    resp = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": ticker, "interval": binance_i, "limit": min(outputsize, 1000)},
        timeout=15,
    )
    data = resp.json()
    if not isinstance(data, list) or not data:
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore",
    ])
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(None)
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()

    _binance_cache[cache_key] = (df, time.time())
    return df


def _fetch_tiingo(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    api_key = os.environ.get("TIINGO_API_KEY", "")
    if not api_key:
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _tiingo_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    now = pd.Timestamp.now("UTC")

    if symbol in _TIINGO_CRYPTO_MAP:
        ticker = _TIINGO_CRYPTO_MAP[symbol]
        resample = _TIINGO_RESAMPLE.get(interval)
        if resample is None:
            return pd.DataFrame()
        start = (now - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://api.tiingo.com/tiingo/crypto/prices",
            params={"tickers": ticker, "startDate": start, "resampleFreq": resample},
            headers=headers,
            timeout=15,
        )
        data = resp.json()
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        rows = data[0].get("priceData", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["date"]).dt.tz_convert(None)
        df = df.rename(columns={"open": "open", "high": "high", "low": "low",
                                 "close": "close", "volumeNotional": "volume"})

    elif symbol in _TIINGO_FX_MAP and interval == "1day":
        ticker = _TIINGO_FX_MAP[symbol]
        start = (now - pd.Timedelta(days=730)).strftime("%Y-%m-%d")
        resp = requests.get(
            f"https://api.tiingo.com/tiingo/fx/{ticker}/prices",
            params={"startDate": start, "resampleFreq": "1Day"},
            headers=headers,
            timeout=15,
        )
        data = resp.json()
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df.index = pd.to_datetime(df["date"]).dt.tz_convert(None)
        df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close"})
        df["volume"] = 0.0
    else:
        return pd.DataFrame()

    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    _tiingo_cache[cache_key] = (df, time.time())
    return df


def _fetch_polygon(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    global _polygon_last_req
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        return pd.DataFrame()

    ticker = _POLYGON_MAP.get(symbol)
    if ticker is None:
        return pd.DataFrame()

    mult, timespan = _POLYGON_TIMESPAN.get(interval, (None, None))
    if mult is None:
        return pd.DataFrame()

    cache_key = (symbol, interval)
    cached = _polygon_cache.get(cache_key)
    if cached and time.time() - cached[1] < _BAR_TTL.get(interval, 14400):
        return cached[0]

    gap = _POLYGON_MIN_GAP - (time.time() - _polygon_last_req)
    if gap > 0:
        time.sleep(gap)

    now = pd.Timestamp.now("UTC")
    days_back = {"15min": 30, "1h": 90, "4h": 180, "1day": 730}.get(interval, 90)
    from_date = (now - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    resp = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from_date}/{to_date}",
        params={"adjusted": "true", "sort": "asc", "limit": min(outputsize, 50000), "apiKey": api_key},
        timeout=15,
    )
    _polygon_last_req = time.time()
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

    _polygon_cache[cache_key] = (df, time.time())
    return df


def _asset_class(symbol: str) -> str:
    if symbol in {"BTC/USD", "ETH/USD"}:
        return "crypto"
    if symbol in {"XAU/USD", "XAG/USD"}:
        return "metal"
    if "/" in symbol:
        return "forex"
    return "other"


def _select_frame(symbol: str, interval: str, outputsize: int,
                  frames: list[tuple[str, pd.DataFrame]],
                  now: pd.Timestamp) -> pd.DataFrame:
    priority = _SOURCE_PRIORITY.get(_asset_class(symbol), _SOURCE_PRIORITY["other"])
    order = {name: i for i, name in enumerate(priority)}
    prepared: list[tuple[int, str, pd.DataFrame, float]] = []

    for source_name, df in frames:
        candidate = df[df.index <= now].iloc[-outputsize:]
        if candidate.empty:
            continue
        age_h = (now - candidate.index[-1]).total_seconds() / 3600
        rank = order.get(source_name, len(order))
        prepared.append((rank, source_name, candidate, age_h))

    if not prepared:
        raise ValueError(f"No current data for {symbol} from any source")

    limit_h = _stale_limit_hours(symbol, interval)
    fresh = [item for item in prepared if item[3] <= limit_h]
    if not fresh:
        rank, source_name, candidate, age_h = min(prepared, key=lambda x: (x[0], x[3]))
        raise ValueError(
            f"{symbol} {interval}: last bar {candidate.index[-1]} from {source_name} "
            f"is {age_h:.1f}h old — data too stale"
        )

    _, _, result, _ = min(fresh, key=lambda x: x[0])
    return result.astype(float)


def _stale_limit_hours(symbol: str, interval: str) -> int:
    if symbol == "XAG/USD" and interval == "1h":
        return 4
    return _STALE_HOURS.get(interval, 8)


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
