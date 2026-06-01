import pandas as pd

from .base import BaseStrategy


class AdxMa(BaseStrategy):
    def __init__(self, ma_period: int = 21, adx_period: int = 14,
                 adx_threshold: float = 20.0):
        self.ma_period = ma_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        min_bars = max(self.ma_period, self.adx_period) + 3
        if len(df) < min_bars:
            return 0

        ma = df["close"].rolling(self.ma_period).mean()
        adx, _, _ = self._adx_di(df)
        if adx.iloc[-1] <= self.adx_threshold:
            return 0

        crossed_up = df["close"].iloc[-2] <= ma.iloc[-2] and df["close"].iloc[-1] > ma.iloc[-1]
        crossed_down = df["close"].iloc[-2] >= ma.iloc[-2] and df["close"].iloc[-1] < ma.iloc[-1]
        if crossed_up:
            return 1
        if crossed_down:
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


class TwoB(BaseStrategy):
    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < self.lookback + 5:
            return 0

        breakout = df.iloc[-2]
        confirm = df.iloc[-1]
        history = df.iloc[-self.lookback - 3:-3]
        if history.empty:
            return 0

        failed_low = breakout["low"] < history["low"].min() and confirm["close"] > breakout["high"]
        failed_high = breakout["high"] > history["high"].max() and confirm["close"] < breakout["low"]
        if failed_low:
            return 1
        if failed_high:
            return -1
        return 0
