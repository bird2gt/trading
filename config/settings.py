import os
from dotenv import load_dotenv

load_dotenv()

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
BYBIT_TESTNET = True

# Global risk settings
MAX_RISK_PER_TRADE = 0.01
MAX_DRAWDOWN = 0.10
TIMEFRAME = "1h"

# Trading profiles by asset class
PROFILES = {
    "forex": {
        "enabled": True,
        "symbols": ["EUR/USD", "USD/CHF", "GBP/USD"],
        "strategy": "sma_cross",
        "strategy_params": {
            "fast": 20,
            "slow": 50,
            "rsi_period": 14,
        },
        "risk_params": {
            "sl_pct": 0.02,
            "tp_pct": 0.04,
        },
    },
    "crypto": {
        "enabled": True,
        "symbols": ["BTC/USDT", "ETH/USDT"],
        "strategy": "breakout",
        "strategy_params": {
            "period": 20,
        },
        "risk_params": {
            "sl_pct": 0.03,
            "tp_pct": 0.05,
        },
    },
    "metals": {
        "enabled": True,
        "symbols": ["XAU/USD", "XAG/USD"],
        "strategy": "mean_reversion",
        "strategy_params": {
            "period": 20,
            "std_mult": 2.0,
        },
        "risk_params": {
            "sl_pct": 0.015,
            "tp_pct": 0.03,
        },
    },
    "stocks": {
        "enabled": False,
        "symbols": ["AAPL", "GOOGL"],
        "strategy": "sma_cross",
        "strategy_params": {
            "fast": 10,
            "slow": 30,
            "rsi_period": 14,
        },
        "risk_params": {
            "sl_pct": 0.025,
            "tp_pct": 0.04,
        },
    },
}

# Legacy (for backward compatibility)
SYMBOLS = PROFILES["crypto"]["symbols"]
