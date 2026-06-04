"""
Compare exit logic: ATR vs structure/Fibonacci for SL and trailing.

Question: is ATR-based SL + Chandelier trailing actually better than a
structural / Fibonacci alternative, or is it just untested convention?

Same signals, sizing and profiles as backtest_2w (config/profiles.py is the
single source of truth). The difference: this runs a BAR-BY-BAR simulation
with a moving stop, so trailing variants are evaluated on the real path
inside each trade (the TP/SL-only backtests can't do that).

Two independent axes:

  Initial SL:
    atr    — entry ∓ sl_mult * ATR                      (current live rule)
    swing  — beyond the last swing low/high + 0.25*ATR  (structural stop)

  Trailing:
    none       — fixed SL, no trail
    chandelier — SL = extreme_since_entry ∓ 2*ATR, updated on H4 close (current live rule)
    fib        — once price has run R = 1*ATR in favour, pull SL to the
                 0.618 retracement of the move from entry to the running extreme

TP is fib_tp(1.272) for non-metals, ATR*tp_mult for metals — same as live.
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.crypto import Crypto
from strategy.forex import Forex
from strategy.metals import MetalsSession
from strategy.structure import fib_tp
from config.profiles import PIP_CONFIG, MIN_LOTS, MAX_LOTS, rules_for

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/CHF", "USD/JPY",
    "AUD/USD", "EUR/CHF", "USD/CAD",
    "XAU/USD", "XAG/USD",
    "BTC/USD", "ETH/USD",
]
FOREX_SYMBOLS = {"EUR/USD", "GBP/USD", "USD/CHF", "EUR/CHF", "AUD/USD", "USD/JPY", "USD/CAD"}
CRYPTO_SYMBOLS = {"BTC/USD", "ETH/USD"}

STRATEGY_FOREX = Forex(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0)
STRATEGY_CRYPTO = Crypto(period=20, adx_period=14, adx_threshold=25.0,
                         vol_ma=20, vol_mult=1.2, adx_rising_bars=5)
STRATEGY_METALS_XAU = MetalsSession("XAUUSD")
STRATEGY_METALS_XAG = MetalsSession("XAGUSD")

ATR_PERIOD   = 14
SWING_LOOKBACK = 10        # bars to look back for structural swing
SWING_BUFFER_ATR = 0.25    # extra room beyond the swing
CHANDELIER_ATR_MULT = 2.0
FIB_TRIGGER_ATR = 1.0      # start fib-trailing after price runs this far
FIB_RETRACE = 0.618        # pull SL to this retracement of the run
import os
WINDOW_H4    = int(os.environ.get("WINDOW_H4", "84"))   # bars to trade over
WARMUP_H4    = 250
TOTAL_H4     = WINDOW_H4 + WARMUP_H4
INITIAL_BALANCE = 10_000.0


def _atr_series(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry, sl, symbol, balance):
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    if sl_pips == 0:
        return MIN_LOTS
    risk_pct = rules_for(symbol)["risk_pct"]
    return max(MIN_LOTS, min(MAX_LOTS, round(balance * risk_pct / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots, symbol):
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def _profit_factor(pnl):
    gross_l = pnl[pnl <= 0].abs().sum()
    return float("inf") if gross_l == 0 else pnl[pnl > 0].sum() / gross_l


def _max_drawdown(pnls):
    cum = 0.0; peak = 0.0; mdd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def _initial_sl(df, i, entry, atr_val, direction, sl_mode, sl_mult):
    if sl_mode == "atr":
        return entry - sl_mult * atr_val if direction == 1 else entry + sl_mult * atr_val
    # structural: beyond the last swing low/high in the lookback window (closed bars)
    window = df.iloc[max(0, i - SWING_LOOKBACK):i]
    buf = SWING_BUFFER_ATR * atr_val
    if direction == 1:
        return window["low"].min() - buf
    return window["high"].max() + buf


def _trail_sl(sl, direction, entry, extreme, atr_val, trail_mode):
    """Return the trailed SL (only ever tightened) given the running extreme."""
    if trail_mode == "none":
        return sl
    if trail_mode == "chandelier":
        cand = (extreme - CHANDELIER_ATR_MULT * atr_val if direction == 1
                else extreme + CHANDELIER_ATR_MULT * atr_val)
    else:  # fib: pull to 0.618 retracement of entry->extreme, once R reached
        run = (extreme - entry) * direction
        if run < FIB_TRIGGER_ATR * atr_val:
            return sl
        cand = (entry + (1 - FIB_RETRACE) * (extreme - entry) if direction == 1
                else entry - (1 - FIB_RETRACE) * (entry - extreme))
    # never loosen
    return max(sl, cand) if direction == 1 else min(sl, cand)


# pairs that run with breakeven on, per chandelier_trailing memory
BREAKEVEN_SYMBOLS = {"EUR/USD", "USD/CHF", "EUR/CHF"}
BREAKEVEN_ATR_MULT = 1.0


def backtest_symbol(symbol, df, sl_mode, trail_mode, df_xau=None):
    if symbol in FOREX_SYMBOLS:
        strategy = STRATEGY_FOREX
    elif symbol in CRYPTO_SYMBOLS:
        strategy = STRATEGY_CRYPTO
    elif symbol == "XAG/USD":
        strategy = STRATEGY_METALS_XAG
    else:
        strategy = STRATEGY_METALS_XAU

    rules = rules_for(symbol)
    sl_mult, tp_mult = rules["sl_mult"], rules["tp_mult"]
    is_metal = symbol in {"XAU/USD", "XAG/USD"}
    atr = _atr_series(df)
    use_be = symbol in BREAKEVEN_SYMBOLS
    pnls = []
    in_trade = False
    balance = INITIAL_BALANCE
    start_i = max(WARMUP_H4, len(df) - WINDOW_H4)
    sl = tp = entry = direction = extreme = lots = entry_atr = 0.0
    partial_done = False

    for i in range(start_i, len(df)):
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            atr_val = atr.iloc[i - 1]
            extreme = max(extreme, h) if direction == 1 else min(extreme, l)

            if trail_mode == "live":
                # Phase 1: ride fixed SL until TP1 (50% close). SL priority on tie.
                if not partial_done:
                    hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
                    hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
                    if hit_sl:
                        p = _pnl(entry, sl, direction, lots, symbol)
                        balance += p; pnls.append(p); in_trade = False; continue
                    if hit_tp:
                        # close 50% at TP1, lock that PnL; runner continues on half lots
                        p = _pnl(entry, tp, direction, lots / 2, symbol)
                        balance += p; pnls.append(p)
                        lots = round(lots / 2, 2)
                        partial_done = True
                        if use_be:  # breakeven becomes eligible immediately post-TP1
                            sl = max(sl, entry) if direction == 1 else min(sl, entry)
                    continue
                # Phase 2 (runner): breakeven (tick) + chandelier (bar close)
                if use_be and not pd.isna(atr_val):
                    moved = (extreme - entry) * direction
                    if moved >= BREAKEVEN_ATR_MULT * atr_val:
                        sl = max(sl, entry) if direction == 1 else min(sl, entry)
                if not pd.isna(atr_val):
                    sl = _trail_sl(sl, direction, entry, extreme, atr_val, "chandelier")
                hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
                if hit_sl:
                    p = _pnl(entry, sl, direction, lots, symbol)
                    balance += p; pnls.append(p); in_trade = False
                continue

            # static / chandelier / fib trailing to a single full exit
            if not pd.isna(atr_val):
                sl = _trail_sl(sl, direction, entry, extreme, atr_val, trail_mode)
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_sl or hit_tp:
                exit_p = sl if hit_sl else tp  # SL priority on tie (conservative)
                p = _pnl(entry, exit_p, direction, lots, symbol)
                balance += p
                pnls.append(p)
                in_trade = False
            continue

        if i == 0:
            continue
        df_closed = df.iloc[:i]
        if symbol == "XAG/USD" and df_xau is not None:
            xau_closed = df_xau[df_xau.index <= df_closed.index[-1]]
            signal = strategy.generate_signal(df_closed, df_xau=xau_closed)
        else:
            signal = strategy.generate_signal(df_closed, symbol=symbol)
        if signal == 0:
            continue

        entry = df["close"].iloc[i - 1]
        atr_val = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl = _initial_sl(df, i, entry, atr_val, signal, sl_mode, sl_mult)
        if (signal == 1 and sl >= entry) or (signal == -1 and sl <= entry):
            sl = entry - sl_mult * atr_val if signal == 1 else entry + sl_mult * atr_val

        if is_metal:
            tp = entry + tp_mult * atr_val if signal == 1 else entry - tp_mult * atr_val
        else:
            tp = fib_tp(df_closed, signal, lookback=20, level=1.272)
            if (signal == 1 and tp <= entry) or (signal == -1 and tp >= entry):
                tp = entry + tp_mult * atr_val if signal == 1 else entry - tp_mult * atr_val

        lots = _lot_size(entry, sl, symbol, balance)
        direction = signal
        extreme = entry
        entry_atr = atr_val
        partial_done = False
        in_trade = True

    return pnls


def main():
    print(f"Exit-logic comparison — bar-by-bar, {WINDOW_H4} H4 bars + {WARMUP_H4} warmup\n"
          f"Same signals/sizing/profiles as live. SL priority on tie.\n")
    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            data[sym] = fetch_ohlcv(sym, outputsize=TOTAL_H4 + 1, interval="4h")
            print(f"ok ({len(data[sym])} bars)")
        except Exception as e:
            print(f"FAIL — {e}")
        time.sleep(1)

    df_xau = data.get("XAU/USD")
    combos = [
        ("atr",   "live"),         # ← real EA: 50% at TP1 → breakeven + chandelier on runner
        ("atr",   "none"),         # fixed SL, aim full position at TP1.272
        ("atr",   "chandelier"),
        ("atr",   "fib"),
        ("swing", "none"),
        ("swing", "live"),
    ]

    print(f"\n{'SL':<7} {'Trail':<11} {'Tr':>4} {'Win%':>6} {'PnL $':>10} "
          f"{'Avg $':>8} {'PF':>6} {'MaxLoss':>9} {'MaxDD':>9}")
    print("─" * 76)
    for sl_mode, trail_mode in combos:
        all_pnls = []
        for sym, df in data.items():
            if len(df) < WARMUP_H4 + 10:
                continue
            all_pnls.extend(backtest_symbol(sym, df, sl_mode, trail_mode, df_xau=df_xau))
        if not all_pnls:
            print(f"{sl_mode:<7} {trail_mode:<11} {'—':>4}")
            continue
        s = pd.Series(all_pnls)
        wins = (s > 0).sum()
        pf = _profit_factor(s)
        tag = " ← live EA" if (sl_mode, trail_mode) == ("atr", "live") else ""
        print(f"{sl_mode:<7} {trail_mode:<11} {len(s):>4} {wins/len(s)*100:>5.0f}% "
              f"{s.sum():>+10.2f} {s.mean():>+8.2f} {pf:>6.2f} "
              f"{s.min():>+9.2f} {_max_drawdown(all_pnls):>+9.2f}{tag}")

    # ── per-symbol breakdown: live rule vs the two fib variants ───────────────
    detail = [("atr", "live"), ("atr", "none")]
    for sl_mode, trail_mode in detail:
        label = f"{sl_mode}+{trail_mode}"
        live = " (live EA)" if (sl_mode, trail_mode) == ("atr", "live") else ""
        print(f"\nPer-symbol — {label}{live}")
        print(f"  {'Symbol':<9} {'Tr':>3} {'Win%':>6} {'PnL $':>10} {'PF':>6}")
        print("  " + "─" * 40)
        for sym in SYMBOLS:
            df = data.get(sym)
            if df is None or len(df) < WARMUP_H4 + 10:
                continue
            pnls = backtest_symbol(sym, df, sl_mode, trail_mode, df_xau=df_xau)
            if not pnls:
                print(f"  {sym:<9} {'–':>3}")
                continue
            s = pd.Series(pnls)
            w = (s > 0).sum()
            print(f"  {sym:<9} {len(s):>3} {w/len(s)*100:>5.0f}% "
                  f"{s.sum():>+10.2f} {_profit_factor(s):>6.2f}")


if __name__ == "__main__":
    main()
