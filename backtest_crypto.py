"""
6-month crypto strategy research backtest.
Compares: SupertrendRsi | EmaRibbon | Breakout+ADX+Vol
H4 bars, 2% risk/trade, $10k balance.
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.crypto.supertrend_rsi import SupertrendRsi
from strategy.crypto.ema_ribbon import EmaRibbon
from strategy.crypto.breakout import Breakout

SYMBOLS = ["BTC/USD", "ETH/USD"]

STRATEGIES = {
    "SupertrendRSI": SupertrendRsi(atr_period=10, mult=3.0, rsi_period=14,
                                    rsi_long=55.0, rsi_short=45.0),
    "EmaRibbon":     EmaRibbon(fast=8, mid=21, slow=55, vol_ma=20, vol_mult=1.5),
    "BreakoutADX":   Breakout(period=20, adx_period=14, adx_threshold=25.0,
                               vol_ma=20, vol_mult=1.2, adx_rising_bars=5),
}

ATR_PERIOD      = 14
SL_MULT         = 1.5
TP_MULT         = 2.0   # 1:2 R:R — crypto moves more
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.02
PIP_SIZE        = 1.0
PIP_VALUE       = 1.0

# 6 months crypto H4 = ~1080 bars (24/7); 200 warmup
TEST_H4   = 1080
WARMUP_H4 = 200
TOTAL_H4  = TEST_H4 + WARMUP_H4


def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry: float, sl: float, balance: float) -> float:
    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        return 0.01
    return max(0.01, min(2.0, round(balance * RISK_PCT / (sl_dist * PIP_VALUE / PIP_SIZE), 2)))


def _pnl(entry: float, exit_: float, direction: int, lots: float) -> float:
    return round((exit_ - entry) * direction * lots, 2)


def backtest_one(symbol: str, strategy, df: pd.DataFrame) -> list[dict]:
    atr   = _atr_series(df)
    trades = []
    in_trade = False
    balance  = INITIAL_BALANCE
    start_i  = max(WARMUP_H4, len(df) - TEST_H4)

    for i in range(start_i, len(df)):
        bar_time = df.index[i]

        if in_trade:
            h = df["high"].iloc[i]
            l = df["low"].iloc[i]
            hit_sl = (direction ==  1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction ==  1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p = tp if hit_tp else sl
                pnl    = _pnl(entry_price, exit_p, direction, lots)
                balance += pnl
                trades.append({
                    "symbol":   symbol,
                    "entry_t":  entry_t,
                    "exit_t":   bar_time,
                    "dir":      "BUY" if direction == 1 else "SELL",
                    "entry":    entry_price,
                    "exit":     exit_p,
                    "pnl":      pnl,
                    "result":   "WIN" if hit_tp else "LOSS",
                    "balance":  round(balance, 2),
                })
                in_trade = False
            continue

        df_closed = df.iloc[:i]
        signal    = strategy.generate_signal(df_closed)
        if signal == 0:
            continue

        entry_price = df["close"].iloc[i - 1]
        atr_val     = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl  = entry_price - SL_MULT * atr_val if signal ==  1 else entry_price + SL_MULT * atr_val
        tp  = entry_price + TP_MULT * atr_val if signal ==  1 else entry_price - TP_MULT * atr_val
        lots     = _lot_size(entry_price, sl, balance)
        direction = signal
        entry_t   = bar_time
        in_trade  = True

    return trades


def main():
    print(f"6-month crypto backtest  ({TEST_H4} H4 bars + {WARMUP_H4} warmup)\n"
          f"SL={SL_MULT}×ATR  TP={TP_MULT}×ATR  Risk=2%  Balance=$10k\n")

    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            df = fetch_ohlcv(sym, outputsize=TOTAL_H4 + 1, interval="4h")
            data[sym] = df
            print(f"ok  [{len(df)} bars  from {df.index[0].date()} to {df.index[-1].date()}]")
        except Exception as e:
            print(f"FAIL — {e}")
        time.sleep(1)

    all_results = {}  # strategy_name -> list of trades

    for strat_name, strategy in STRATEGIES.items():
        trades = []
        for sym, df in data.items():
            if len(df) < WARMUP_H4 + 20:
                continue
            trades.extend(backtest_one(sym, strategy, df))
        all_results[strat_name] = trades

    # ── summary table ─────────────────────────────────────────────────────────
    print(f"\n{'Strategy':<16} {'Tr':>4} {'W':>4} {'L':>4} {'Win%':>6} {'PnL $':>9} {'Avg $':>7}")
    print("─" * 54)
    for name, trades in all_results.items():
        if not trades:
            print(f"{name:<16} {'–':>4}")
            continue
        df_t = pd.DataFrame(trades)
        w    = (df_t["pnl"] > 0).sum()
        n    = len(df_t)
        pnl  = df_t["pnl"].sum()
        print(f"{name:<16} {n:>4} {w:>4} {n-w:>4} {w/n*100:>5.0f}% "
              f"{pnl:>+9.2f} {pnl/n:>+7.2f}")
    print("─" * 54)

    # ── per-symbol breakdown ──────────────────────────────────────────────────
    print()
    for name, trades in all_results.items():
        if not trades:
            continue
        df_t = pd.DataFrame(trades)
        print(f"{name}:")
        for sym in SYMBOLS:
            sub = df_t[df_t["symbol"] == sym]
            if sub.empty:
                print(f"  {sym:<10} –")
                continue
            w   = (sub["pnl"] > 0).sum()
            n   = len(sub)
            pnl = sub["pnl"].sum()
            print(f"  {sym:<10} {n:>3} trades  {w/n*100:>4.0f}% win  {pnl:>+9.2f}$")
        print()

    # ── trade log for best strategy ───────────────────────────────────────────
    best_name = max(all_results, key=lambda k: sum(t["pnl"] for t in all_results[k]) if all_results[k] else -999)
    best = all_results[best_name]
    if best:
        print(f"Trade log — {best_name} (best PnL):")
        print(f"{'#':<3} {'Sym':<10} {'Dir':<5} {'Date':<12} {'Entry':>10} {'Exit':>10} {'PnL $':>9}  Result")
        print("─" * 66)
        for n, t in enumerate(best, 1):
            print(f"{n:<3} {t['symbol']:<10} {t['dir']:<5} {str(t['entry_t'].date()):<12} "
                  f"{t['entry']:>10.2f} {t['exit']:>10.2f} {t['pnl']:>+9.2f}  {t['result']}")
        print(f"\nFinal balance: ${best[-1]['balance']:,.2f}  "
              f"(Return: {(best[-1]['balance'] - INITIAL_BALANCE) / INITIAL_BALANCE * 100:+.1f}%)")


if __name__ == "__main__":
    main()
