import pandas as pd
import yfinance as yf

SYMBOL_MAP = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CHF": "USDCHF=X",
    "USD/JPY": "USDJPY=X",
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI/USD": "CL=F",
    "BRENT/USD": "BZ=F",
}

# How many 1h bars to download for each interval
_PERIOD = {
    "1h":  "6mo",
    "4h":  "6mo",
    "1day": "2y",
}


def fetch_ohlcv(symbol: str, interval: str = "4h", **kwargs) -> pd.DataFrame:
    ticker = SYMBOL_MAP.get(symbol, symbol)

    if interval == "4h":
        raw = yf.download(ticker, period="6mo", interval="1h",
                          auto_adjust=True, progress=False)
        df = _resample_4h(raw)
    else:
        yf_interval = "1h" if interval == "1h" else "1d"
        df = yf.download(ticker, period=_PERIOD.get(interval, "6mo"),
                         interval=yf_interval, auto_adjust=True, progress=False)
        df = _clean(df)

    if df.empty:
        raise ValueError(f"No data for {symbol} ({ticker})")

    return df


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = _clean(df)
    return df.resample("4h").agg({
        "open":  "first",
        "high":  "max",
        "low":   "min",
        "close": "last",
        "volume": "sum",
    }).dropna()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df
