import pandas as pd

from .base import BaseStrategy
from .mean_reversion import MeanReversion


class Metals(BaseStrategy):
    def __init__(self, period: int = 20, std_mult: float = 2.0,
                 adx_period: int = 14, max_adx: float = 25.0):
        self.mean_reversion = MeanReversion(period=period, std_mult=std_mult)
        self.adx_period = adx_period
        self.max_adx = max_adx

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < self.adx_period + 2:
            return 0
        if self._adx(df).iloc[-1] > self.max_adx:
            return 0
        return self.mean_reversion.generate_signal(df, **kwargs)

    def _adx(self, df: pd.DataFrame) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        up = h.diff()
        dn = -l.diff()
        plus_dm = up.where((up > dn) & (up > 0), 0.0)
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=self.adx_period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(span=self.adx_period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(span=self.adx_period, adjust=False).mean() / atr
        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
        return dx.ewm(span=self.adx_period, adjust=False).mean()
