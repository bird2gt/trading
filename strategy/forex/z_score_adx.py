import pandas as pd
from .base import BaseStrategy


class ZScoreAdx(BaseStrategy):
    def __init__(self, z_period: int = 20, z_entry: float = 2.0,
                 adx_period: int = 14, ema_period: int = 200,
                 adx_threshold: float = 25.0):
        self.z_period = z_period
        self.z_entry = z_entry
        self.adx_period = adx_period
        self.ema_period = ema_period
        self.adx_threshold = adx_threshold

    def generate_signal(self, df: pd.DataFrame, df_h4: pd.DataFrame | None = None) -> int:
        if len(df) < max(self.z_period, self.ema_period) + 2:
            return 0

        close = df["close"]

        sma = close.rolling(self.z_period).mean()
        std = close.rolling(self.z_period).std()
        if std.iloc[-1] == 0:
            return 0
        z_score = (close.iloc[-1] - sma.iloc[-1]) / std.iloc[-1]

        ema200 = close.rolling(self.ema_period).mean().iloc[-1]
        above_ema = close.iloc[-1] > ema200

        trend_df = df_h4 if df_h4 is not None else df
        adx = self._adx(trend_df)
        if adx.iloc[-1] < self.adx_threshold:
            return 0

        if above_ema and z_score <= -self.z_entry:
            return 1
        if not above_ema and z_score >= self.z_entry:
            return -1
        return 0

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
