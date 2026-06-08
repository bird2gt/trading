import os
import sys
import json
import socket
import time
import threading
import logging
from pathlib import Path
from datetime import date, datetime, timezone
import requests
import pandas as pd
from history.fetcher import fetch_ohlcv
from history.news import fetch_headlines
from history.calendar import is_high_impact_active, is_high_impact_soon, send_calendar_to_telegram
from strategy.sma_cross import SMACross
from strategy.breakout import Breakout as NewsBreakout
from strategy.crypto import Crypto
from strategy.forex import Forex
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.metals import MetalsSession
from strategy.structure import market_structure, fib_tp
from analytics.sentiment import analyze_sentiment
from analytics.fear_greed import get_value as get_fg_value
from analytics.digest import run_digest
from analytics.journal import sync as journal_sync, stats as journal_stats
from analytics.learning import run_learning
from bias import resolve_bias
from broker.mt4_bridge import run_server

# Setup basic logging — timestamps in UTC to match the session/weekend gate
logging.Formatter.converter = time.gmtime
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s UTC - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BRIDGE_URL = "http://127.0.0.1:8000"
_bridge_session = requests.Session()
_bridge_token = os.environ.get("MT4_BRIDGE_TOKEN", "")
if _bridge_token:
    _bridge_session.headers["Authorization"] = f"Bearer {_bridge_token}"
DRAWDOWN_LIMIT = 0.05  # stop trading if daily loss exceeds 5%
# Trading rules (risk %, ATR stop/target multipliers, pip specs) live in
# config/profiles.py — the single source of truth shared with the backtest.
from config.profiles import SYMBOL_GROUP, PIP_CONFIG, MIN_LOTS, MAX_LOTS, rules_for

# Sessions (UTC): Asian 22:00-08:00, London 08:00-12:30, US 12:30-21:00
ALWAYS_SYMBOLS = ["BTC/USD", "ETH/USD"]
MAJOR_SYMBOLS  = ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/CHF", "USD/CAD", "AUD/USD", "USD/JPY"]
ASIAN_SYMBOLS  = ["XAU/USD", "XAG/USD", "JP225", "NZD/CHF", "AUD/CHF", "NZD/JPY", "NZD/CAD"]
LONDON_SYMBOLS = ["XAU/USD", "XAG/USD", "BRENT", "WTI", "DE40",
                  "NZD/CHF", "AUD/CHF", "NZD/JPY", "NZD/CAD"] + MAJOR_SYMBOLS
US_SYMBOLS     = ["XAU/USD", "XAG/USD", "BRENT", "WTI", "USTEC", "US500"] + MAJOR_SYMBOLS
POLL_INTERVAL      = 300  # 5 minutes default
POLL_INTERVAL_NEWS = 60   # 1 minute during US session (12:00–16:00 UTC = 15:00–19:00 Kyiv)
# Friday: flatten all positions before the weekend close (forex closes ~21:00 UTC)
WEEKEND_FLAT_HOUR = 20
WEEKEND_FLAT_MIN  = 30
ATR_PERIOD = 14
ATR_SL_MULT  = 1.5
ATR_TP1_MULT = 1.5     # 50% close at 1:1 risk/reward
ATR_BREAKOUT_MULT = 1.0  # tighter SL/TP for news breakout
EURUSD_POTENTIAL_FILTER = {
    "adr_period": 20,
    "atr_period": 14,
    "min_adr_pips": 45.0,
    "strong_adr_pips": 60.0,
    "min_session_range_pips": 30.0,
    "range_spent_ratio": 0.85,
    "min_rr": 1.5,
}

STRATEGY = SMACross(fast=5, slow=20)           # 1h early-exit MA only
STRATEGY_FOREX = Forex(                        # profile strategy: forex
    z_period=20, z_entry=2.0,
    adx_period=14, adx_threshold=25.0,
)
STRATEGY_CRYPTO = Crypto(period=20, adx_period=14, adx_threshold=25.0,
                         vol_ma=20, vol_mult=1.2, adx_rising_bars=5)  # matches backtest
STRATEGY_METALS_XAU = MetalsSession("XAUUSD")
STRATEGY_METALS_XAG = MetalsSession("XAGUSD")
STRATEGY_INDEX = BreakoutAdx(period=20, adx_period=14, adx_threshold=22.0, adx_rising_bars=3)
STRATEGY_ENERGY = BreakoutAdx(period=20, adx_period=14, adx_threshold=25.0, adx_rising_bars=3)
BREAKOUT_STRATEGY = NewsBreakout(period=8)     # 8 × 15min = 2h pre-news range

FOREX_SYMBOLS = {
    "NZD/CHF", "AUD/CHF", "NZD/JPY", "NZD/CAD",
    *MAJOR_SYMBOLS,   # majors restored alongside the intraday set — same Forex profile strategy
}

MT4_SYMBOL_MAP = {
    "BTC/USD": "BTCUSD",
    "ETH/USD": "ETHUSD",
    "XAU/USD": "XAUUSD",
    "XAG/USD": "XAGUSD",
    "NZD/CHF": "NZDCHF",
    "AUD/CHF": "AUDCHF",
    "NZD/JPY": "NZDJPY",
    "NZD/CAD": "NZDCAD",
    "BRENT": "BRENT",
    "WTI": "WTI",
    "USTEC": ".USTECHCash",   # RoboForex prefixes index CFDs with a dot
    "US500": ".US500Cash",
    "DE40": ".DE40Cash",
    "JP225": ".JP225Cash",
}

# Forex correlation is handled by per-currency net-exposure (see _correlated_conflict):
# every forex pair nets ±1 on its base/quote, and a signal is blocked once it would
# push |net| on any currency past CURRENCY_EXPOSURE_CAP. This replaces the old hand-
# written forex groups + inverse groups (measured: cap=2 beats them on PnL/drawdown).
# Non-forex assets have no base/quote currency, so they keep explicit groups here.
CURRENCY_EXPOSURE_CAP = 2  # max net positions per currency (e.g. EUR/USD + EUR/CHF longs ok, third blocked)

CORR_GROUPS = [
    {"XAU/USD", "XAG/USD"},        # положительная корреляция: блокировать одинаковые действия
    {"BRENT", "WTI"},               # нефть: один и тот же драйвер
    {"USTEC", "US500"},             # US indices: не дублировать один и тот же риск-on/off
]
_MT4_TO_PY = {mt4: py for py, mt4 in MT4_SYMBOL_MAP.items()}
_MT4_TO_PY.update({s.replace("/", ""): s for s in SYMBOL_GROUP})
_active_signals: dict[str, str] = {}   # symbol → "BUY" | "SELL"
_entry_prices: dict[str, float] = {}   # symbol → entry price
_day_start: dict = {"date": None, "balance": None}
_DAY_START_FILE = Path(__file__).resolve().parent / "logs" / "day_start.json"
_last_digest_date: date | None = None
_last_calendar_date: date | None = None
_last_journal_sync: float = 0.0
_last_learning_run: float = 0.0


def _active_symbols() -> list[str]:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return ALWAYS_SYMBOLS
    hour, minute = now.hour, now.minute
    if hour < 8 or hour >= 22:
        session = ASIAN_SYMBOLS                          # 22:00-08:00: XAU, XAG
    elif (hour > 12 or (hour == 12 and minute >= 30)) and hour < 21:
        session = LONDON_SYMBOLS + US_SYMBOLS            # 12:30-21:00: EUR, GBP, CHF + XAU
    elif hour >= 21:
        session = ASIAN_SYMBOLS                          # rollover hour: no new forex entries
    else:
        session = LONDON_SYMBOLS                         # 08:00-12:30: EUR, GBP, CHF
    return list(dict.fromkeys(ALWAYS_SYMBOLS + session))


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _load_day_start(today: date) -> bool:
    if _day_start["date"] == today and _day_start["balance"] is not None:
        return True
    try:
        data = json.loads(_DAY_START_FILE.read_text(encoding="utf-8"))
        saved_date = date.fromisoformat(data.get("date", ""))
        saved_balance = float(data["balance"])
    except Exception:
        return False
    if saved_date != today:
        return False
    _day_start["date"] = saved_date
    _day_start["balance"] = saved_balance
    print(f"Loaded day start balance: {saved_balance:.2f} ({saved_date.isoformat()} UTC)")
    return True


def _save_day_start(today: date, balance: float) -> None:
    try:
        _DAY_START_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DAY_START_FILE.write_text(
            json.dumps({"date": today.isoformat(), "balance": balance}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[WARN] could not persist day start balance: {e}")


def _daily_drawdown_hit() -> bool:
    today = _utc_today()
    try:
        balance = _get_balance()
    except RuntimeError as e:
        print(f"[WARN] drawdown check skipped: {e}")
        return False
    if not _load_day_start(today):
        _day_start["date"] = today
        _day_start["balance"] = balance
        _save_day_start(today, balance)
        print(f"New day — starting balance: {balance:.2f}")
        return False
    start = _day_start["balance"]
    loss_pct = (start - balance) / start
    if loss_pct >= DRAWDOWN_LIMIT:
        print(f"Daily drawdown limit hit: -{loss_pct*100:.1f}% (start={start:.2f}, now={balance:.2f})")
        return True
    return False


def _is_forex(symbol: str) -> bool:
    return SYMBOL_GROUP.get(symbol) in {"forex", "forex_cross"} and "/" in symbol


def _currency_net(extra: tuple[str, str] | None = None) -> dict[str, int]:
    """Net exposure per currency from open forex positions (+1 base, -1 quote per
    BUY; flipped for SELL). `extra` optionally adds a hypothetical (symbol, action)."""
    net: dict[str, int] = {}
    pairs = [(s, a) for s, a in _active_signals.items() if a in ("BUY", "SELL") and _is_forex(s)]
    if extra is not None:
        pairs.append(extra)
    for sym, act in pairs:
        base, quote = sym.split("/")
        s = 1 if act == "BUY" else -1
        net[base] = net.get(base, 0) + s
        net[quote] = net.get(quote, 0) - s
    return net


def _correlated_conflict(symbol: str, action: str) -> bool:
    # Forex: block once the entry would push net exposure on any currency past the cap
    # (catches both same-direction stacks and inverse stacks, e.g. BUY EUR/USD + SELL USD/CHF).
    if _is_forex(symbol):
        net = _currency_net(extra=(symbol, action))
        return any(abs(v) > CURRENCY_EXPOSURE_CAP for v in net.values())
    # Non-forex (metals, oil, indices): explicit same-direction groups.
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


def _mt4_symbol(symbol: str) -> str:
    return MT4_SYMBOL_MAP.get(symbol, symbol.replace("/", ""))


def _forex_pip_value_usd(symbol: str, entry: float) -> float:
    base, quote = symbol.split("/")
    if quote == "USD":
        return 10.0
    if quote == "JPY":
        return 1000.0 / entry
    if quote == "CHF":
        try:
            usdchf = fetch_ohlcv("USD/CHF", outputsize=1, interval="1h")["close"].iloc[-1]
        except Exception:
            raise RuntimeError(f"Could not fetch USD/CHF rate for {symbol} lot calculation")
        return 10.0 / usdchf
    if quote == "CAD":
        try:
            usdcad = fetch_ohlcv("USD/CAD", outputsize=1, interval="1h")["close"].iloc[-1]
        except Exception:
            raise RuntimeError(f"Could not fetch USD/CAD rate for {symbol} lot calculation")
        return 10.0 / usdcad
    return PIP_CONFIG.get(symbol, {"pip_value": 10.0})["pip_value"]


def _calc_lots(entry: float, sl: float, symbol: str) -> float:
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return MIN_LOTS
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    sl_pips = sl_distance / cfg["pip_size"]
    if SYMBOL_GROUP.get(symbol) in {"forex", "forex_cross"} and "/" in symbol:
        pip_value = _forex_pip_value_usd(symbol, entry)
    else:
        pip_value = cfg["pip_value"]
    balance = _get_balance()
    risk_amount = balance * rules_for(symbol)["risk_pct"]
    lots = risk_amount / (sl_pips * pip_value)
    lots = round(lots, 2)
    return max(MIN_LOTS, min(MAX_LOTS, lots))


def _atr(df: pd.DataFrame) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean().iloc[-1]


def _daily_from_intraday(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    tmp["date"] = tmp.index.date
    return tmp.groupby("date").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        bars=("close", "count"),
    )


def _true_range_pips(daily: pd.DataFrame, pip_size: float) -> pd.Series:
    prev_close = daily["close"].shift(1)
    tr = pd.concat([
        daily["high"] - daily["low"],
        (daily["high"] - prev_close).abs(),
        (daily["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr / pip_size


def _breakout_in_direction(df: pd.DataFrame, signal: int, lookback: int) -> bool:
    if df.empty or len(df) < lookback + 2:
        return False
    history = df.iloc[-lookback - 1:-1]
    close = df["close"].iloc[-1]
    if signal == 1:
        return close > history["high"].max()
    if signal == -1:
        return close < history["low"].min()
    return False


def _eurusd_potential_filter(signal: int, df_entry: pd.DataFrame,
                             sl_mult: float, tp_mult: float,
                             tp_price: float | None,
                             in_news_window: bool) -> tuple[bool, str]:
    symbol = "EUR/USD"
    cfg = EURUSD_POTENTIAL_FILTER
    pip_size = PIP_CONFIG[symbol]["pip_size"]

    try:
        df_1h = fetch_ohlcv(symbol, outputsize=1200, interval="1h")
    except Exception as e:
        return False, f"EUR/USD potential unavailable: H1 fetch failed ({e})"

    daily = _daily_from_intraday(df_1h)
    today_key = df_1h.index[-1].date()
    if today_key not in daily.index:
        return False, "EUR/USD potential unavailable: current day missing from H1 history"

    complete = daily[(daily.index < today_key) & (daily["bars"] >= 8)]
    if len(complete) + 1 < cfg["adr_period"] + 1:
        return False, "EUR/USD potential unavailable: not enough H1 daily history"

    if len(complete) < cfg["adr_period"]:
        return False, "EUR/USD potential unavailable: not enough completed days"

    adr20 = ((complete["high"] - complete["low"]) / pip_size).tail(cfg["adr_period"]).mean()
    atr14 = _true_range_pips(complete, pip_size).tail(cfg["atr_period"]).mean()
    expected_pips = max(float(adr20), float(atr14))
    today = daily.loc[today_key]
    today_range_pips = float((today["high"] - today["low"]) / pip_size)

    h1_breakout = _breakout_in_direction(df_1h, signal, lookback=20)
    try:
        df_15m = fetch_ohlcv(symbol, outputsize=160, interval="15min")
    except Exception:
        m15_breakout = False
    else:
        m15_breakout = _breakout_in_direction(df_15m, signal, lookback=32)

    expanded = today_range_pips >= cfg["min_session_range_pips"]
    strong_setup = expanded and (h1_breakout or m15_breakout or in_news_window)

    if adr20 < cfg["min_adr_pips"]:
        return False, (
            f"EUR/USD ADR20={adr20:.1f}p < {cfg['min_adr_pips']:.0f}p; low intraday potential"
        )
    if adr20 < cfg["strong_adr_pips"] and not strong_setup:
        return False, (
            f"EUR/USD ADR20={adr20:.1f}p needs strong setup; "
            f"day_range={today_range_pips:.1f}p h1_breakout={h1_breakout} m15_breakout={m15_breakout}"
        )
    if today_range_pips >= expected_pips * cfg["range_spent_ratio"]:
        return False, (
            f"EUR/USD range mostly spent: {today_range_pips:.1f}p/"
            f"{expected_pips:.1f}p expected"
        )

    if len(df_entry) < ATR_PERIOD + 2:
        return False, "EUR/USD potential unavailable: not enough entry-frame bars"
    entry = df_entry["close"].iloc[-1]
    atr = _atr(df_entry)
    if pd.isna(atr) or atr <= 0:
        return False, "EUR/USD potential unavailable: ATR invalid"

    sl_pips = sl_mult * atr / pip_size
    if tp_price is not None and ((signal == 1 and tp_price > entry) or (signal == -1 and tp_price < entry)):
        target_pips = abs(tp_price - entry) / pip_size
    else:
        target_pips = tp_mult * atr / pip_size

    remaining_pips = max(expected_pips - today_range_pips, 0.0)
    usable_pips = min(target_pips, remaining_pips)
    required_pips = cfg["min_rr"] * sl_pips
    if usable_pips < required_pips:
        return False, (
            f"EUR/USD target potential too small: usable={usable_pips:.1f}p "
            f"< {cfg['min_rr']:.1f}R={required_pips:.1f}p "
            f"(sl={sl_pips:.1f}p target={target_pips:.1f}p remaining={remaining_pips:.1f}p)"
        )

    return True, (
        f"ADR20={adr20:.1f}p ATR14={atr14:.1f}p day={today_range_pips:.1f}p "
        f"remaining={remaining_pips:.1f}p h1_breakout={h1_breakout} m15_breakout={m15_breakout}"
    )


def send_signal(td_symbol: str, action: str, df: pd.DataFrame, size_mult: float = 1.0,
                sl_mult: float = ATR_SL_MULT, tp_mult: float = ATR_TP1_MULT,
                tp_price: float | None = None):
    mt4_symbol = _mt4_symbol(td_symbol)
    entry = df["close"].iloc[-1]
    atr = _atr(df)

    if action == "BUY":
        sl  = round(entry - sl_mult * atr, 5)
        if tp_price is not None and tp_price > entry:
            tp1 = tp_price
        else:
            tp1 = round(entry + tp_mult * atr, 5)
    elif action == "SELL":
        sl  = round(entry + sl_mult * atr, 5)
        if tp_price is not None and tp_price < entry:
            tp1 = tp_price
        else:
            tp1 = round(entry - tp_mult * atr, 5)
    else:
        sl = tp1 = 0.0

    base_lots = round(_calc_lots(entry, sl, td_symbol) * size_mult, 2)
    size_note = f" [×{size_mult} sentiment]" if size_mult != 1.0 else ""

    try:
        resp = _bridge_session.post(f"{BRIDGE_URL}/signal", json={
            "symbol": mt4_symbol, "action": action,
            "lots": base_lots, "sl": sl, "tp": tp1,
        }, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] signal POST failed for {td_symbol}: {e}")
        return
    _active_signals[td_symbol] = action
    _entry_prices[td_symbol] = entry
    tp_note = " [fib]" if tp_price is not None and tp1 == tp_price else ""
    print(f"{td_symbol}: {action} | lots={base_lots}{size_note} | SL={sl:.5f} TP={tp1:.5f}{tp_note}")


def _send_close(symbol: str, reason: str):
    mt4_symbol = _mt4_symbol(symbol)
    try:
        resp = _bridge_session.post(f"{BRIDGE_URL}/signal", json={
            "symbol": mt4_symbol, "action": "CLOSE",
            "lots": 0.01, "sl": 0.0, "tp": 0.0,
        }, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"{symbol}: failed to send CLOSE — {e}")
        return
    _active_signals[symbol] = "NONE"
    _entry_prices.pop(symbol, None)
    print(f"{symbol}: CLOSE — {reason}")


def _weekend_flat_now() -> bool:
    """True while forex/metals are closed: Fri 20:30 UTC → Sun ~21:00 UTC.
    Crypto trades 24/7 and is exempt (see _close_all_positions exclude)."""
    now = datetime.now(timezone.utc)
    wd = now.weekday()  # Mon=0 … Sun=6
    if wd == 4:  # Friday
        return now.hour > WEEKEND_FLAT_HOUR or (
            now.hour == WEEKEND_FLAT_HOUR and now.minute >= WEEKEND_FLAT_MIN
        )
    if wd == 5:  # Saturday — fully closed
        return True
    if wd == 6:  # Sunday — closed until forex reopens ~21:00 UTC
        return now.hour < 21
    return False


def _close_all_positions(reason: str, exclude: set | None = None):
    exclude = exclude or set()
    for symbol, action in list(_active_signals.items()):
        if symbol in exclude:
            continue
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
    """Keep the loop alive: crypto is 24/7, sessions gate the other symbols."""
    return


# One-shot reminder: on/after this date, ping Telegram once that the intraday
# surprise layer runs on a price proxy, and a calendar-with-actual subscription
# (Finnhub / TradingEconomics) would enable exact "actual vs forecast".
SUBS_REMINDER_DATE = date(2026, 7, 3)
SUBS_REMINDER_MARKER = Path(__file__).resolve().parent / "logs" / "calendar_actual_reminder.sent"
SUBS_REMINDER_TEXT = (
    "🔔 Напоминание: внутридневной surprise-слой работает по РЕАКЦИИ ЦЕНЫ (прокси). "
    "Для точного «факт vs прогноз» нужна подписка на эконом-календарь с actual "
    "(Finnhub / TradingEconomics). Захочешь подключать — скажи Claude, добавим "
    "разбор actual в bias/surprise.py."
)


def _maybe_send_subscription_reminder() -> None:
    """Fire once on/after SUBS_REMINDER_DATE, then never again (marker file)."""
    if _utc_today() < SUBS_REMINDER_DATE or SUBS_REMINDER_MARKER.exists():
        return
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": SUBS_REMINDER_TEXT},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] subscription reminder send failed: {e}")
        return
    try:
        SUBS_REMINDER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SUBS_REMINDER_MARKER.write_text(_utc_today().isoformat(), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] could not persist reminder marker: {e}")
    print("Subscription reminder sent → Telegram")


def _run_learning_report() -> None:
    global _last_learning_run
    try:
        run_learning()
        _last_learning_run = time.time()
    except Exception as e:
        print(f"[learning] report failed: {e}")


def trading_loop():
    global _last_digest_date, _last_calendar_date, _last_journal_sync, _last_learning_run
    while True:
        logger.info("Starting new poll cycle...")
        _sleep_until_open()
        today = _utc_today()
        if datetime.now(timezone.utc).hour == 5 and _last_calendar_date != today:
            _last_calendar_date = today
            threading.Thread(target=send_calendar_to_telegram, daemon=True).start()

        if datetime.now(timezone.utc).hour == 6 and _last_digest_date != today:
            _last_digest_date = today
            threading.Thread(target=run_digest, daemon=True).start()

        if time.time() - _last_journal_sync >= 3600:
            new_trades = journal_sync()
            _last_journal_sync = time.time()
            if new_trades or time.time() - _last_learning_run >= 21600:
                threading.Thread(target=_run_learning_report, daemon=True).start()

        _maybe_send_subscription_reminder()

        _load_active_signals()

        weekend = _weekend_flat_now()
        if weekend:
            to_flat = [s for s, a in _active_signals.items()
                       if a in ("BUY", "SELL") and s not in set(ALWAYS_SYMBOLS)]
            if to_flat:
                logger.info(f"weekend-flat active — closing {to_flat}")
            _close_all_positions("weekend flat — forex/metals closed", exclude=set(ALWAYS_SYMBOLS))

        drawdown_hit = _daily_drawdown_hit()
        symbols = list(ALWAYS_SYMBOLS) if weekend else _active_symbols()
        news_windows = {
            symbol: is_high_impact_active(symbol)
            for symbol in symbols
        }
        in_news_cycle = any(active for active, _ in news_windows.values())
        mode = "BREAKOUT/M15" if in_news_cycle else "PROFILE/H4"
        weekend_tag = " [weekend: crypto only]" if weekend else ""
        print(f"Session symbols: {symbols} [{mode}]{weekend_tag}{' [drawdown: new entries blocked]' if drawdown_hit else ''}")
        for symbol in symbols:
            try:
                asset_profile = SYMBOL_GROUP.get(symbol)
                in_news_window, news_event = news_windows.get(symbol, (False, ""))

                if _active_signals.get(symbol) in ("BUY", "SELL"):
                    try:
                        df_1h = fetch_ohlcv(symbol, outputsize=50, interval="1h")
                    except Exception as e:
                        print(f"{symbol}: early-exit check skipped — 1h data unavailable: {e}")
                        if asset_profile == "metal":
                            try:
                                df_4h_exit = fetch_ohlcv(symbol, outputsize=50, interval="4h")
                            except Exception as fallback_error:
                                print(f"{symbol}: early-exit fallback skipped — 4h data unavailable: {fallback_error}")
                            else:
                                if _check_early_exit(symbol, df_4h_exit):
                                    continue
                    else:
                        if _check_early_exit(symbol, df_1h):
                            continue

                if drawdown_hit:
                    continue

                if in_news_window:
                    print(f"{symbol}: news breakout window — {news_event}")
                    df_signal = fetch_ohlcv(symbol, outputsize=20, interval="15min")
                    signal = BREAKOUT_STRATEGY.generate_signal(df_signal)
                    sl_mult = tp_mult = ATR_BREAKOUT_MULT
                    tp_price = None
                else:
                    df_h4 = fetch_ohlcv(symbol, outputsize=221, interval="4h")
                    # Drop the last (forming) bar so signal is based on closed bars only
                    df_closed = df_h4.iloc[:-1]
                    df_signal = df_closed
                    if symbol in FOREX_SYMBOLS:
                        signal = STRATEGY_FOREX.generate_signal(df_closed, symbol=symbol)
                    elif asset_profile == "crypto":
                        signal = STRATEGY_CRYPTO.generate_signal(df_closed)
                    elif asset_profile == "metal":
                        if symbol == "XAG/USD":
                            df_xau_h4 = fetch_ohlcv("XAU/USD", outputsize=221, interval="4h")
                            signal = STRATEGY_METALS_XAG.generate_signal(df_closed, df_xau=df_xau_h4.iloc[:-1])
                        else:
                            signal = STRATEGY_METALS_XAU.generate_signal(df_closed)
                    elif asset_profile == "index":
                        signal = STRATEGY_INDEX.generate_signal(df_closed)
                    elif asset_profile == "energy":
                        signal = STRATEGY_ENERGY.generate_signal(df_closed)
                    else:
                        signal = 0
                    rules = rules_for(symbol)
                    sl_mult = rules["sl_mult"]
                    tp_mult = rules["tp_mult"]
                    tp_price = None

                if signal == 0:
                    print(f"{symbol}: no signal")
                    continue

                # market structure filter — trend-following gate; skip for
                # mean-reverting forex engines (they buy dips / sell rallies, so
                # blocking BUY in LH/LL kills their edge — see backtest 2026-06-05)
                mean_reverting = symbol in FOREX_SYMBOLS and STRATEGY_FOREX.is_mean_reverting(symbol)
                if not in_news_window and not mean_reverting:
                    struct = market_structure(df_closed)
                    if signal == 1 and struct == -1:
                        print(f"{symbol}: BUY blocked — bearish structure (LH/LL)")
                        continue
                    if signal == -1 and struct == 1:
                        print(f"{symbol}: SELL blocked — bullish structure (HH/HL)")
                        continue
                if not in_news_window:
                    tp_price = fib_tp(df_closed, signal, level=1.272) if asset_profile != "metal" else None

                # Fear & Greed filter — crypto only, trend-following mode
                # backtest shows: buy in Greed(≥50)=69%win, Neutral=29%win → block neutral/fear longs
                if asset_profile == "crypto" and not in_news_window:
                    fg = get_fg_value(datetime.now(timezone.utc))
                    if fg is not None:
                        if signal == 1 and fg < 50:
                            print(f"{symbol}: BUY blocked — F&G={fg} (Fear/Neutral, no bullish momentum)")
                            continue
                        if signal == -1 and fg >= 50:
                            print(f"{symbol}: SELL blocked — F&G={fg} (Greed/Neutral, no bearish momentum)")
                            continue
                    print(f"{symbol}: F&G={fg} — {'allowed' if fg is not None else 'unavailable, skipping filter'}")

                if not in_news_window:
                    blocked, event_title = is_high_impact_soon(symbol)
                    if blocked:
                        print(f"{symbol}: blocked — high-impact event: {event_title}")
                        continue

                action = "BUY" if signal == 1 else "SELL"
                if _active_signals.get(symbol) == action:
                    print(f"{symbol}: {action} уже активен — пропуск")
                    continue

                if symbol == "EUR/USD":
                    entry_df = df_signal if in_news_window else df_h4
                    allowed, reason = _eurusd_potential_filter(
                        signal, entry_df, sl_mult, tp_mult, tp_price, in_news_window
                    )
                    if not allowed:
                        print(f"{symbol}: {action} blocked — {reason}")
                        continue
                    print(f"{symbol}: intraday potential OK — {reason}")

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

                bias = resolve_bias(symbol, action)
                if not bias.allow:
                    print(f"{symbol}: {action} blocked — {bias.reason}")
                    continue
                if bias.size_mult != 1.0:
                    size_mult *= bias.size_mult
                    print(f"{symbol}: {bias.reason}")

                if _correlated_conflict(symbol, action):
                    print(f"{symbol}: {action} blocked by correlation")
                    continue

                # Pass df_h4 (with forming bar) so ATR/entry use the latest price
                send_signal(symbol, action, df_h4 if not in_news_window else df_signal,
                            size_mult=size_mult, sl_mult=sl_mult, tp_mult=tp_mult,
                            tp_price=tp_price)

            except Exception as e:
                print(f"{symbol}: error — {e}")
        interval = POLL_INTERVAL_NEWS if in_news_cycle else POLL_INTERVAL
        print(f"Next poll in {interval}s {'[news breakout window]' if in_news_cycle else ''}")
        time.sleep(interval)


def _load_active_signals():
    try:
        resp = _bridge_session.get(f"{BRIDGE_URL}/positions", timeout=3)
        resp.raise_for_status()
        positions = resp.json()
    except Exception as e:
        print(f"[WARN] position reconciliation failed: {e}")
        return

    live_signals: dict[str, str] = {}
    live_entries: dict[str, float] = {}
    for pos in positions:
        symbol = _MT4_TO_PY.get(pos.get("symbol", ""))
        action = pos.get("action")
        if symbol and action in ("BUY", "SELL"):
            live_signals[symbol] = action
            open_price = pos.get("open_price")
            if open_price:
                live_entries[symbol] = float(open_price)

    stale = {
        symbol: action
        for symbol, action in _active_signals.items()
        if action in ("BUY", "SELL") and symbol not in live_signals
    }

    _active_signals.clear()
    _active_signals.update(live_signals)
    _entry_prices.clear()
    _entry_prices.update(live_entries)

    if live_signals or stale:
        stale_note = f"; cleared stale={stale}" if stale else ""
        print(f"Reconciled {len(live_signals)} open positions: {live_signals}{stale_note}")


def _clear_signal_files():
    all_symbols = list(dict.fromkeys(ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS + US_SYMBOLS))
    for symbol in all_symbols:
        mt4_symbol = _mt4_symbol(symbol)
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
    if datetime.now(timezone.utc).weekday() >= 5:
        all_symbols = ALWAYS_SYMBOLS
    else:
        all_symbols = list(dict.fromkeys(ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS + US_SYMBOLS))
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


def main():
    if _port_in_use():
        print("ERROR: port 8000 already in use — another run_mt4.py is running. Aborting.")
        sys.exit(1)
    threading.Thread(target=run_server, daemon=True).start()
    print(f"MT4 bridge running at {BRIDGE_URL}")
    print("Symbols:", list(dict.fromkeys(ALWAYS_SYMBOLS + ASIAN_SYMBOLS + LONDON_SYMBOLS + US_SYMBOLS)))
    time.sleep(1)  # wait for server to start
    _clear_signal_files()
    _data_check()
    _load_active_signals()
    journal_sync()
    journal_stats()
    _run_learning_report()
    trading_loop()


if __name__ == "__main__":
    main()
