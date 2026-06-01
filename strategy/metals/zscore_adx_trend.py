import pandas as pd
from .base import BaseStrategy


class ZScoreAdxTrend(BaseStrategy):
    """Momentum: price extended in trend direction + ADX >= threshold."""

    def __init__(self, z_period: int = 20, z_entry: float = 1.5,
                 adx_period: int = 14, adx_threshold: float = 20.0):
        self.z_period = z_period
        self.z_entry = z_entry
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.z_period + self.adx_period + 2:
            return 0

        close = df["close"]
        sma = close.rolling(self.z_period).mean()
        std = close.rolling(self.z_period).std()
        if std.iloc[-1] == 0 or pd.isna(std.iloc[-1]):
            return 0
        z = (close.iloc[-1] - sma.iloc[-1]) / std.iloc[-1]

        adx, pdi, mdi = self._adx_di(df)
        if adx.iloc[-1] < self.adx_threshold:
            return 0

        trend_up = pdi.iloc[-1] > mdi.iloc[-1]
        if trend_up and z > self.z_entry:
            return 1
        if not trend_up and z < -self.z_entry:
            return -1
        return 0

    def _adx_di(self, df: pd.DataFrame):
        h, l, c = df["high"], df["low"], df["close"]
        up = h.diff(); dn = -l.diff()
        plus_dm  = up.where((up > dn) & (up > 0), 0.0)
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
        tr  = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        a   = 1 / self.adx_period
        atr = tr.ewm(alpha=a, adjust=False).mean()
        pdi = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
        mdi = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
        dx  = (100 * (pdi - mdi).abs() / (pdi + mdi)).fillna(0)
        return dx.ewm(alpha=a, adjust=False).mean(), pdi, mdi
