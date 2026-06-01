import pandas as pd
from .base import BaseStrategy


class ZScoreAdx(BaseStrategy):
    def __init__(self, z_period: int = 20, z_entry: float = 2.0,
                 adx_period: int = 14, adx_threshold: float = 25.0,
                 z_signal_period: int = 3):
        self.z_period = z_period
        self.z_entry = z_entry
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.z_signal_period = z_signal_period

    def generate_signal(self, df: pd.DataFrame, df_h4: pd.DataFrame | None = None) -> int:
        min_bars = max(self.z_period, self.adx_period) + self.z_signal_period + 2
        if len(df) < min_bars:
            return 0

        close = df["close"]

        sma = close.rolling(self.z_period).mean()
        std = close.rolling(self.z_period).std()
        if std.iloc[-1] == 0:
            return 0

        z = (close - sma) / std
        z_sig = z.rolling(self.z_signal_period).mean()
        if pd.isna(z_sig.iloc[-1]) or pd.isna(z_sig.iloc[-2]):
            return 0

        trend_df = df_h4 if df_h4 is not None else df
        adx, plus_di, minus_di = self._adx_di(trend_df)
        if adx.iloc[-1] < self.adx_threshold:
            return 0

        trend_up = plus_di.iloc[-1] > minus_di.iloc[-1]

        # Enter on Z-Score crossing back through its signal line from extreme zone
        crossed_up = z.iloc[-2] < z_sig.iloc[-2] and z.iloc[-1] >= z_sig.iloc[-1]
        crossed_dn = z.iloc[-2] > z_sig.iloc[-2] and z.iloc[-1] <= z_sig.iloc[-1]

        if trend_up and crossed_up and z.iloc[-2] <= -self.z_entry:
            return 1
        if not trend_up and crossed_dn and z.iloc[-2] >= self.z_entry:
            return -1
        return 0

    def _adx_di(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        h, l, c = df["high"], df["low"], df["close"]
        up = h.diff()
        dn = -l.diff()
        plus_dm  = up.where((up > dn) & (up > 0), 0.0)
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        a        = 1 / self.adx_period
        atr      = tr.ewm(alpha=a, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
        dx  = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
        adx = dx.ewm(alpha=a, adjust=False).mean()
        return adx, plus_di, minus_di
