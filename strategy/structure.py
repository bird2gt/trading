import pandas as pd


def market_structure(df: pd.DataFrame, n: int = 3) -> int:
    """
    Detects HH/HL (bullish) or LH/LL (bearish) pivot structure.
    n = candles on each side for pivot identification.
    Returns 1 (bullish), -1 (bearish), 0 (unclear/mixed).
    """
    highs = df["high"]
    lows  = df["low"]
    ph, pl = [], []

    for i in range(n, len(df) - n):
        if highs.iloc[i] == highs.iloc[i - n : i + n + 1].max():
            ph.append(highs.iloc[i])
        if lows.iloc[i] == lows.iloc[i - n : i + n + 1].min():
            pl.append(lows.iloc[i])

    if len(ph) < 2 or len(pl) < 2:
        return 0

    if ph[-1] > ph[-2] and pl[-1] > pl[-2]:
        return 1   # HH + HL → bullish
    if ph[-1] < ph[-2] and pl[-1] < pl[-2]:
        return -1  # LH + LL → bearish
    return 0


def fib_tp(df: pd.DataFrame, action: int, lookback: int = 20, level: float = 1.272) -> float:
    """
    Fibonacci extension TP from the most recent swing high/low.
    action: 1=BUY, -1=SELL
    level: 1.272 (conservative) or 1.618 (aggressive)
    """
    recent = df.iloc[-lookback:]
    swing_high = recent["high"].max()
    swing_low  = recent["low"].min()
    diff = swing_high - swing_low

    if action == 1:
        return round(swing_low + level * diff, 5)
    else:
        return round(swing_high - level * diff, 5)
