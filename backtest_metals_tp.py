"""
Compare ATR TP vs Fibonacci TP (1.272) for metals.

Strategy: MetalsSession (XAU=ZScoreAdxTrend, XAG=Silver+ratio)
SL: fixed ATR multiplier (XAU=1.5, XAG=2.0)
TP variants:
  - ATR TP  : entry ± sl_mult * ATR  (1:1 RR)
  - Fib TP  : fib_tp(lookback=20, level=1.272)
  - Fib 1.618: fib_tp(lookback=20, level=1.618)  (aggressive)
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.metals.session import MetalsSession
from strategy.structure import fib_tp

ATR_PERIOD = 14
OUTPUTSIZE = 2200
ALLOWED_HOURS = {8, 12, 16}  # London + US/CME

METAL_PARAMS = {
    "XAU/USD": {"sl_mult": 1.5, "tp_mult": 1.5},
    "XAG/USD": {"sl_mult": 2.0, "tp_mult": 2.0},
}


def _atr_series(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest(df: pd.DataFrame, strategy, sl_mult: float, tp_mode: str,
             df_xau: pd.DataFrame | None = None, is_xag: bool = False) -> dict:
    atr = _atr_series(df)
    trades = []
    in_trade = False
    direction = sl = tp = 0.0

    for i in range(60, len(df) - 1):
        bar = df.iloc[i]

        if in_trade:
            if direction == 1:
                if bar["low"] <= sl:   trades.append(-1); in_trade = False; continue
                if bar["high"] >= tp:  trades.append(1);  in_trade = False; continue
            else:
                if bar["high"] >= sl:  trades.append(-1); in_trade = False; continue
                if bar["low"] <= tp:   trades.append(1);  in_trade = False; continue
            continue

        if df.index[i].hour not in ALLOWED_HOURS:
            continue

        df_slice = df.iloc[:i + 1]
        if is_xag and df_xau is not None:
            xau_slice = df_xau[df_xau.index <= df_slice.index[-1]]
            sig = strategy.generate_signal(df_slice, df_xau=xau_slice if len(xau_slice) > 0 else None)
        else:
            sig = strategy.generate_signal(df_slice)

        if sig == 0:
            continue

        entry   = df["close"].iloc[i]
        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl = entry - sl_mult * atr_val if sig == 1 else entry + sl_mult * atr_val

        if tp_mode == "atr":
            tp = entry + sl_mult * atr_val if sig == 1 else entry - sl_mult * atr_val
        elif tp_mode == "fib1.272":
            tp = fib_tp(df_slice, sig, lookback=20, level=1.272)
        elif tp_mode == "fib1.618":
            tp = fib_tp(df_slice, sig, lookback=20, level=1.618)

        # sanity: TP must be in the right direction
        if sig == 1 and tp <= entry:
            tp = entry + sl_mult * atr_val
        if sig == -1 and tp >= entry:
            tp = entry - sl_mult * atr_val

        direction = sig
        in_trade  = True

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "expectancy": 0.0, "avg_rr": 0.0}
    wins  = trades.count(1)
    total = len(trades)
    return {
        "trades":   total,
        "win_rate": round(wins / total * 100, 1),
        # expectancy in R using sl_mult as risk unit
        "expectancy": round((wins / total - (1 - wins / total)) * sl_mult, 3),
    }


if __name__ == "__main__":
    print(f"Fetching {OUTPUTSIZE} H4 bars...")
    data = {}
    for sym in ["XAU/USD", "XAG/USD"]:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            data[sym] = fetch_ohlcv(sym, outputsize=OUTPUTSIZE, interval="4h")
            print(f"ok ({len(data[sym])} bars)")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(15)

    strats = {
        "XAU/USD": (MetalsSession("XAUUSD"), False),
        "XAG/USD": (MetalsSession("XAGUSD"), True),
    }
    df_xau = data.get("XAU/USD")

    tp_modes = {
        "ATR (1:1 RR)  ": "atr",
        "Fib 1.272     ": "fib1.272",
        "Fib 1.618     ": "fib1.618",
    }

    print()
    print(f"{'Symbol':<10} {'TP mode':<16} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}")
    print("-" * 56)

    for sym, (strat, is_xag) in strats.items():
        p = METAL_PARAMS[sym]
        for tp_label, tp_mode in tp_modes.items():
            r = backtest(data[sym], strat, sl_mult=p["sl_mult"], tp_mode=tp_mode,
                         df_xau=df_xau, is_xag=is_xag)
            if r["trades"] == 0:
                print(f"{sym:<10} {tp_label:<16} {'—':>7} {'—':>7} {'—':>12}")
            else:
                print(f"{sym:<10} {tp_label:<16} {r['trades']:>7} "
                      f"{r['win_rate']:>6.1f}% {r['expectancy']:>+11.3f}R")
        print()
