---
applyTo: "strategy/forex/**"
description: "Forex strategy standards: data format requirements, required methods, testing conventions, and integration guidelines"
---

# Forex Strategy Standards

File instructions for all forex trading strategies in this workspace.

## Required Data Format

All forex strategies must accept OHLC data in this format:

```python
# Input data structure
{
    'timestamp': datetime,      # UTC timestamp for the bar
    'open': float,              # Opening price
    'high': float,              # Highest price in period
    'low': float,               # Lowest price in period
    'close': float,             # Closing price
    'volume': int or float      # Trading volume (optional for forex)
}
```

## Required Methods

Every strategy class must implement:

```python
class ForexStrategy:
    def __init__(self, symbol: str, timeframe: str):
        """Initialize strategy with currency pair and timeframe (1H, 4H, 1D, etc.)"""
        pass
    
    def on_bar(self, bar: dict) -> Optional[dict]:
        """
        Process a new bar and generate signals
        
        Returns:
            - None: no action
            - {'action': 'BUY', 'size': float}: long entry
            - {'action': 'SELL', 'size': float}: short entry
            - {'action': 'CLOSE'}: exit position
        """
        pass
    
    def get_indicators(self) -> dict:
        """Return current indicator values for analysis"""
        pass
```

## File Naming Convention

- File name matches strategy name (snake_case)
- Class name in PascalCase matches file name
- Example: `mean_reversion.py` → `class MeanReversion`

## Backtesting Integration

Strategies must work with the backtest engine:

```python
from backtest.engine import BacktestEngine
from strategy.forex.your_strategy import YourStrategy

engine = BacktestEngine(
    strategy=YourStrategy(symbol='EURUSD', timeframe='1H'),
    data_source=data_loader,  # Must provide dicts in standard format
    initial_capital=10000,
    risk_percent=2
)
```

## Data Validation

Before using new data sources:

1. **Format Check**: Verify all OHLC fields are present and correct types
2. **Completeness**: Confirm no missing bars for the timeframe
3. **Logic Test**: Run a single strategy on the data to catch format issues
4. **Compare**: Cross-reference with known good data sources

See `/strategy/forex/base.py` for the base class implementation.

## Testing Requirements

- Unit tests for signal generation
- Backtests on 3+ different pairs
- Documentation of parameter ranges tested
- Example trade logs showing entry/exit logic
