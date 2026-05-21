import os
from dotenv import load_dotenv

load_dotenv()

TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"]

SYMBOLS = ["BTC/USDT"]
FOREX_SYMBOLS = ["EUR/USD", "GBP/USD"]
TIMEFRAME = "1h"

# Risk
MAX_RISK_PER_TRADE = 0.01
MAX_DRAWDOWN = 0.10

# Bybit
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
BYBIT_TESTNET = True
