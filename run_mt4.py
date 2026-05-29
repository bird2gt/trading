import os
import sys
import socket
import time
import threading
from datetime import date, datetime, timezone, timedelta
import requests
import pandas as pd
from history.fetcher import fetch_ohlcv
from history.news import fetch_headlines
from history.calendar import is_high_impact_soon, send_calendar_to_telegram
from strategy.sma_cross import SMACross
from strategy.breakout import Breakout
from strategy.structure import market_structure, fib_tp
from analytics.sentiment import analyze_sentiment
from analytics.digest import run_digest
from analytics.journal import sync as journal_sync, stats as journal_stats
from forecasts.reader import get_bias
from broker.mt4_bridge import run_server

BRIDGE_URL = "http://127.0.0.1:8000"
_bridge_session = requests.Session()
_bridge_token = os.environ.get("MT4_BRIDGE_TOKEN", "")
if _bridge_token:
    _bridge_session.headers["Authorization"] = f"Bearer {_bridge_token}"
DRAWDOWN_LIMIT = 0.05  # stop trading if daily loss exceeds 5%
MIN_LOTS = 0.01
MAX_LOTS = 1.0

PROFILES = {
    "forex_major": {"risk_pct": 0.02, "sl_mult": 1.5},   # EUR/USD, AUD/USD, USD/CHF, EUR/CHF
    "forex_gbp":   {"risk_pct": 0.02, "sl_mult": 2.0},   # GBP/USD — шире ATR
    "forex_jpy":   {"risk_pct": 0.02, "sl_mult": 1.5},   # USD/JPY — динамический pip_value
    "forex_cad":   {"risk_pct": 0.02, "sl_mult": 1.5},   # USD/CAD — динамический pip_value
    "crypto":      {"risk_pct": 0.01, "sl_mult": 1.0},
    "metal":       {"risk_pct": 0.02, "sl_mult": 1.0},
}

SYMBOL_PROFILES = {
    "EUR/USD": "forex_major", "USD/CHF": "forex_major",
    "EUR/CHF": "forex_major", "AUD/USD": "forex_major",
    "GBP/USD": "forex_gbp",
    "USD/JPY": "forex_jpy",
    "USD/CAD": "forex_cad",
    "BTC/USD": "crypto", "ETH/USD": "crypto",
    "XAU/USD": "metal",  "XAG/USD": "metal",
}


def _profile(symbol: str) -> dict:
    return PROFILES[SYMBOL_PROFILES.get(symbol, "forex_major")]

# pip_size = price per 1 pip; pip_value = USD per pip per standard lot
PIP_CONFIG = {
    "EUR/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "GBP/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "EUR/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/CAD": {"pip_size": 0.0001, "pip_value": 7.0},
    "AUD/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/JPY": {"pip_size": 0.01,   "pip_value": 7.0},
    "BTC/USD": {"pip_size": 1.0,    "pip_value": 1.0},
    "ETH/USD": {"pip_size": 0.1,    "pip_value": 1.0},
    "XAU/USD": {"pip_size": 0.01,   "pip_value": 1.0},
    "XAG/USD": {"pip_size": 0.001,  "pip_value": 5.0},
}

# Sessions (UTC): Asian 22:00-08:00, London 08:00-12:30, US 12:30-21:00
ALWAYS_SYMBOLS = ["BTC/USD", "ETH/USD"]
ASIAN_SYMBOLS  = ["XAU/USD", "XAG/USD"]
LONDON_SYMBOLS = ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/CHF", "USD/CAD", "AUD/USD", "USD/JPY"]
US_SYMBOLS     = ["XAU/USD"]  # gold active during full US session
POLL_INTERVAL      = 300  # 5 minutes default
POLL_INTERVAL_NEWS = 60   # 1 minute during US session (12:00–16:00 UTC = 15:00–19:00 Kyiv)
# Friday: flatten all positions before the weekend close (forex closes ~21:00 UTC)
WEEKEND_FLAT_HOUR = 20
WEEKEND_FLAT_MIN  = 30
ATR_PERIOD = 14
ATR_SL_MULT  = 1.5
ATR_TP1_MULT = 1.5     # 50% close at 1:1 risk/reward
ATR_BREAKOUT_MULT = 1.0  # tighter SL/TP for news breakout

STRATEGY = SMACross(fast=5, slow=20)
BREAKOUT_STRATEGY = Breakout(period=8)  # 8 × 15min = 2h pre-news range

CORR_GROUPS = [
    {"EUR/USD", "GBP/USD"},        # EUR и GBP коррелируют
    {"XAU/USD", "XAG/USD"},        # золото и серебро коррелируют
    {"EUR/USD", "USD/CHF"},        # оба = ставка на USD (разные стороны)
    {"GBP/USD", "USD/CHF"},        # то же
]
_MT4_TO_PY = {s.replace("/", ""): s for s in SYMBOL_PROFILES}
_active_signals: dict[str, str] = {}   # symbol → "BUY" | "SELL"
_entry_prices: dict[str, float] = {}   # symbol → entry price
_day_start: dict = {"date": None, "balance": None}
_last_digest_date: date | None = None
_last_calendar_date: date | None = None
_last_journal_sync: float = 0.0


def _active_symbols() -> list[str]:
    now = datetime.now(timezone.utc)
    hour, minute = now.hour, now.minute
    if hour < 8 or hour >= 22:
        session = ASIAN_SYMBOLS                          # 22:00-08:00: XAU, XAG
    elif hour > 12 or (hour == 12 and minute >= 30):
        session = LONDON_SYMBOLS + US_SYMBOLS            # 12:30-21:00: EUR, GBP, CHF + XAU
    else:
        session = LONDON_SYMBOLS                         # 08:00-12:30: EUR, GBP, CHF
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
        resp = _bridge_session.get(f"{BRIDGE_URL}/balance", timeout=3)
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
    if symbol == "USD/JPY":
        pip_value = 1000.0 / entry      # 100k units × 0.01 pip / rate
    elif symbol == "USD/CAD":
        pip_value = 10.0 / entry        # 100k units × 0.0001 pip / rate
    else:
        pip_value = cfg["pip_value"]
    balance = _get_balance()
    risk_amount = balance * _profile(symbol)["risk_pct"]
    lots = risk_amount / (sl_pips * pip_value)
    lots = round(lots, 2)
    return max(MIN_LOTS, min(MAX_LOTS, lots))


def _atr(df: pd.DataFrame) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean().iloc[-1]


def send_signal(td_symbol: str, action: str, df: pd.DataFrame, size_mult: float = 1.0,
                sl_mult: float = ATR_SL_MULT, tp_mult: float = ATR_TP1_MULT,
                tp_price: float | None = None, tp2_price: float | None = None):
    mt4_symbol = td_symbol.replace("/", "")
    entry = df["close"].iloc[-1]
    atr = _atr(df)

    if action == "BUY":
        sl  = round(entry - sl_mult * atr, 5)
        tp1 = tp_price if tp_price is not None else round(entry + tp_mult * atr, 5)
    elif action == "SELL":
        sl  = round(entry + sl_mult * atr, 5)
        tp1 = tp_price if tp_price is not None else round(entry - tp_mult * atr, 5)
    else:
        sl = tp1 = 0.0

    base_lots = round(_calc_lots(entry, sl, td_symbol) * size_mult, 2)
    size_note = f" [×{size_mult} sentiment]" if size_mult != 1.0 else ""

    _bridge_session.post(f"{BRIDGE_URL}/signal", json={
        "symbol": mt4_symbol, "action": action,
        "lots": base_lots, "sl": sl, "tp": tp1,
    }, timeout=3)
    _active_signals[td_symbol] = action
    _entry_prices[td_symbol] = entry
    tp_note = " [fib TP2=chandelier]" if tp2_price is not None else (" [fib]" if tp_price is not None else "")
    print(f"{td_symbol}: {action} | lots={base_lots}{size_note} | SL={sl:.5f} TP={tp1:.5f}{tp_note}")


def _send_close(symbol: str, reason: str):
    mt4_symbol = symbol.replace("/", "")
    try:
        _bridge_session.post(f"{BRIDGE_URL}/signal", json={
            "symbol": mt4_symbol, "action": "CLOSE",
            "lots": 0.01, "sl": 0.0, "tp": 0.0,
        }, timeout=3)
        _active_signals[symbol] = "NONE"
        _entry_prices.pop(symbol, None)
        print(f"{symbol}: CLOSE — {reason}")
    except Exception as e:
        print(f"{symbol}: failed to send CLOSE — {e}")


def _weekend_flat_now() -> bool:
    """True on Friday from WEEKEND_FLAT_HOUR:MIN UTC onward — time to be flat."""
    now = datetime.now(timezone.utc)
    return now.weekday() == 4 and (
        now.hour > WEEKEND_FLAT_HOUR
        or (now.hour == WEEKEND_FLAT_HOUR and now.minute >= WEEKEND_FLAT_MIN)
    )


def _close_all_positions(reason: str):
    for symbol, action in list(_active_signals.items()):
        if action in ("BUY", "SELL"):
            _send_close(symbol, reason)


def _check_early_exit(symbol: str, df_1h: pd.DataFrame) -> bool:
    active = _active_signals.get(symbol)
    if active not in ("BUY", "SELL"):
        return False

    current = df_1h["close"].iloc[-1]
    entry = _entry_prices.get(symbol)
    if entry is not None:
        atr = _atr(df_1h)
        if active == "SELL" and current > entry + 1.0 * atr:
            _send_close(symbol, f"impulse against SELL >1 ATR (entry={entry:.5f} atr={atr:.5f})")
            return True
        if active == "BUY" and current < entry - 1.0 * atr:
            _send_close(symbol, f"impulse against BUY >1 ATR (entry={entry:.5f} atr={atr:.5f})")
            return True

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


def _sleep_until_open():
    """If outside trading hours (08:00–21:00 UTC), sleep until 08:00 UTC."""
    now = datetime.now(timezone.utc)
    if 8 <= now.hour < 21:
        return
    if now.hour < 8:
        wake = now.replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        wake = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    secs = (wake - now).total_seconds()
    print(f"Outside trading hours — sleeping {secs/3600:.1f}h until {wake.strftime('%H:%M UTC')}")
    time.sleep(secs)


def trading_loop():
    global _last_digest_date, _last_calendar_date, _last_journal_sync
    while True:
        _sleep_until_open()
        today = date.today()
        if datetime.now(timezone.utc).hour == 5 and _last_calendar_date != today:
            _last_calendar_date = today
            threading.Thread(target=send_calendar_to_telegram, daemon=True).start()

        if datetime.now(timezone.utc).hour == 6 and _last_digest_date != today:
            _last_digest_date = today
            threading.Thread(target=run_digest, daemon=True).start()

        if time.time() - _last_journal_sync >= 3600:
            journal_sync()
            _last_journal_sync = time.time()

        if _weekend_flat_now():
            _close_all_positions("weekend flat — no positions held over weekend")
            print("Weekend flat — positions closed, new entries blocked until Monday")
            time.sleep(POLL_INTERVAL)
            continue

        drawdown_hit = _daily_drawdown_hit()
        now_utc = datetime.now(timezone.utc)
        in_news_window = (now_utc.hour == 12 and now_utc.minute >= 30) or (now_utc.hour == 13 and now_utc.minute < 30)

        symbols = _active_symbols()
        mode = "BREAKOUT/M15" if in_news_window else "SMA/H4"
        print(f"Session symbols: {symbols} [{mode}]{' [drawdown: new entries blocked]' if drawdown_hit else ''}")
        for symbol in symbols:
            try:
                df_1h = fetch_ohlcv(symbol, outputsize=50, interval="1h")

                if _check_early_exit(symbol, df_1h):
                    continue

                if drawdown_hit:
                    continue

                if in_news_window:
                    df_signal = fetch_ohlcv(symbol, outputsize=20, interval="15min")
                    signal = BREAKOUT_STRATEGY.generate_signal(df_signal)
                    sl_mult = tp_mult = ATR_BREAKOUT_MULT
                    tp_price = None
                    tp2_price = None
                else:
                    df_h4 = fetch_ohlcv(symbol, outputsize=220, interval="4h")
                    df_d1 = fetch_ohlcv(symbol, outputsize=60,  interval="1day")
                    df_signal = df_h4
                    signal = STRATEGY.generate_signal(df_h4, df_trend=df_d1)
                    sl_mult = _profile(symbol)["sl_mult"]
                    tp_mult = ATR_TP1_MULT
                    tp_price = None
                    tp2_price = None

                if signal == 0:
                    print(f"{symbol}: no signal")
                    continue

                # market structure filter (SMA mode only)
                if not in_news_window:
                    struct = market_structure(df_h4)
                    if signal == 1 and struct == -1:
                        print(f"{symbol}: BUY blocked — bearish structure (LH/LL)")
                        continue
                    if signal == -1 and struct == 1:
                        print(f"{symbol}: SELL blocked — bullish structure (HH/HL)")
                        continue
                    tp_price  = fib_tp(df_h4, signal, level=1.272)
                    tp2_price = fib_tp(df_h4, signal, level=1.618)

                blocked, event_title = is_high_impact_soon(symbol)
                if blocked:
                    print(f"{symbol}: blocked — high-impact event: {event_title}")
                    continue

                action = "BUY" if signal == 1 else "SELL"
                if _active_signals.get(symbol) == action:
                    print(f"{symbol}: {action} уже активен — пропуск")
                    continue

                headlines = fetch_headlines(symbol)
                score     = analyze_sentiment(symbol, headlines)
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

                send_signal(symbol, action, df_signal, size_mult=size_mult,
                            sl_mult=sl_mult, tp_mult=tp_mult, tp_price=tp_price, tp2_price=tp2_price)

            except Exception as e:
                print(f"{symbol}: error — {e}")
        interval = POLL_INTERVAL_NEWS if in_news_window else POLL_INTERVAL
        print(f"Next poll in {interval}s {'[US news window]' if in_news_window else ''}")
        time.sleep(interval)


def _load_active_signals():
    try:
        resp = _bridge_session.get(f"{BRIDGE_URL}/positions", timeout=3)
        for pos in resp.json():
            symbol = _MT4_TO_PY.get(pos["symbol"])
            if symbol:
                _active_signals[symbol] = pos["action"]
                _entry_prices[symbol] = pos["open_price"]
        if _active_signals:
            print(f"Reconciled {len(_active_signals)} open positions: {_active_signals}")
    except Exception as e:
        print(f"[WARN] position reconciliation failed: {e}")


def _clear_signal_files():
    all_symbols = ASIAN_SYMBOLS + LONDON_SYMBOLS
    for symbol in all_symbols:
        mt4_symbol = symbol.replace("/", "")
        try:
            _bridge_session.post(f"{BRIDGE_URL}/signal", json={
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


def _port_in_use(host: str = "127.0.0.1", port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


if __name__ == "__main__":
    if _port_in_use():
        print("ERROR: port 8000 already in use — another run_mt4.py is running. Aborting.")
        sys.exit(1)
    threading.Thread(target=run_server, daemon=True).start()
    print(f"MT4 bridge running at {BRIDGE_URL}")
    print("Symbols:", ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS)
    time.sleep(1)  # wait for server to start
    _clear_signal_files()
    _data_check()
    _load_active_signals()
    journal_sync()
    journal_stats()
    trading_loop()
