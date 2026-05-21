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
        rsi = self._rsi(df["close"])
        last = rsi.iloc[-1]

        if last < self.oversold:
            return 1
        if last > self.overbought:
            return -1
        return 0
