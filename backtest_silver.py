"""
Backtest Silver (XAG/USD) strategy variants on ~1 year of H4.

Compares:
  1. EmaAtr          — previous best for XAG (London +0.300R)
  2. Silver (no ratio) — EMA21/55 + RSI cross 50 + ADX
  3. Silver (ratio)    — same + Gold/Silver ratio bias filter

ATR_SL_MULT = 2.0 (wider — silver is ~2× more volatile than gold)
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.metals.ema_atr import EmaAtr
from strategy.metals.silver import Silver

ATR_PERIOD  = 14
ATR_SL_MULT = 2.0   # wider for silver
ATR_TP_MULT = 2.0
OUTPUTSIZE  = 2200

SESSIONS = {
    "London (08)   ": {8},
    "US/CME (12,16)": {12, 16},
    "Lnd + US      ": {8, 12, 16},
    "All sessions  ": None,
}


def _atr_series(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest(df_xag: pd.DataFrame, strategy, allowed_hours: set | None,
             df_xau: pd.DataFrame | None = None) -> dict:
    atr = _atr_series(df_xag)
    trades = []
    in_trade = False
    direction = sl = tp = 0.0

    for i in range(60, len(df_xag) - 1):
        bar = df_xag.iloc[i]

        if in_trade:
            if direction == 1:
                if bar["low"] <= sl:
                    trades.append(-1); in_trade = False; continue
                if bar["high"] >= tp:
                    trades.append(1);  in_trade = False; continue
            else:
                if bar["high"] >= sl:
                    trades.append(-1); in_trade = False; continue
                if bar["low"] <= tp:
                    trades.append(1);  in_trade = False; continue
            continue

        bar_hour = df_xag.index[i].hour
        if allowed_hours is not None and bar_hour not in allowed_hours:
            continue

        xag_slice = df_xag.iloc[:i + 1]

        if df_xau is not None:
            # align XAU slice to same timestamp range
            ts = xag_slice.index[-1]
            xau_slice = df_xau[df_xau.index <= ts]
            sig = strategy.generate_signal(xag_slice, df_xau=xau_slice if len(xau_slice) > 0 else None)
        else:
            sig = strategy.generate_signal(xag_slice)

        if sig == 0:
            continue

        entry   = df_xag["close"].iloc[i]
        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl        = entry - ATR_SL_MULT * atr_val if sig == 1 else entry + ATR_SL_MULT * atr_val
        tp        = entry + ATR_TP_MULT * atr_val  if sig == 1 else entry - ATR_TP_MULT * atr_val
        direction = sig
        in_trade  = True

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "expectancy": 0.0}
    wins  = trades.count(1)
    total = len(trades)
    return {
        "trades":     total,
        "win_rate":   round(wins / total * 100, 1),
        "expectancy": round((wins * ATR_TP_MULT - (total - wins) * ATR_SL_MULT) / total, 3),
    }


if __name__ == "__main__":
    print(f"Fetching {OUTPUTSIZE} H4 bars...")
    data = {}
    for sym in ["XAG/USD", "XAU/USD"]:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            data[sym] = fetch_ohlcv(sym, outputsize=OUTPUTSIZE, interval="4h")
            print(f"ok ({len(data[sym])} bars, {data[sym].index[0].date()} – {data[sym].index[-1].date()})")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(15)

    df_xag = data["XAG/USD"]
    df_xau = data.get("XAU/USD")

    # Gold/Silver ratio overview
    if df_xau is not None:
        ratio = df_xau["close"].reindex(df_xag.index, method="ffill") / df_xag["close"]
        print(f"\nGold/Silver ratio — min: {ratio.min():.1f}  max: {ratio.max():.1f}  "
              f"current: {ratio.iloc[-1]:.1f}  mean: {ratio.mean():.1f}")

    strategies = {
        "EmaAtr (prev best)   ": (EmaAtr(fast=9, slow=21), None),
        "Silver (no ratio)    ": (Silver(), None),
        "Silver (ratio filter)": (Silver(), df_xau),
    }

    print()
    print(f"{'Strategy':<24} {'Session':<22} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}  "
          f"  [SL/TP = {ATR_SL_MULT}/{ATR_TP_MULT} ATR]")
    print("-" * 82)

    for name, (strat, xau) in strategies.items():
        for session_name, hours in SESSIONS.items():
            r = backtest(df_xag, strat, hours, df_xau=xau)
            if r["trades"] == 0:
                print(f"{name:<24} {session_name:<22} {'—':>7} {'—':>7} {'—':>12}")
            else:
                print(f"{name:<24} {session_name:<22} {r['trades']:>7} "
                      f"{r['win_rate']:>6.1f}% {r['expectancy']:>+11.3f}R")
        print()
