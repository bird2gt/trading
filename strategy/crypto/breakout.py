import pandas as pd
from .base import BaseStrategy


class Breakout(BaseStrategy):
    def __init__(self, period: int = 20, adx_period: int = 14,
                 adx_threshold: float = 25.0, vol_ma: int = 20, vol_mult: float = 1.2,
                 adx_rising_bars: int = 5):
        self.period = period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.vol_ma = vol_ma
        self.vol_mult = vol_mult
        self.adx_rising_bars = adx_rising_bars

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < self.period + self.adx_period + self.vol_ma + self.adx_rising_bars + 2:
            return 0

        close = df["close"]
        prev_high = df["high"].iloc[-self.period - 1: -1].max()
        prev_low  = df["low"].iloc[-self.period - 1: -1].min()

        broke_up = close.iloc[-1] > prev_high and close.iloc[-2] <= prev_high
        broke_dn = close.iloc[-1] < prev_low  and close.iloc[-2] >= prev_low

        if not broke_up and not broke_dn:
            return 0

        adx = self._adx(df)
        if adx.iloc[-1] < self.adx_threshold:
            return 0

        # Regime filter: ADX must be rising — trend is accelerating, not fading
        if adx.iloc[-1] <= adx.iloc[-self.adx_rising_bars - 1]:
            return 0

        if not self._volume_surge(df):
            return 0

        return 1 if broke_up else -1

    def _adx(self, df: pd.DataFrame) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        up = h.diff()
        dn = -l.diff()
        plus_dm  = up.where((up > dn) & (up > 0), 0.0)
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr      = tr.ewm(span=self.adx_period, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=self.adx_period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(span=self.adx_period, adjust=False).mean() / atr
        dx  = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
        return dx.ewm(span=self.adx_period, adjust=False).mean()

    def _volume_surge(self, df: pd.DataFrame) -> bool:
        vol = df["volume"]
        if vol.iloc[-self.vol_ma:].sum() == 0:
            return True
        vol_ma = vol.rolling(self.vol_ma).mean()
        return vol.iloc[-1] > self.vol_mult * vol_ma.iloc[-1]
