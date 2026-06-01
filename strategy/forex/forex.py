import pandas as pd

from .base import BaseStrategy
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

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        return self.z_score_adx.generate_signal(df, **kwargs)
