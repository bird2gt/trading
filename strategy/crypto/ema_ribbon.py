import pandas as pd
from .base import BaseStrategy


class EmaRibbon(BaseStrategy):
    def __init__(self, fast: int = 8, mid: int = 21, slow: int = 55,
                 vol_ma: int = 20, vol_mult: float = 1.5):
        self.fast = fast
        self.mid = mid
        self.slow = slow
        self.vol_ma = vol_ma
        self.vol_mult = vol_mult

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < self.slow + self.vol_ma + 2:
            return 0

        close = df["close"]
        ema_f = close.ewm(span=self.fast,  adjust=False).mean()
        ema_m = close.ewm(span=self.mid,   adjust=False).mean()
        ema_s = close.ewm(span=self.slow,  adjust=False).mean()

        # EMA(fast) just crossed EMA(mid) and EMA(mid) > EMA(slow) confirms trend
        crossed_up = ema_f.iloc[-2] <= ema_m.iloc[-2] and ema_f.iloc[-1] > ema_m.iloc[-1]
        crossed_dn = ema_f.iloc[-2] >= ema_m.iloc[-2] and ema_f.iloc[-1] < ema_m.iloc[-1]

        vol_ok = self._volume_surge(df)

        if crossed_up and ema_m.iloc[-1] > ema_s.iloc[-1] and vol_ok:
            return 1
        if crossed_dn and ema_m.iloc[-1] < ema_s.iloc[-1] and vol_ok:
            return -1
        return 0

    def _volume_surge(self, df: pd.DataFrame) -> bool:
        vol = df["volume"]
        if vol.iloc[-self.vol_ma:].sum() == 0:
            return True  # no volume data — skip filter
        vol_ma = vol.rolling(self.vol_ma).mean()
        return vol.iloc[-1] > self.vol_mult * vol_ma.iloc[-1]
