import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.sma_cross import SMACross
from strategy.breakout import Breakout
from strategy.mean_reversion import MeanReversion

ATR_PERIOD   = 14
ATR_SL_MULT  = 1.5
ATR_TP1_MULT = 1.5
SYMBOLS      = ["BTC/USD", "XAU/USD", "XAG/USD", "EUR/USD", "USD/CHF"]
STRATEGIES   = {
    "SMA 10/30":    SMACross(fast=10, slow=30),
    "Breakout 20":  Breakout(period=20),
    "MeanRev BB":   MeanReversion(period=20, std_mult=2.0),
}
OUTPUTSIZE   = 1000  # ~6 months of H4


def _atr(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest(symbol: str, strategy, df_h4: pd.DataFrame, df_d1: pd.DataFrame) -> dict:
    atr_series = _atr(df_h4)
    trades = []
    in_trade = False

    for i in range(60, len(df_h4) - 10):
        if in_trade:
            high = df_h4["high"].iloc[i]
            low  = df_h4["low"].iloc[i]
            if direction == 1:
                if low <= sl:
                    trades.append(-1); in_trade = False
                elif high >= tp:
                    trades.append(1);  in_trade = False
            else:
                if high >= sl:
                    trades.append(-1); in_trade = False
                elif low <= tp:
                    trades.append(1);  in_trade = False
            continue

        df_slice = df_h4.iloc[:i + 1]
        bar_date = df_h4.index[i].date()
        df_d1_slice = df_d1[df_d1.index.date <= bar_date]

        signal = strategy.generate_signal(df_slice, df_trend=df_d1_slice if len(df_d1_slice) >= 55 else None)
        if signal == 0:
            continue

        entry = df_h4["close"].iloc[i]
        atr   = atr_series.iloc[i]
        if pd.isna(atr) or atr == 0:
            continue

        sl = entry - ATR_SL_MULT * atr if signal == 1 else entry + ATR_SL_MULT * atr
        tp = entry + ATR_TP1_MULT * atr if signal == 1 else entry - ATR_TP1_MULT * atr
        direction = signal
        in_trade  = True

    if not trades:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "expectancy": 0.0}

    wins  = trades.count(1)
    total = len(trades)
    return {
        "trades":     total,
        "wins":       wins,
        "losses":     total - wins,
        "win_rate":   round(wins / total * 100, 1),
        "expectancy": round((wins - (total - wins)) / total, 2),
    }


if __name__ == "__main__":
    print(f"Backtesting {OUTPUTSIZE} H4 bars (~6 months)\n")

    data = {}
    for sym in SYMBOLS:
        print(f"  Fetching {sym}...", end=" ", flush=True)
        try:
            data[sym] = (
                fetch_ohlcv(sym, outputsize=OUTPUTSIZE, interval="4h"),
                fetch_ohlcv(sym, outputsize=OUTPUTSIZE // 6, interval="1day"),
            )
            print("ok")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(20)

    print()
    print(f"{'Symbol':<10} {'Strategy':<14} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}")
    print("-" * 55)
    for sym, (df_h4, df_d1) in data.items():
        for strat_name, strategy in STRATEGIES.items():
            r = backtest(sym, strategy, df_h4, df_d1)
            print(f"{sym:<10} {strat_name:<14} {r['trades']:>7} "
                  f"{r['win_rate']:>6.1f}% {r['expectancy']:>+11.2f}R")
