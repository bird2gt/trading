"""Does CHF/JPY have a tradeable engine? It's the only non-traded pair that is
both reasonably independent (max corr +0.55 to NZD/JPY) and not dead-flat, so
it's the one expansion candidate worth a real backtest.

Same bar-by-bar sim and real EA exit as backtest_audusd.py (50% at TP1=fib1.272
→ breakeven → chandelier), so PF here is comparable to the rest of the book.

Data: CHF/JPY isn't in the live fetcher's symbol map, so we load the 12-month
H4 CSV captured in the 2026-06-03 universe research. JPY-pair pip config
(0.01 / $7) mirrors NZD/JPY in config.profiles.

Run:  python3 backtest/scratch/backtest_chfjpy.py
"""
import pandas as pd
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.forex.z_score_adx import ZScoreAdx
from strategy.forex.take_profit import AdxMa, TwoB
from strategy.structure import fib_tp, market_structure
from config.profiles import MIN_LOTS, MAX_LOTS

SYMBOL = "CHF/JPY"
CSV = "research/intraday_universe_2026-06-03/data/CHFJPY_4h.csv"
PIP = {"pip_size": 0.01, "pip_value": 7.0}   # JPY pair, same as NZD/JPY in config
RISK_PCT = 0.01                               # forex_cross risk
SL_MULT, TP_MULT = 1.5, 1.5                   # forex_cross defaults
ATR_PERIOD = 14
CHANDELIER_ATR_MULT = 2.0
BREAKEVEN_ATR_MULT = 1.0
WARMUP_H4 = 250
INITIAL_BALANCE = 10_000.0

CANDIDATES = {
    "AdxMa 21/20 (trend)":   AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
    "AdxMa 50/25 (trend)":   AdxMa(ma_period=50, adx_period=14, adx_threshold=25.0),
    "TwoB lookback20 (2B)":  TwoB(lookback=20),
    "BreakoutADX 30/20":     BreakoutAdx(period=30, adx_period=14, adx_threshold=20.0, adx_rising_bars=3),
    "ZScoreAdx 2.0/25 (MR)": ZScoreAdx(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0),
    "ZScoreAdx 1.5/20 (MR)": ZScoreAdx(z_period=20, z_entry=1.5, adx_period=14, adx_threshold=20.0),
}


def _atr_series(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry, sl, balance):
    sl_pips = abs(entry - sl) / PIP["pip_size"]
    if sl_pips == 0:
        return MIN_LOTS
    return max(MIN_LOTS, min(MAX_LOTS, round(balance * RISK_PCT / (sl_pips * PIP["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots):
    pips = (exit_ - entry) * direction / PIP["pip_size"]
    return round(pips * PIP["pip_value"] * lots, 2)


def _pf(s):
    gl = s[s <= 0].abs().sum()
    return float("inf") if gl == 0 else s[s > 0].sum() / gl


def _max_dd(pnls):
    cum = peak = mdd = 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    return mdd


def backtest(df, strategy):
    atr = _atr_series(df)
    pnls = []
    in_trade = partial_done = False
    balance = INITIAL_BALANCE
    sl = tp = entry = direction = extreme = lots = 0.0

    for i in range(WARMUP_H4, len(df)):
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

        df_closed = df.iloc[:i]
        sig = strategy.generate_signal(df_closed)
        if sig == 0:
            continue
        struct = market_structure(df_closed)
        if (sig == 1 and struct == -1) or (sig == -1 and struct == 1):
            continue

        entry = df["close"].iloc[i - 1]
        atr_val = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue
        sl = entry - SL_MULT * atr_val if sig == 1 else entry + SL_MULT * atr_val
        tp = fib_tp(df_closed, sig, lookback=20, level=1.272)
        if (sig == 1 and tp <= entry) or (sig == -1 and tp >= entry):
            tp = entry + TP_MULT * atr_val if sig == 1 else entry - TP_MULT * atr_val
        lots = _lot_size(entry, sl, balance)
        direction = sig; extreme = entry; partial_done = False; in_trade = True

    return pnls


def main():
    df = pd.read_csv(CSV, parse_dates=["datetime"]).set_index("datetime")
    print(f"CHF/JPY engine search — bar-by-bar, real EA exit, {len(df)} H4 bars "
          f"({df.index[0].date()} → {df.index[-1].date()})\n")
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


def split_check():
    """Out-of-sample sanity: does AdxMa 21/20 hold up in both halves of the year?"""
    df = pd.read_csv(CSV, parse_dates=["datetime"]).set_index("datetime")
    mid = len(df) // 2
    for label, strat in [("AdxMa 21/20", AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0)),
                          ("AdxMa 50/25", AdxMa(ma_period=50, adx_period=14, adx_threshold=25.0))]:
        print(f"\n{label}:")
        for name, sub in [("H1 (older)", df.iloc[:mid + WARMUP_H4]), ("H2 (recent)", df.iloc[mid - WARMUP_H4:])]:
            pnls = backtest(sub.reset_index().set_index("datetime"), strat)
            if not pnls:
                print(f"  {name:<12} no trades"); continue
            s = pd.Series(pnls)
            print(f"  {name:<12} {len(s):>3} tr  win {(s>0).mean()*100:>3.0f}%  "
                  f"PnL {s.sum():>+9.2f}  PF {_pf(s):>5.2f}")


if __name__ == "__main__" and __import__("sys").argv[-1] == "--split":
    split_check()
