import pandas as pd
from .base import BaseStrategy


class Breakout(BaseStrategy):
    def __init__(self, period: int = 20):
        self.period = period

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        if len(df) < self.period + 2:
            return 0

        prev_high = df["high"].iloc[-self.period - 1 : -1].max()
        prev_low  = df["low"].iloc[-self.period - 1 : -1].min()
        close     = df["close"]

        broke_up = close.iloc[-1] > prev_high and close.iloc[-2] <= prev_high
        broke_dn = close.iloc[-1] < prev_low  and close.iloc[-2] >= prev_low

        if broke_up:
            return 1
        if broke_dn:
            return -1
        return 0
