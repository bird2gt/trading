import time
import threading
import requests
import pandas as pd
from config.settings import FOREX_SYMBOLS
from data.fetcher import fetch_ohlcv
from strategy.sma_cross import SMACross
from broker.mt4_bridge import run_server

BRIDGE_URL = "http://127.0.0.1:8000"
LOT_SIZE = 0.01
POLL_INTERVAL = 60  # seconds
ATR_PERIOD = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

STRATEGY = SMACross(fast=20, slow=50)


def _atr(df: pd.DataFrame) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean().iloc[-1]


def send_signal(td_symbol: str, action: str, df: pd.DataFrame):
    mt4_symbol = td_symbol.replace("/", "")
    entry = df["close"].iloc[-1]
    atr = _atr(df)

    if action == "BUY":
        sl = round(entry - ATR_SL_MULT * atr, 5)
        tp = round(entry + ATR_TP_MULT * atr, 5)
    elif action == "SELL":
        sl = round(entry + ATR_SL_MULT * atr, 5)
        tp = round(entry - ATR_TP_MULT * atr, 5)
    else:
        sl = tp = 0.0

    requests.post(f"{BRIDGE_URL}/signal", json={
        "symbol": mt4_symbol,
        "action": action,
        "lots": LOT_SIZE,
        "sl": sl,
        "tp": tp,
    }, timeout=3)
    print(f"{td_symbol}: {action} | SL={sl:.5f} TP={tp:.5f}")


def trading_loop():
    while True:
        for symbol in FOREX_SYMBOLS:
            try:
                df = fetch_ohlcv(symbol, outputsize=100)
                signal = STRATEGY.generate_signal(df)
                if signal == 1:
                    send_signal(symbol, "BUY", df)
                elif signal == -1:
                    send_signal(symbol, "SELL", df)
                else:
                    print(f"{symbol}: no signal")
            except Exception as e:
                print(f"{symbol}: error — {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print(f"MT4 bridge running at {BRIDGE_URL}")
    print("Symbols:", FOREX_SYMBOLS)
    trading_loop()
