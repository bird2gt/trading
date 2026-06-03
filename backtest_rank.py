"""
Rank the live universe by realised strategy P&L over 12-month and 6-month windows.
Same engine as backtest_2w.py (signal on closed H4 bars, ATR SL/TP from
config/profiles.py — the single source of truth) but:
  * trades are bounded by a calendar window (365d / 182d), not a fixed bar count,
  * reports avg trade $, profit factor and expectancy alongside win%.

Scope = the 11 symbols the bot actually trades. Indices/oil/extra crosses are not
wired into the strategy dispatch or PIP_CONFIG, so they cannot be backtested here.
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.crypto import Crypto
from strategy.forex import Forex
from strategy.metals import MetalsSession

from config.profiles import PIP_CONFIG, MIN_LOTS, MAX_LOTS, rules_for

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/CHF", "USD/JPY",
    "AUD/USD", "EUR/CHF", "USD/CAD",
    "XAU/USD", "XAG/USD",
    "BTC/USD", "ETH/USD",
]
FOREX_SYMBOLS  = {"EUR/USD", "GBP/USD", "USD/CHF", "EUR/CHF", "AUD/USD", "USD/JPY", "USD/CAD"}
CRYPTO_SYMBOLS = {"BTC/USD", "ETH/USD"}

STRATEGY_FOREX  = Forex(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0)
STRATEGY_XAU    = MetalsSession("XAUUSD")
STRATEGY_XAG    = MetalsSession("XAGUSD")
STRATEGY_CRYPTO = Crypto(period=20, adx_period=14, adx_threshold=25.0,
                         vol_ma=20, vol_mult=1.2, adx_rising_bars=5)

ATR_PERIOD      = 14
WARMUP_H4       = 250
INITIAL_BALANCE = 10_000.0
FETCH_BARS      = 2600  # forex/metals reach ~13 months; crypto capped by source


def _strategy_tag(symbol: str) -> str:
    if symbol in FOREX_SYMBOLS:
        return STRATEGY_FOREX.strategy_name(symbol)
    if symbol in CRYPTO_SYMBOLS:
        return "BreakoutADX(25/r5)"
    return "MetalsSession"


def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry: float, sl: float, symbol: str, balance: float) -> float:
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    if sl_pips == 0:
        return MIN_LOTS
    risk_pct = rules_for(symbol)["risk_pct"]
    return max(MIN_LOTS, min(MAX_LOTS, round(balance * risk_pct / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry: float, exit_: float, direction: int, lots: float, symbol: str) -> float:
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def backtest_window(symbol, df_h4, window_start, df_xau_h4=None):
    """Trades whose ENTRY falls on/after window_start. Indicators still use full history."""
    if symbol in FOREX_SYMBOLS:
        strategy = STRATEGY_FOREX
    elif symbol in CRYPTO_SYMBOLS:
        strategy = STRATEGY_CRYPTO
    elif symbol == "XAG/USD":
        strategy = STRATEGY_XAG
    else:
        strategy = STRATEGY_XAU

    rules   = rules_for(symbol)
    sl_mult, tp_mult = rules["sl_mult"], rules["tp_mult"]
    atr     = _atr_series(df_h4)
    trades  = []
    in_trade = False
    balance = INITIAL_BALANCE

    for i in range(max(WARMUP_H4, 1), len(df_h4)):
        bar_time = df_h4.index[i]

        if in_trade:
            h, l = df_h4["high"].iloc[i], df_h4["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p = tp if hit_tp else sl
                pnl = _pnl(entry_price, exit_p, direction, lots, symbol)
                balance += pnl
                trades.append({"pnl": pnl, "win": hit_tp})
                in_trade = False
            continue

        if bar_time < window_start:
            continue

        df_closed = df_h4.iloc[:i]  # closed bars only — no repaint
        if symbol == "XAG/USD" and df_xau_h4 is not None:
            xau_closed = df_xau_h4[df_xau_h4.index <= df_closed.index[-1]]
            signal = strategy.generate_signal(df_closed, df_xau=xau_closed)
        else:
            signal = strategy.generate_signal(df_closed, symbol=symbol)
        if signal == 0:
            continue

        entry_price = df_h4["close"].iloc[i - 1]
        atr_val = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl = entry_price - sl_mult * atr_val if signal == 1 else entry_price + sl_mult * atr_val
        tp = entry_price + tp_mult * atr_val if signal == 1 else entry_price - tp_mult * atr_val
        lots = _lot_size(entry_price, sl, symbol, balance)
        direction = signal
        in_trade = True

    return trades


def _summary(trades):
    n = len(trades)
    if n == 0:
        return None
    wins  = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    pnl = gross_w - gross_l
    return {
        "trades": n,
        "win_rate": len(wins) / n * 100,
        "pnl": pnl,
        "avg": pnl / n,
        "pf": pf,
    }


def run_window(label, days, data, df_xau_h4):
    now = pd.Timestamp.now().tz_localize(None)
    window_start = now - pd.Timedelta(days=days)
    print(f"\n{'='*72}\n  {label}  (entries since {window_start.date()})\n{'='*72}")
    print(f"{'Symbol':<10} {'Strategy':<20} {'Tr':>3} {'Win%':>6} {'PnL $':>9} {'Avg $':>8} {'PF':>6}")
    print("─" * 72)

    rows = []
    for sym in SYMBOLS:
        df_h4 = data.get(sym)
        if df_h4 is None or len(df_h4) < WARMUP_H4 + 10:
            print(f"{sym:<10} {_strategy_tag(sym):<20} {'– no data':>3}")
            continue
        covered = df_h4.index[0] <= window_start
        s = _summary(backtest_window(sym, df_h4, window_start, df_xau_h4))
        tag = _strategy_tag(sym)
        if s is None:
            note = "" if covered else "  (partial coverage)"
            print(f"{sym:<10} {tag:<20} {0:>3} {'—':>6} {'0.00':>9} {'—':>8} {'—':>6}{note}")
            continue
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        note = "" if covered else "  *partial"
        print(f"{sym:<10} {tag:<20} {s['trades']:>3} {s['win_rate']:>5.0f}% "
              f"{s['pnl']:>+9.2f} {s['avg']:>+8.2f} {pf:>6}{note}")
        rows.append((sym, s, covered))

    print("─" * 72)
    ranked = sorted(rows, key=lambda r: r[1]["avg"], reverse=True)
    print(f"  RANK by avg trade $:")
    for n, (sym, s, covered) in enumerate(ranked, 1):
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        flag = "" if covered else " *partial"
        print(f"   {n:>2}. {sym:<9} avg {s['avg']:>+7.2f}$  PF {pf:>5}  "
              f"win {s['win_rate']:>3.0f}%  ({s['trades']} tr, tot {s['pnl']:>+8.2f}$){flag}")
    return ranked


def main():
    print(f"Fetching {FETCH_BARS} H4 bars per symbol (one-time)...\n")
    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            df = fetch_ohlcv(sym, interval="4h", outputsize=FETCH_BARS)
            data[sym] = df
            print(f"ok  {len(df)} bars  from {df.index[0].date()}")
        except Exception as e:
            print(f"FAIL — {type(e).__name__}: {e}")
        time.sleep(1)

    df_xau_h4 = data.get("XAU/USD")
    run_window("12 MONTHS", 365, data, df_xau_h4)
    run_window("6 MONTHS", 182, data, df_xau_h4)
    print("\nNote: crypto history is source-capped (~6 mo via Binance); 12-mo crypto is partial.")
    print("Scope = 11 live-traded symbols. Indices/oil are not in the strategy dispatch.")


if __name__ == "__main__":
    main()
