import pandas as pd

from .base import BaseStrategy
from .breakout_adx import BreakoutAdx
from .z_score_adx import ZScoreAdx


class Forex(BaseStrategy):
    def __init__(self, z_period: int = 20, z_entry: float = 2.0,
                 adx_period: int = 14, adx_threshold: float = 25.0,
                 z_signal_period: int = 3):
        self.z_score_adx = ZScoreAdx(
            z_period=z_period,
            z_entry=z_entry,
            adx_period=adx_period,
            adx_threshold=adx_threshold,
            z_signal_period=z_signal_period,
        )
        self.breakout = BreakoutAdx(
            period=20,
            adx_period=adx_period,
            adx_threshold=20.0,
            adx_rising_bars=3,
        )
        self.by_symbol = {
            "USD/CAD": self.breakout,
        }

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        params = dict(kwargs)
        symbol = params.pop("symbol", None)
        strategy = self.by_symbol.get(symbol, self.z_score_adx)
        return strategy.generate_signal(df, **params)
