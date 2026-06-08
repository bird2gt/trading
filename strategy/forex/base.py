from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    # Mean-reverting engines buy dips / sell rallies, so the trend-following
    # market-structure gate (block BUY in LH/LL) is counter-productive for them.
    mean_reverting = False

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> int:
        """Return 1 (buy), -1 (sell), or 0 (hold)."""
        ...
