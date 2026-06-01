import pandas as pd

from .base import BaseStrategy
from .breakout import Breakout


class Crypto(BaseStrategy):
    def __init__(self, period: int = 20, adx_period: int = 14,
                 adx_threshold: float = 25.0, vol_ma: int = 20,
                 vol_mult: float = 1.2, adx_rising_bars: int = 5):
        self.breakout = Breakout(
            period=period,
            adx_period=adx_period,
            adx_threshold=adx_threshold,
            vol_ma=vol_ma,
            vol_mult=vol_mult,
            adx_rising_bars=adx_rising_bars,
        )

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        return self.breakout.generate_signal(df, **kwargs)
