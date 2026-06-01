import pandas as pd

from .base import BaseStrategy
from .sma_cross import SMACross


class Stocks(BaseStrategy):
    def __init__(self, fast: int = 10, slow: int = 30, rsi_period: int = 14):
        self.sma_cross = SMACross(fast=fast, slow=slow, rsi_period=rsi_period)

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        return self.sma_cross.generate_signal(df, **kwargs)
