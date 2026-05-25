import time
import threading
from datetime import date, datetime, timezone
import requests
import pandas as pd
from history.fetcher import fetch_ohlcv
from history.news import fetch_headlines
from history.calendar import is_high_impact_soon
from strategy.sma_cross import SMACross
from analytics.sentiment import analyze_sentiment
from analytics.digest import run_digest
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

CORR_GROUPS = [{"EUR/USD", "GBP/USD"}, {"XAU/USD", "XAG/USD"}]
_active_signals: dict[str, str] = {}  # symbol → "BUY" | "SELL"
_day_start: dict = {"date": None, "balance": None}
_last_digest_date: date | None = None


def _active_symbols() -> list[str]:
    hour = datetime.now(timezone.utc).hour
    session = ASIAN_SYMBOLS if (hour < 8 or hour >= 22) else LONDON_SYMBOLS
    return ALWAYS_SYMBOLS + session


def _daily_drawdown_hit() -> bool:
    today = date.today()
    try:
        balance = _get_balance()
    except RuntimeError as e:
        print(f"[WARN] drawdown check skipped: {e}")
        return False
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
    except Exception as e:
        raise RuntimeError(f"balance unavailable: {e}") from e
    if bal is None:
        raise RuntimeError("balance endpoint returned null — balance.txt missing or MT4 not running")
    return float(bal)


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


def send_signal(td_symbol: str, action: str, df: pd.DataFrame, size_mult: float = 1.0):
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

    lots = round(_calc_lots(entry, sl, td_symbol) * size_mult, 2)
    requests.post(f"{BRIDGE_URL}/signal", json={
        "symbol": mt4_symbol,
        "action": action,
        "lots": lots,
        "sl": sl,
        "tp": tp1,
    }, timeout=3)
    _active_signals[td_symbol] = action
    size_note = f" [×{size_mult} sentiment]" if size_mult != 1.0 else ""
    print(f"{td_symbol}: {action} | lots={lots}{size_note} | SL={sl:.5f} TP1={tp1:.5f}")


def _send_close(symbol: str, reason: str):
    mt4_symbol = symbol.replace("/", "")
    try:
        requests.post(f"{BRIDGE_URL}/signal", json={
            "symbol": mt4_symbol, "action": "CLOSE",
            "lots": 0.01, "sl": 0.0, "tp": 0.0,
        }, timeout=3)
        _active_signals[symbol] = "NONE"
        print(f"{symbol}: CLOSE — {reason}")
    except Exception as e:
        print(f"{symbol}: failed to send CLOSE — {e}")


def _check_early_exit(symbol: str, df_1h: pd.DataFrame) -> bool:
    active = _active_signals.get(symbol)
    if active not in ("BUY", "SELL"):
        return False
    close = df_1h["close"]
    fast_ma = close.rolling(STRATEGY.fast).mean().iloc[-1]
    slow_ma = close.rolling(STRATEGY.slow).mean().iloc[-1]
    if active == "BUY" and fast_ma < slow_ma:
        _send_close(symbol, "1h trend reversed bearish")
        return True
    if active == "SELL" and fast_ma > slow_ma:
        _send_close(symbol, "1h trend reversed bullish")
        return True
    return False


def trading_loop():
    global _last_digest_date
    while True:
        today = date.today()
        if datetime.now(timezone.utc).hour == 7 and _last_digest_date != today:
            _last_digest_date = today
            threading.Thread(target=run_digest, daemon=True).start()

        if _daily_drawdown_hit():
            time.sleep(POLL_INTERVAL)
            continue
        symbols = _active_symbols()
        print(f"Session symbols: {symbols}")
        for symbol in symbols:
            try:
                df_1h = fetch_ohlcv(symbol, outputsize=50,  interval="1h")
                df_h4 = fetch_ohlcv(symbol, outputsize=100, interval="4h")
                df_d1 = fetch_ohlcv(symbol, outputsize=60,  interval="1day")

                if _check_early_exit(symbol, df_1h):
                    continue

                signal = STRATEGY.generate_signal(df_h4, df_trend=df_d1)

                if signal == 0:
                    print(f"{symbol}: no signal")
                    continue

                blocked, event_title = is_high_impact_soon(symbol)
                if blocked:
                    print(f"{symbol}: blocked — high-impact event: {event_title}")
                    continue

                headlines = fetch_headlines(symbol)
                score     = analyze_sentiment(symbol, headlines)
                action    = "BUY" if signal == 1 else "SELL"
                print(f"{symbol}: {action} | sentiment score={score:+d}")

                # strongly against → block
                if signal == 1 and score == -2:
                    print(f"{symbol}: BUY blocked — strongly bearish sentiment")
                    continue
                if signal == -1 and score == 2:
                    print(f"{symbol}: SELL blocked — strongly bullish sentiment")
                    continue

                # mildly against → halve position size
                size_mult = 0.5 if (signal == 1 and score == -1) or (signal == -1 and score == 1) else 1.0

                forecast = get_bias(symbol)
                if signal == 1 and forecast == -1:
                    print(f"{symbol}: BUY blocked by macro forecast")
                    continue
                if signal == -1 and forecast == 1:
                    print(f"{symbol}: SELL blocked by macro forecast")
                    continue

                if _correlated_conflict(symbol, action):
                    print(f"{symbol}: {action} blocked by correlation")
                    continue

                send_signal(symbol, action, df_h4, size_mult=size_mult)

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


def _data_check():
    print("--- data check ---")
    all_symbols = ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS
    ok = True
    for symbol in all_symbols:
        for interval in ("1h", "4h", "1day"):
            try:
                df = fetch_ohlcv(symbol, outputsize=5, interval=interval)
                last = df.index[-1]
                close = df["close"].iloc[-1]
                age_h = (pd.Timestamp.now('UTC').tz_convert(None) - last).total_seconds() / 3600
                print(f"  {symbol} {interval}: last={last} close={close:.4f} age={age_h:.1f}h OK")
            except Exception as e:
                print(f"  {symbol} {interval}: FAIL — {e}")
                ok = False
    print(f"--- data check {'OK' if ok else 'FAILED'} ---")


if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print(f"MT4 bridge running at {BRIDGE_URL}")
    print("Symbols:", ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS)
    time.sleep(1)  # wait for server to start
    _clear_signal_files()
    _data_check()
    trading_loop()
