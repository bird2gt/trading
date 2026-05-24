import time
import threading
from datetime import date, datetime, timezone
import requests
import pandas as pd
from history.fetcher import fetch_ohlcv
from history.news import fetch_headlines
from strategy.sma_cross import SMACross
from analytics.sentiment import analyze_sentiment
from forecasts.reader import get_bias
from broker.mt4_bridge import run_server

BRIDGE_URL = "http://127.0.0.1:8000"
RISK_PCT = 0.15        # 15% of balance per trade
DRAWDOWN_LIMIT = 0.05  # stop trading if daily loss exceeds 5%
MIN_LOTS = 0.01
MAX_LOTS = 1.0

# pip_size = price per 1 pip; pip_value = USD per pip per standard lot
PIP_CONFIG = {
    "EUR/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "BTC/USD": {"pip_size": 1.0,    "pip_value": 1.0},
    "XAU/USD": {"pip_size": 0.01,   "pip_value": 1.0},
    "XAG/USD": {"pip_size": 0.001,  "pip_value": 5.0},
}

# UTC hours: 00-07 and 22-23 → Asian session
ALWAYS_SYMBOLS = ["BTC/USD"]
ASIAN_SYMBOLS  = ["XAU/USD", "XAG/USD"]
LONDON_SYMBOLS = ["EUR/USD", "USD/CHF"]
POLL_INTERVAL = 300    # 5 minutes
ATR_PERIOD = 14
ATR_SL_MULT  = 1.5
ATR_TP1_MULT = 1.5     # 50% close at 1:1 risk/reward

STRATEGY = SMACross(fast=10, slow=30)

CORR_GROUPS = [{"EUR/USD", "GBP/USD"}]
_active_signals: dict[str, str] = {}  # symbol → "BUY" | "SELL"
_day_start: dict = {"date": None, "balance": None}


def _active_symbols() -> list[str]:
    hour = datetime.now(timezone.utc).hour
    session = ASIAN_SYMBOLS if (hour < 8 or hour >= 22) else LONDON_SYMBOLS
    return ALWAYS_SYMBOLS + session


def _daily_drawdown_hit() -> bool:
    today = date.today()
    balance = _get_balance()
    if _day_start["date"] != today:
        _day_start["date"] = today
        _day_start["balance"] = balance
        print(f"New day — starting balance: {balance:.2f}")
        return False
    start = _day_start["balance"]
    loss_pct = (start - balance) / start
    if loss_pct >= DRAWDOWN_LIMIT:
        print(f"Daily drawdown limit hit: -{loss_pct*100:.1f}% (start={start:.2f}, now={balance:.2f})")
        return True
    return False


def _correlated_conflict(symbol: str, action: str) -> bool:
    for group in CORR_GROUPS:
        if symbol not in group:
            continue
        for other in group:
            if other == symbol:
                continue
            if _active_signals.get(other) == action:
                return True
    return False


def _get_balance() -> float:
    try:
        resp = requests.get(f"{BRIDGE_URL}/balance", timeout=3)
        bal = resp.json().get("balance")
        return float(bal) if bal else 4000.0
    except Exception:
        return 4000.0


def _calc_lots(entry: float, sl: float, symbol: str) -> float:
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return MIN_LOTS
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    sl_pips = sl_distance / cfg["pip_size"]
    balance = _get_balance()
    risk_amount = balance * RISK_PCT
    lots = risk_amount / (sl_pips * cfg["pip_value"])
    lots = round(lots, 2)
    return max(MIN_LOTS, min(MAX_LOTS, lots))


def _atr(df: pd.DataFrame) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean().iloc[-1]


def send_signal(td_symbol: str, action: str, df: pd.DataFrame):
    mt4_symbol = td_symbol.replace("/", "")
    entry = df["close"].iloc[-1]
    atr = _atr(df)

    if action == "BUY":
        sl  = round(entry - ATR_SL_MULT  * atr, 5)
        tp1 = round(entry + ATR_TP1_MULT * atr, 5)
    elif action == "SELL":
        sl  = round(entry + ATR_SL_MULT  * atr, 5)
        tp1 = round(entry - ATR_TP1_MULT * atr, 5)
    else:
        sl = tp1 = 0.0

    lots = _calc_lots(entry, sl, td_symbol)
    requests.post(f"{BRIDGE_URL}/signal", json={
        "symbol": mt4_symbol,
        "action": action,
        "lots": lots,
        "sl": sl,
        "tp": tp1,
    }, timeout=3)
    _active_signals[td_symbol] = action
    print(f"{td_symbol}: {action} | lots={lots} | SL={sl:.5f} TP1={tp1:.5f}")


def trading_loop():
    while True:
        if _daily_drawdown_hit():
            time.sleep(POLL_INTERVAL)
            continue
        symbols = _active_symbols()
        print(f"Session symbols: {symbols}")
        for symbol in symbols:
            try:
                df_h4 = fetch_ohlcv(symbol, outputsize=100, interval="4h")
                df_d1 = fetch_ohlcv(symbol, outputsize=60,  interval="1day")
                signal = STRATEGY.generate_signal(df_h4, df_trend=df_d1)

                if signal == 0:
                    print(f"{symbol}: no signal")
                    continue

                headlines  = fetch_headlines(symbol)
                sentiment  = analyze_sentiment(symbol, headlines)
                print(f"{symbol}: signal={'BUY' if signal==1 else 'SELL'} | sentiment={sentiment}")

                if signal == 1 and sentiment == "bearish":
                    print(f"{symbol}: BUY blocked by bearish sentiment")
                    continue
                if signal == -1 and sentiment == "bullish":
                    print(f"{symbol}: SELL blocked by bullish sentiment")
                    continue

                forecast = get_bias(symbol)
                if signal == 1 and forecast == -1:
                    print(f"{symbol}: BUY blocked by macro forecast")
                    continue
                if signal == -1 and forecast == 1:
                    print(f"{symbol}: SELL blocked by macro forecast")
                    continue

                action = "BUY" if signal == 1 else "SELL"
                if _correlated_conflict(symbol, action):
                    print(f"{symbol}: {action} blocked by correlation")
                    continue

                send_signal(symbol, action, df_h4)

            except Exception as e:
                print(f"{symbol}: error — {e}")
        time.sleep(POLL_INTERVAL)


def _clear_signal_files():
    all_symbols = ASIAN_SYMBOLS + LONDON_SYMBOLS
    for symbol in all_symbols:
        mt4_symbol = symbol.replace("/", "")
        try:
            requests.post(f"{BRIDGE_URL}/signal", json={
                "symbol": mt4_symbol, "action": "NONE",
                "lots": 0.01, "sl": 0.0, "tp": 0.0,
            }, timeout=3)
        except Exception:
            pass
    print("Signal files cleared")


if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print(f"MT4 bridge running at {BRIDGE_URL}")
    print("Symbols:", ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS)
    time.sleep(1)  # wait for server to start
    _clear_signal_files()
    trading_loop()
