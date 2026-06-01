import numpy as np
import pandas as pd
from .base import BaseStrategy


class SupertrendRsi(BaseStrategy):
    def __init__(self, atr_period: int = 10, mult: float = 3.0,
                 rsi_period: int = 14, rsi_long: float = 55.0, rsi_short: float = 45.0):
        self.atr_period = atr_period
        self.mult = mult
        self.rsi_period = rsi_period
        self.rsi_long = rsi_long
        self.rsi_short = rsi_short

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < max(self.atr_period, self.rsi_period) * 2 + 2:
            return 0

        direction = self._supertrend(df)
        rsi = self._rsi(df["close"])

        if pd.isna(rsi.iloc[-1]):
            return 0

        trend_up   = direction.iloc[-1] == 1
        trend_down = direction.iloc[-1] == -1
        just_flipped_up   = direction.iloc[-2] == -1 and trend_up
        just_flipped_down = direction.iloc[-2] ==  1 and trend_down

        if just_flipped_up and rsi.iloc[-1] > self.rsi_long:
            return 1
        if just_flipped_down and rsi.iloc[-1] < self.rsi_short:
            return -1
        return 0

    def _supertrend(self, df: pd.DataFrame) -> pd.Series:
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        atr = self._atr(df).values
        hl2 = (h + l) / 2

        raw_upper = hl2 + self.mult * atr
        raw_lower = hl2 - self.mult * atr
        upper = raw_upper.copy()
        lower = raw_lower.copy()
        direction = np.ones(len(c), dtype=int)

        for i in range(1, len(c)):
            upper[i] = (raw_upper[i] if raw_upper[i] < upper[i-1] or c[i-1] > upper[i-1]
                        else upper[i-1])
            lower[i] = (raw_lower[i] if raw_lower[i] > lower[i-1] or c[i-1] < lower[i-1]
                        else lower[i-1])

            if direction[i-1] == -1 and c[i] > upper[i]:
                direction[i] = 1
            elif direction[i-1] == 1 and c[i] < lower[i]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]

        return pd.Series(direction, index=df.index)

    def _atr(self, df: pd.DataFrame) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.ewm(span=self.atr_period, adjust=False).mean()

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(span=self.rsi_period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(span=self.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100 - 100 / (1 + rs)
