"""
Validate MetalsSession (session-switching) vs baselines.

Baselines:
  - OldMetals      : mean-reversion, ADX<25, all sessions (current production)
  - ZScoreAdxTrend : momentum, all sessions
  - EmaAtr         : EMA cross + ATR, all sessions
  - MetalsSession  : session-switching dispatcher (new)
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.metals.metals import Metals as OldMetals
from strategy.metals.zscore_adx_trend import ZScoreAdxTrend
from strategy.metals.ema_atr import EmaAtr
from strategy.metals.session import MetalsSession

ATR_PERIOD  = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 1.5
OUTPUTSIZE  = 2200

SYMBOLS = ["XAU/USD", "XAG/USD"]


def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest(df: pd.DataFrame, strategy) -> dict:
    atr = _atr_series(df)
    trades = []
    in_trade = False
    direction = sl = tp = 0.0

    for i in range(50, len(df) - 1):
        bar = df.iloc[i]

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

        sig = strategy.generate_signal(df.iloc[:i + 1])
        if sig == 0:
            continue

        entry   = df["close"].iloc[i]
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
    data = {}
    print(f"Fetching {OUTPUTSIZE} H4 bars (~1 year)...")
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            data[sym] = fetch_ohlcv(sym, outputsize=OUTPUTSIZE, interval="4h")
            print(f"ok ({len(data[sym])} bars)")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(15)

    strategies = {
        "OldMetals (prod)  ": lambda sym: OldMetals(period=20, std_mult=2.0, adx_period=14, max_adx=25.0),
        "ZScoreAdxTrend    ": lambda sym: ZScoreAdxTrend(z_period=20, z_entry=1.5, adx_period=14, adx_threshold=20.0),
        "EmaAtr            ": lambda sym: EmaAtr(fast=9, slow=21, atr_period=14, atr_ma=20),
        "MetalsSession ★   ": lambda sym: MetalsSession(sym),
    }

    print()
    print(f"{'Symbol':<10} {'Strategy':<22} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}")
    print("-" * 62)

    for sym, df in data.items():
        for name, factory in strategies.items():
            r = backtest(df, factory(sym))
            if r["trades"] == 0:
                print(f"{sym:<10} {name:<22} {'—':>7} {'—':>7} {'—':>12}")
            else:
                print(f"{sym:<10} {name:<22} {r['trades']:>7} "
                      f"{r['win_rate']:>6.1f}% {r['expectancy']:>+11.3f}R")
        print()
