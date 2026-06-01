from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> int:
        """Return 1 (buy), -1 (sell), or 0 (hold)."""
        ...
