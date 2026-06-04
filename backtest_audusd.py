"""Find a working AUD/USD strategy. The old BreakoutAdx was net-negative
(−$1.3k/12mo, PF<0.9) so it was disabled; user wants a new one.

Bar-by-bar sim with the real EA exit (50% at TP1=fib1.272 → breakeven →
chandelier on the runner) — same engine as backtest_exit_compare, so results
are comparable to the rest of the book. Profiles from config (single source).

Run:  WINDOW_H4=1950 python3 backtest_audusd.py
"""
import os
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.forex.z_score_adx import ZScoreAdx
from strategy.forex.take_profit import AdxMa, TwoB
from strategy.structure import fib_tp, market_structure
from config.profiles import PIP_CONFIG, MIN_LOTS, MAX_LOTS, rules_for

SYMBOL = "AUD/USD"
ATR_PERIOD = 14
CHANDELIER_ATR_MULT = 2.0
BREAKEVEN_ATR_MULT = 1.0
WINDOW_H4 = int(os.environ.get("WINDOW_H4", "1950"))
WARMUP_H4 = 250
INITIAL_BALANCE = 10_000.0

# Candidate engines to compare (label → strategy instance)
CANDIDATES = {
    "BreakoutADX 20/25 (old)": BreakoutAdx(period=20, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
    "BreakoutADX 30/20":       BreakoutAdx(period=30, adx_period=14, adx_threshold=20.0, adx_rising_bars=3),
    "AdxMa 21/20 (trend)":     AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
    "AdxMa 50/25 (trend)":     AdxMa(ma_period=50, adx_period=14, adx_threshold=25.0),
    "TwoB lookback20 (2B)":    TwoB(lookback=20),
    "ZScoreAdx 2.0/25 (MR)":   ZScoreAdx(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0),
    "ZScoreAdx 1.5/20 (MR)":   ZScoreAdx(z_period=20, z_entry=1.5, adx_period=14, adx_threshold=20.0),
}


def _atr_series(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry, sl, balance):
    cfg = PIP_CONFIG[SYMBOL]
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    if sl_pips == 0:
        return MIN_LOTS
    risk = rules_for(SYMBOL)["risk_pct"]
    return max(MIN_LOTS, min(MAX_LOTS, round(balance * risk / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots):
    cfg = PIP_CONFIG[SYMBOL]
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def _pf(s):
    gl = s[s <= 0].abs().sum()
    return float("inf") if gl == 0 else s[s > 0].sum() / gl


def _max_dd(pnls):
    cum = peak = mdd = 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    return mdd


def backtest(df, strategy):
    rules = rules_for(SYMBOL)
    sl_mult, tp_mult = rules["sl_mult"], rules["tp_mult"]
    atr = _atr_series(df)
    pnls = []
    in_trade = partial_done = False
    balance = INITIAL_BALANCE
    sl = tp = entry = direction = extreme = lots = 0.0
    start_i = max(WARMUP_H4, len(df) - WINDOW_H4)

    for i in range(start_i, len(df)):
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            atr_val = atr.iloc[i - 1]
            extreme = max(extreme, h) if direction == 1 else min(extreme, l)
            if not partial_done:
                hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
                hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
                if hit_sl:
                    pnls.append(_pnl(entry, sl, direction, lots)); in_trade = False; continue
                if hit_tp:
                    pnls.append(_pnl(entry, tp, direction, lots / 2))
                    lots = round(lots / 2, 2); partial_done = True
                continue
            if not pd.isna(atr_val):
                moved = (extreme - entry) * direction
                if moved >= BREAKEVEN_ATR_MULT * atr_val:
                    sl = max(sl, entry) if direction == 1 else min(sl, entry)
                cand = (extreme - CHANDELIER_ATR_MULT * atr_val if direction == 1
                        else extreme + CHANDELIER_ATR_MULT * atr_val)
                sl = max(sl, cand) if direction == 1 else min(sl, cand)
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            if hit_sl:
                pnls.append(_pnl(entry, sl, direction, lots)); in_trade = False
            continue

        if i == 0:
            continue
        df_closed = df.iloc[:i]
        sig = strategy.generate_signal(df_closed)
        if sig == 0:
            continue
        # same market-structure filter as live (non-metal path)
        struct = market_structure(df_closed)
        if (sig == 1 and struct == -1) or (sig == -1 and struct == 1):
            continue

        entry = df["close"].iloc[i - 1]
        atr_val = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue
        sl = entry - sl_mult * atr_val if sig == 1 else entry + sl_mult * atr_val
        tp = fib_tp(df_closed, sig, lookback=20, level=1.272)
        if (sig == 1 and tp <= entry) or (sig == -1 and tp >= entry):
            tp = entry + tp_mult * atr_val if sig == 1 else entry - tp_mult * atr_val
        lots = _lot_size(entry, sl, balance)
        direction = sig; extreme = entry; partial_done = False; in_trade = True

    return pnls


def main():
    print(f"AUD/USD strategy search — bar-by-bar, real EA exit, {WINDOW_H4} H4 bars + {WARMUP_H4} warmup\n")
    df = fetch_ohlcv(SYMBOL, outputsize=WINDOW_H4 + WARMUP_H4 + 1, interval="4h")
    print(f"Fetched {len(df)} bars, window from {df.index[-WINDOW_H4].date()}\n")

    print(f"{'Strategy':<26} {'Tr':>4} {'Win%':>6} {'PnL $':>10} {'Avg $':>8} {'PF':>6} {'MaxDD':>9}")
    print("-" * 74)
    for label, strat in CANDIDATES.items():
        pnls = backtest(df, strat)
        if not pnls:
            print(f"{label:<26} {'0':>4}  (no trades)")
            continue
        s = pd.Series(pnls)
        w = (s > 0).sum()
        print(f"{label:<26} {len(s):>4} {w/len(s)*100:>5.0f}% {s.sum():>+10.2f} "
              f"{s.mean():>+8.2f} {_pf(s):>6.2f} {_max_dd(pnls):>+9.2f}")


if __name__ == "__main__":
    main()
