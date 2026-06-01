import pandas as pd
from .base import BaseStrategy


class EmaAtr(BaseStrategy):
    """EMA crossover confirmed by ATR expansion."""

    def __init__(self, fast: int = 9, slow: int = 21, atr_period: int = 14, atr_ma: int = 20):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.atr_ma = atr_ma

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.slow + self.atr_ma + 2:
            return 0

        close = df["close"]
        ema_f = close.ewm(span=self.fast, adjust=False).mean()
        ema_s = close.ewm(span=self.slow, adjust=False).mean()

        cross_up = ema_f.iloc[-2] <= ema_s.iloc[-2] and ema_f.iloc[-1] > ema_s.iloc[-1]
        cross_dn = ema_f.iloc[-2] >= ema_s.iloc[-2] and ema_f.iloc[-1] < ema_s.iloc[-1]
        if not cross_up and not cross_dn:
            return 0

        h, l, c = df["high"], df["low"], df["close"]
        tr  = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(self.atr_period).mean()
        if atr.iloc[-1] <= atr.rolling(self.atr_ma).mean().iloc[-1]:
            return 0

        return 1 if cross_up else -1
