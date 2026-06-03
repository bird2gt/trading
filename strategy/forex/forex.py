import pandas as pd

from .base import BaseStrategy
from .pair_profiles import (
    DisabledEngine,
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
            # AUD/USD disabled: BreakoutAdx is net-negative over 12mo (−$1.3k; every R:R combo
            # PF<0.9 in backtest). Re-enable via AudUsdBreakout() once the engine is reworked.
            "AUD/USD": PairProfile("AUD/USD Disabled (neg EV)", DisabledEngine()),
            "EUR/CHF": EurChfMeanReversion(),
            "USD/CAD": UsdCadBreakout(),
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
