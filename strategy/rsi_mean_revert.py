import pandas as pd
from .base import BaseStrategy


class RSIMeanRevert(BaseStrategy):
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.period + 2:
            return 0
        rsi = self._rsi(df["close"])
        prev, last = rsi.iloc[-2], rsi.iloc[-1]
        if pd.isna(prev) or pd.isna(last):
            return 0

        # Fire on the cross INTO the zone, not on the level: returning a signal on
        # every bar while RSI stays < oversold causes repeated re-entries into a
        # falling knife after a stop/early exit. One event per oversold excursion.
        if prev >= self.oversold and last < self.oversold:
            return 1
        if prev <= self.overbought and last > self.overbought:
            return -1
        return 0
