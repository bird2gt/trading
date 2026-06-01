import pandas as pd
from .base import BaseStrategy


class Silver(BaseStrategy):
    """
    XAG/USD strategy combining:
      - EMA(21/55) trend direction
      - RSI(14): pullback to 40 in uptrend / rally to 60 in downtrend (mean-reversion entry)
      - ADX >= threshold for trend strength
      - Optional Gold/Silver ratio bias (pass df_xau to generate_signal)

    Entry logic (per LiteFinance research):
      uptrend   + RSI touches/crosses down through rsi_buy  → BUY  (oversold pullback)
      downtrend + RSI touches/crosses up   through rsi_sell → SELL (overbought rally)

    Ratio logic: if ratio > ratio_high → silver undervalued → only BUY
                 if ratio < ratio_low  → silver overvalued  → only SELL
                 otherwise             → both directions allowed
    """

    def __init__(self, ema_fast: int = 21, ema_slow: int = 55,
                 rsi_period: int = 14, rsi_buy: float = 40.0, rsi_sell: float = 60.0,
                 adx_period: int = 14, adx_threshold: float = 20.0,
                 ratio_high: float = 80.0, ratio_low: float = 65.0):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.rsi_buy    = rsi_buy
        self.rsi_sell   = rsi_sell
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.ratio_high = ratio_high
        self.ratio_low  = ratio_low

    def generate_signal(self, df: pd.DataFrame, df_xau: pd.DataFrame | None = None) -> int:
        if len(df) < self.ema_slow + self.rsi_period + 2:
            return 0

        close = df["close"]

        # EMA trend
        ema_f = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_s = close.ewm(span=self.ema_slow, adjust=False).mean()
        trend_up = ema_f.iloc[-1] > ema_s.iloc[-1]

        # ADX filter
        adx, _, _ = self._adx_di(df)
        if adx.iloc[-1] < self.adx_threshold:
            return 0

        # RSI: enter on pullback-to-support (40) in uptrend, rally-to-resistance (60) in downtrend
        rsi = self._rsi(close)
        if pd.isna(rsi.iloc[-1]) or pd.isna(rsi.iloc[-2]):
            return 0

        # Touch: previous bar was at/below rsi_buy, now recovering (or still there)
        touched_buy  = rsi.iloc[-2] <= self.rsi_buy  and rsi.iloc[-1] > rsi.iloc[-2]
        touched_sell = rsi.iloc[-2] >= self.rsi_sell and rsi.iloc[-1] < rsi.iloc[-2]

        if trend_up and touched_buy:
            raw = 1
        elif not trend_up and touched_sell:
            raw = -1
        else:
            return 0

        # Gold/Silver ratio bias filter
        if df_xau is not None and len(df_xau) >= 2:
            ratio = df_xau["close"].iloc[-1] / df["close"].iloc[-1]
            if ratio > self.ratio_high and raw == -1:
                return 0   # ratio says silver cheap → block shorts
            if ratio < self.ratio_low and raw == 1:
                return 0   # ratio says silver expensive → block longs

        return raw

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss  = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs    = gain / loss.replace(0, float("nan"))
        return 100 - 100 / (1 + rs)

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
