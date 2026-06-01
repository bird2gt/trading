import pandas as pd

from .base import BaseStrategy


class BreakoutAdx(BaseStrategy):
    def __init__(self, period: int = 20, adx_period: int = 14,
                 adx_threshold: float = 20.0, adx_rising_bars: int = 3):
        self.period = period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.adx_rising_bars = adx_rising_bars

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        min_bars = self.period + self.adx_period + self.adx_rising_bars + 2
        if len(df) < min_bars:
            return 0

        close = df["close"]
        prev_high = df["high"].iloc[-self.period - 1:-1].max()
        prev_low = df["low"].iloc[-self.period - 1:-1].min()

        broke_up = close.iloc[-1] > prev_high and close.iloc[-2] <= prev_high
        broke_dn = close.iloc[-1] < prev_low and close.iloc[-2] >= prev_low
        if not broke_up and not broke_dn:
            return 0

        adx, plus_di, minus_di = self._adx_di(df)
        if adx.iloc[-1] < self.adx_threshold:
            return 0
        if adx.iloc[-1] <= adx.iloc[-self.adx_rising_bars - 1]:
            return 0

        trend_up = plus_di.iloc[-1] > minus_di.iloc[-1]
        if broke_up and trend_up:
            return 1
        if broke_dn and not trend_up:
            return -1
        return 0

    def _adx_di(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        h, l, c = df["high"], df["low"], df["close"]
        up = h.diff()
        dn = -l.diff()
        plus_dm = up.where((up > dn) & (up > 0), 0.0)
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        a = 1 / self.adx_period
        atr = tr.ewm(alpha=a, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
        adx = dx.ewm(alpha=a, adjust=False).mean()
        return adx, plus_di, minus_di
