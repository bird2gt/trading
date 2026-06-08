import pandas as pd

from .base import BaseStrategy
from .breakout_adx import BreakoutAdx
from .take_profit import AdxMa, TwoB
from .z_score_adx import ZScoreAdx


class PairProfile(BaseStrategy):
    def __init__(self, name: str, engine: BaseStrategy):
        self.name = name
        self.engine = engine
        self.mean_reverting = getattr(engine, "mean_reverting", False)

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        return self.engine.generate_signal(df, **kwargs)


class DisabledEngine(BaseStrategy):
    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        return 0


class EurUsdDefensive(PairProfile):
    def __init__(self):
        super().__init__(
            "EUR/USD TakeProfit ADX+MA",
            AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
        )
        self.mean_reverting = True


class GbpUsdSwing(PairProfile):
    def __init__(self):
        super().__init__(
            "GBP/USD TakeProfit 2B",
            TwoB(lookback=20),
        )


class UsdChfBreakout(PairProfile):
    def __init__(self):
        super().__init__(
            "USD/CHF Breakout ADX",
            BreakoutAdx(period=30, adx_period=14, adx_threshold=20.0, adx_rising_bars=3),
        )


class UsdJpyDefensive(PairProfile):
    def __init__(self):
        super().__init__(
            "USD/JPY TakeProfit 2B",
            TwoB(lookback=20),
        )


class AudUsdSwing(PairProfile):
    # 2026-06-04: backtested over 12mo — 2B beat BreakoutADX/AdxMa/ZScore on AUD/USD
    # (PF 1.39 / +$2.3k vs PF<0.7 net-negative for breakout/trend). Same engine as GBP/USD, USD/JPY.
    def __init__(self):
        super().__init__(
            "AUD/USD TakeProfit 2B",
            TwoB(lookback=20),
        )


class EurChfMeanReversion(PairProfile):
    def __init__(self):
        super().__init__(
            "EUR/CHF Mean Reversion ZScore",
            ZScoreAdx(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0, z_signal_period=3),
        )
        self.mean_reverting = True


class UsdCadBreakout(PairProfile):
    def __init__(self):
        super().__init__(
            "USD/CAD TakeProfit ADX+MA",
            AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
        )
        self.mean_reverting = True
