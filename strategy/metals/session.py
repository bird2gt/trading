import pandas as pd
from .base import BaseStrategy
from .zscore_adx_trend import ZScoreAdxTrend
from .silver import Silver

# H4 bar hours (UTC) per session
_ASIAN_HOURS  = {20, 0, 4}
_LONDON_HOURS = {8}
_US_HOURS     = {12, 16}


class MetalsSession(BaseStrategy):
    """
    Session-aware strategy dispatcher for metals.

    Bar-hour dispatch (H4 UTC):
      - Asian  (20, 0, 4): no edge — stay flat
      - London (8):        XAU → ZScoreAdxTrend | XAG → Silver + ratio filter
      - US/CME (12, 16):   XAU → ZScoreAdxTrend | XAG → Silver + ratio filter

    XAG generate_signal accepts an optional df_xau kwarg for the Gold/Silver ratio filter.
    """

    # z_entry 2.0 + ADX 25 (was 1.5/20): stricter filter ~halves entries (118→46 over 12mo),
    # turning gold's trend from churn (PF≈1.0) into profit (PF 1.30 / +$1.2k 12mo backtest).
    _XAU_STRAT = ZScoreAdxTrend(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0)
    _XAG_STRAT = Silver(ema_fast=21, ema_slow=55, rsi_period=14, rsi_buy=40.0, rsi_sell=60.0,
                        adx_period=14, adx_threshold=20.0, ratio_high=80.0, ratio_low=65.0)

    def __init__(self, symbol: str):
        sym = symbol.replace("/", "")
        if sym in ("XAUUSD",):
            self._strat  = self._XAU_STRAT
            self._is_xag = False
        elif sym in ("XAGUSD",):
            self._strat  = self._XAG_STRAT
            self._is_xag = True
        else:
            raise ValueError(f"MetalsSession: unknown symbol '{symbol}'")

    def generate_signal(self, df: pd.DataFrame, df_xau: pd.DataFrame | None = None, **kwargs) -> int:
        if df.empty:
            return 0
        hour = df.index[-1].hour
        if hour not in _LONDON_HOURS and hour not in _US_HOURS:
            return 0  # Asian — no edge
        if self._is_xag:
            return self._strat.generate_signal(df, df_xau=df_xau)
        return self._strat.generate_signal(df)
