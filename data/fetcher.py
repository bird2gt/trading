import requests
import pandas as pd
from pathlib import Path
from config.settings import TWELVE_DATA_API_KEY, TIMEFRAME

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

BASE_URL = "https://api.twelvedata.com/time_series"


def fetch_ohlcv(symbol: str, outputsize: int = 500, interval: str | None = None) -> pd.DataFrame:
    tf = interval or TIMEFRAME
    cache_file = CACHE_DIR / f"{symbol.replace('/', '_')}_{tf}.parquet"

    params = {
        "symbol": symbol,
        "interval": tf,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }
    resp = requests.get(BASE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if "values" not in data:
        raise ValueError(f"Bad response for {symbol}: {data.get('message')}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col])

    df.to_parquet(cache_file)
    return df


def load_cached(symbol: str) -> pd.DataFrame | None:
    cache_file = CACHE_DIR / f"{symbol.replace('/', '_')}_{TIMEFRAME}.parquet"
    if cache_file.exists():
        return pd.read_parquet(cache_file)
    return None
