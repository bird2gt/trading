"""
Backtest XAU/USD and XAG/USD using the Metals strategy,
split by trading session (entry hour filter on H4 bars).

Sessions (UTC):
  Asian  : bars at 20, 00, 04       (22:00-08:00)
  London : bars at 08               (08:00-12:00)
  US     : bars at 12, 16           (12:00-20:00)
  All    : no filter
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.metals.metals import Metals

ATR_PERIOD  = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 1.5
OUTPUTSIZE  = 2000  # ~1.4 years of H4

STRATEGY = Metals(period=20, std_mult=2.0, adx_period=14, max_adx=25.0)

SESSIONS = {
    "Asian  (22-08)": {20, 0, 4},
    "London (08-12)": {8},
    "US     (12-20)": {12, 16},
    "All sessions  ": None,
}


def _atr(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest_session(df: pd.DataFrame, allowed_hours: set | None) -> dict:
    atr_series = _atr(df)
    trades = []
    in_trade = False
    direction = 0
    sl = tp = 0.0

    for i in range(50, len(df) - 1):
        price_bar = df.iloc[i]

        if in_trade:
            if direction == 1:
                if price_bar["low"] <= sl:
                    trades.append(-1); in_trade = False; continue
                if price_bar["high"] >= tp:
                    trades.append(1);  in_trade = False; continue
            else:
                if price_bar["high"] >= sl:
                    trades.append(-1); in_trade = False; continue
                if price_bar["low"] <= tp:
                    trades.append(1);  in_trade = False; continue
            continue

        # session filter: check the bar's hour
        bar_hour = df.index[i].hour
        if allowed_hours is not None and bar_hour not in allowed_hours:
            continue

        signal = STRATEGY.generate_signal(df.iloc[:i + 1])
        if signal == 0:
            continue

        entry = df["close"].iloc[i]
        atr   = atr_series.iloc[i]
        if pd.isna(atr) or atr == 0:
            continue

        sl = entry - ATR_SL_MULT * atr if signal == 1 else entry + ATR_SL_MULT * atr
        tp = entry + ATR_TP_MULT * atr if signal == 1 else entry - ATR_TP_MULT * atr
        direction = signal
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
    symbols = ["XAU/USD", "XAG/USD"]
    data = {}

    print("Fetching data...")
    for sym in symbols:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            data[sym] = fetch_ohlcv(sym, outputsize=OUTPUTSIZE, interval="4h")
            print(f"ok ({len(data[sym])} bars)")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(15)

    print()
    print(f"{'Symbol':<10} {'Session':<22} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}")
    print("-" * 62)

    for sym, df in data.items():
        for session_name, hours in SESSIONS.items():
            r = backtest_session(df, hours)
            if r["trades"] == 0:
                print(f"{sym:<10} {session_name:<22} {'—':>7} {'—':>7} {'—':>12}")
            else:
                print(f"{sym:<10} {session_name:<22} {r['trades']:>7} "
                      f"{r['win_rate']:>6.1f}% {r['expectancy']:>+11.3f}R")
        print()
