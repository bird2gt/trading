import pandas as pd
from .base import BaseStrategy


class SMACross(BaseStrategy):
    def __init__(self, fast: int = 20, slow: int = 50, rsi_period: int = 14):
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period

    def generate_signal(self, df: pd.DataFrame, df_trend: pd.DataFrame | None = None) -> int:
        close = df["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        rsi = self._rsi(close)

        bullish = fast_ma.iloc[-1] > slow_ma.iloc[-1]

        adx = self._adx(df)
        if adx.iloc[-1] < 20:
            return 0
        if adx.iloc[-1] < adx.iloc[-3]:   # ADX declining = trend weakening
            return 0

        # Slope filter: fast MA must still be moving in signal direction (last 3 bars)
        fast_slope = fast_ma.iloc[-1] - fast_ma.iloc[-3]
        if bullish and fast_slope <= 0:
            return 0
        if not bullish and fast_slope >= 0:
            return 0

        trend = self._trend(df_trend) if df_trend is not None else 0

        ma200 = close.rolling(200).mean().iloc[-1]
        above_ma200 = close.iloc[-1] > ma200

        if bullish and trend >= 0 and above_ma200:
            return 1
        if not bullish and trend <= 0 and not above_ma200:
            return -1
        return 0

    def _trend(self, df: pd.DataFrame) -> int:
        close = df["close"]
        fast = close.rolling(self.fast).mean().iloc[-1]
        slow = close.rolling(self.slow).mean().iloc[-1]
        if fast > slow:
            return 1
        if fast < slow:
            return -1
        return 0

    def _adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        up = h.diff()
        dn = -l.diff()
        plus_dm = up.where((up > dn) & (up > 0), 0.0)
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
        return dx.ewm(span=period, adjust=False).mean()

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
