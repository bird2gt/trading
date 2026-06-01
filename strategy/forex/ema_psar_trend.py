import pandas as pd

from .base import BaseStrategy


class EmaPsarTrend(BaseStrategy):
    def __init__(self, fast: int = 20, slow: int = 50,
                 adx_period: int = 14, adx_threshold: float = 20.0,
                 psar_step: float = 0.02, psar_max_step: float = 0.2):
        self.fast = fast
        self.slow = slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.psar_step = psar_step
        self.psar_max_step = psar_max_step

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        min_bars = max(self.slow, self.adx_period) + 5
        if len(df) < min_bars:
            return 0

        close = df["close"]
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        psar = self._psar(df)
        adx, plus_di, minus_di = self._adx_di(df)

        if adx.iloc[-1] < self.adx_threshold:
            return 0

        trend_up = ema_fast.iloc[-1] > ema_slow.iloc[-1] and plus_di.iloc[-1] > minus_di.iloc[-1]
        trend_down = ema_fast.iloc[-1] < ema_slow.iloc[-1] and minus_di.iloc[-1] > plus_di.iloc[-1]

        psar_flip_up = close.iloc[-2] <= psar.iloc[-2] and close.iloc[-1] > psar.iloc[-1]
        psar_flip_down = close.iloc[-2] >= psar.iloc[-2] and close.iloc[-1] < psar.iloc[-1]
        ema_cross_up = ema_fast.iloc[-2] <= ema_slow.iloc[-2] and ema_fast.iloc[-1] > ema_slow.iloc[-1]
        ema_cross_down = ema_fast.iloc[-2] >= ema_slow.iloc[-2] and ema_fast.iloc[-1] < ema_slow.iloc[-1]

        if trend_up and (psar_flip_up or ema_cross_up):
            return 1
        if trend_down and (psar_flip_down or ema_cross_down):
            return -1
        return 0

    def _psar(self, df: pd.DataFrame) -> pd.Series:
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()
        psar = [low[0]]
        bull = close[1] >= close[0] if len(close) > 1 else True
        af = self.psar_step
        ep = high[0] if bull else low[0]

        for i in range(1, len(df)):
            next_psar = psar[-1] + af * (ep - psar[-1])

            if bull:
                if i >= 2:
                    next_psar = min(next_psar, low[i - 1], low[i - 2])
                elif i >= 1:
                    next_psar = min(next_psar, low[i - 1])

                if low[i] < next_psar:
                    bull = False
                    next_psar = ep
                    ep = low[i]
                    af = self.psar_step
                elif high[i] > ep:
                    ep = high[i]
                    af = min(af + self.psar_step, self.psar_max_step)
            else:
                if i >= 2:
                    next_psar = max(next_psar, high[i - 1], high[i - 2])
                elif i >= 1:
                    next_psar = max(next_psar, high[i - 1])

                if high[i] > next_psar:
                    bull = True
                    next_psar = ep
                    ep = high[i]
                    af = self.psar_step
                elif low[i] < ep:
                    ep = low[i]
                    af = min(af + self.psar_step, self.psar_max_step)

            psar.append(next_psar)

        return pd.Series(psar, index=df.index)

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
