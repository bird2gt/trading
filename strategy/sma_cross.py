import pandas as pd
from .base import BaseStrategy


class SMACross(BaseStrategy):
    def __init__(self, fast: int = 20, slow: int = 50, rsi_period: int = 14):
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period

    def generate_signal(self, df: pd.DataFrame) -> int:
        close = df["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        rsi = self._rsi(close)

        crossed_up = fast_ma.iloc[-1] > slow_ma.iloc[-1] and fast_ma.iloc[-2] <= slow_ma.iloc[-2]
        crossed_dn = fast_ma.iloc[-1] < slow_ma.iloc[-1] and fast_ma.iloc[-2] >= slow_ma.iloc[-2]

        if crossed_up and rsi.iloc[-1] < 65:
            return 1
        if crossed_dn and rsi.iloc[-1] > 35:
            return -1
        return 0

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
