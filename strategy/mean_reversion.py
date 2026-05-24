import pandas as pd
from .base import BaseStrategy


class MeanReversion(BaseStrategy):
    def __init__(self, period: int = 20, std_mult: float = 2.0):
        self.period   = period
        self.std_mult = std_mult

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < self.period + 2:
            return 0

        close  = df["close"]
        mid    = close.rolling(self.period).mean()
        std    = close.rolling(self.period).std()
        upper  = mid + self.std_mult * std
        lower  = mid - self.std_mult * std

        # bounce off lower band → BUY
        if close.iloc[-2] < lower.iloc[-2] and close.iloc[-1] >= lower.iloc[-1]:
            return 1
        # bounce off upper band → SELL
        if close.iloc[-2] > upper.iloc[-2] and close.iloc[-1] <= upper.iloc[-1]:
            return -1
        return 0
