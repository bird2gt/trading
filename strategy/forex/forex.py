import pandas as pd

from .base import BaseStrategy
from .breakout_adx import BreakoutAdx
from .pair_profiles import (
    AudUsdSwing,
    EurChfMeanReversion,
    EurUsdDefensive,
    GbpUsdSwing,
    PairProfile,
    UsdCadBreakout,
    UsdChfBreakout,
    UsdJpyDefensive,
)


class Forex(BaseStrategy):
    def __init__(self, z_period: int = 20, z_entry: float = 2.0,
                 adx_period: int = 14, adx_threshold: float = 25.0,
                 z_signal_period: int = 3):
        self.by_symbol = {
            "EUR/USD": EurUsdDefensive(),
            "GBP/USD": GbpUsdSwing(),
            "USD/CHF": UsdChfBreakout(),
            "USD/JPY": UsdJpyDefensive(),
            "AUD/USD": AudUsdSwing(),   # re-enabled 2026-06-04: 2B (PF 1.39/12mo backtest)
            "EUR/CHF": EurChfMeanReversion(),
            "USD/CAD": UsdCadBreakout(),
            "NZD/CHF": PairProfile(
                "NZD/CHF Breakout ADX",
                BreakoutAdx(period=24, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
            ),
            "AUD/CHF": PairProfile(
                "AUD/CHF Breakout ADX",
                BreakoutAdx(period=20, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
            ),
            "NZD/JPY": PairProfile(
                "NZD/JPY Breakout ADX",
                BreakoutAdx(period=20, adx_period=14, adx_threshold=23.0, adx_rising_bars=3),
            ),
            "NZD/CAD": PairProfile(
                "NZD/CAD Breakout ADX",
                BreakoutAdx(period=24, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
            ),
        }

    def generate_signal(self, df: pd.DataFrame, **kwargs) -> int:
        params = dict(kwargs)
        symbol = params.pop("symbol", None)
        strategy = self.by_symbol.get(symbol)
        if strategy is None:
            return 0
        return strategy.generate_signal(df, **params)

    def strategy_name(self, symbol: str) -> str:
        strategy = self.by_symbol.get(symbol)
        if strategy is None:
            return "Forex Disabled"
        return getattr(strategy, "name", type(strategy).__name__)

    def is_mean_reverting(self, symbol: str) -> bool:
        strategy = self.by_symbol.get(symbol)
        return bool(getattr(strategy, "mean_reverting", False))
