"""
Test different Gold/Silver Ratio thresholds on Silver strategy.

Thresholds to compare:
  A) ratio_high=80, ratio_low=65  (current)
  B) ratio_high=85, ratio_low=60  (tighter — closer to article's 60-70 mean)
  C) ratio_high=90, ratio_low=55  (article's extreme levels only)
  D) no ratio filter               (baseline)

Session: London + US/CME (our best combo from previous backtest)
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.metals.silver import Silver

ATR_PERIOD  = 14
ATR_SL_MULT = 2.0
ATR_TP_MULT = 2.0
OUTPUTSIZE  = 2200
ALLOWED_HOURS = {8, 12, 16}  # London + US/CME


def _atr_series(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest(df_xag, strategy, df_xau=None):
    atr = _atr_series(df_xag)
    trades = []
    in_trade = False
    direction = sl = tp = 0.0

    for i in range(60, len(df_xag) - 1):
        bar = df_xag.iloc[i]
        if in_trade:
            if direction == 1:
                if bar["low"] <= sl:   trades.append(-1); in_trade = False; continue
                if bar["high"] >= tp:  trades.append(1);  in_trade = False; continue
            else:
                if bar["high"] >= sl:  trades.append(-1); in_trade = False; continue
                if bar["low"] <= tp:   trades.append(1);  in_trade = False; continue
            continue

        if df_xag.index[i].hour not in ALLOWED_HOURS:
            continue

        xag_slice = df_xag.iloc[:i + 1]
        if df_xau is not None:
            xau_slice = df_xau[df_xau.index <= xag_slice.index[-1]]
            sig = strategy.generate_signal(xag_slice, df_xau=xau_slice if len(xau_slice) > 0 else None)
        else:
            sig = strategy.generate_signal(xag_slice)

        if sig == 0:
            continue
        entry = df_xag["close"].iloc[i]
        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl = entry - ATR_SL_MULT * atr_val if sig == 1 else entry + ATR_SL_MULT * atr_val
        tp = entry + ATR_TP_MULT * atr_val  if sig == 1 else entry - ATR_TP_MULT * atr_val
        direction = sig
        in_trade  = True

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "expectancy": 0.0, "buy": 0, "sell": 0}
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
            print(f"ok ({len(data[sym])} bars)")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(15)

    df_xag = data["XAG/USD"]
    df_xau = data.get("XAU/USD")

    ratio = df_xau["close"].reindex(df_xag.index, method="ffill") / df_xag["close"]
    print(f"\nGold/Silver ratio  min={ratio.min():.1f}  max={ratio.max():.1f}  "
          f"mean={ratio.mean():.1f}  current={ratio.iloc[-1]:.1f}")
    print(f"  >90: {(ratio > 90).sum()} bars  |  80-90: {((ratio >= 80) & (ratio <= 90)).sum()} bars  "
          f"|  65-80: {((ratio >= 65) & (ratio < 80)).sum()} bars  |  <65: {(ratio < 65).sum()} bars\n")

    configs = [
        ("No ratio filter   ", Silver(ratio_high=999, ratio_low=0), None),
        ("ratio 80/65 (cur) ", Silver(ratio_high=80,  ratio_low=65), df_xau),
        ("ratio 85/60       ", Silver(ratio_high=85,  ratio_low=60), df_xau),
        ("ratio 90/55       ", Silver(ratio_high=90,  ratio_low=55), df_xau),
    ]

    print(f"Session: London(08) + US/CME(12,16)    SL/TP = {ATR_SL_MULT}/{ATR_TP_MULT} ATR\n")
    print(f"{'Config':<22} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}")
    print("-" * 52)

    for name, strat, xau in configs:
        r = backtest(df_xag, strat, df_xau=xau)
        if r["trades"] == 0:
            print(f"{name:<22} {'—':>7} {'—':>7} {'—':>12}")
        else:
            print(f"{name:<22} {r['trades']:>7} {r['win_rate']:>6.1f}% {r['expectancy']:>+11.3f}R")
