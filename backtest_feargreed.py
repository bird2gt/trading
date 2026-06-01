"""
Backtest: Fear & Greed Index as trade filter for BreakoutADX (BTC+ETH, 1 year H4).

Filter modes tested:
  none        — baseline, no F&G filter
  trend       — buy only when F&G >= 50 (greed), sell only when F&G < 50 (fear)
  contr_soft  — block buy when F&G > 65, block sell when F&G < 35  (fade moderate extreme)
  contr_hard  — block buy when F&G > 75, block sell when F&G < 25  (fade only extremes)

Verdict: which mode improves win rate and PnL vs baseline?
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.crypto.breakout import Breakout
from analytics.fear_greed import fetch_history, get_value

SYMBOLS   = ["BTC/USD", "ETH/USD"]
TEST_H4   = 2190   # ~1 year 24/7
WARMUP_H4 = 300
TOTAL_H4  = TEST_H4 + WARMUP_H4

ATR_PERIOD = 14
SL_MULT    = 1.5
TP_MULT    = 2.0
INITIAL    = 10_000.0
RISK_PCT   = 0.02

STRATEGY = Breakout(period=20, adx_period=14, adx_threshold=25.0,
                    vol_ma=20, vol_mult=1.2, adx_rising_bars=5)

MODES = {
    "none":       lambda fg, sig: True,
    "trend":      lambda fg, sig: (fg is None) or (sig == 1 and fg >= 50) or (sig == -1 and fg < 50),
    "contr_soft": lambda fg, sig: (fg is None) or not ((sig == 1 and fg > 65) or (sig == -1 and fg < 35)),
    "contr_hard": lambda fg, sig: (fg is None) or not ((sig == 1 and fg > 75) or (sig == -1 and fg < 25)),
}


def _atr(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot(entry: float, sl: float, balance: float) -> float:
    d = abs(entry - sl)
    return max(0.01, min(2.0, round(balance * RISK_PCT / d, 2))) if d else 0.01


def backtest_one(symbol: str, df: pd.DataFrame, fg_df: pd.DataFrame, allow_fn) -> list[dict]:
    atr      = _atr(df)
    trades   = []
    in_trade = False
    balance  = INITIAL
    start_i  = max(WARMUP_H4, len(df) - TEST_H4)

    for i in range(start_i, len(df)):
        bar_time = df.index[i]

        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p  = tp if hit_tp else sl
                pnl     = round((exit_p - entry) * direction * lots, 2)
                balance += pnl
                trades.append({
                    "symbol": symbol, "dir": direction, "date": entry_t.date(),
                    "pnl": pnl, "result": "W" if hit_tp else "L",
                    "fg": fg_at_entry,
                })
                in_trade = False
            continue

        df_closed = df.iloc[:i]
        signal    = STRATEGY.generate_signal(df_closed)
        if signal == 0:
            continue

        fg_val = get_value(bar_time)
        if not allow_fn(fg_val, signal):
            continue

        entry   = df["close"].iloc[i - 1]
        atr_val = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl  = entry - SL_MULT * atr_val if signal == 1 else entry + SL_MULT * atr_val
        tp  = entry + TP_MULT * atr_val if signal == 1 else entry - TP_MULT * atr_val
        lots       = _lot(entry, sl, balance)
        direction  = signal
        entry_t    = bar_time
        fg_at_entry = fg_val
        in_trade   = True

    return trades


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "win_pct": 0, "pnl": 0, "per_trade": 0}
    n   = len(trades)
    w   = sum(1 for t in trades if t["result"] == "W")
    pnl = sum(t["pnl"] for t in trades)
    return {"n": n, "win_pct": w / n * 100, "pnl": pnl, "per_trade": pnl / n}


def main():
    print(f"Fear & Greed filter backtest — 1 year H4 (BTC+ETH)\n"
          f"Strategy: BreakoutADX(adx≥25, rising≥5)  SL={SL_MULT}×ATR  TP={TP_MULT}×ATR\n")

    print("Fetching market data...")
    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            df = fetch_ohlcv(sym, outputsize=TOTAL_H4 + 1, interval="4h")
            data[sym] = df
            print(f"ok  [{len(df)} bars  {df.index[0].date()} → {df.index[-1].date()}]")
        except Exception as e:
            print(f"FAIL — {e}")
        time.sleep(1)

    print("\nFetching Fear & Greed history...")
    try:
        fg_df = fetch_history(500)
        print(f"  ok  [{len(fg_df)} days  {fg_df.index[0]} → {fg_df.index[-1]}]")
        print(f"  Latest: {fg_df.iloc[-1]['value']} ({fg_df.iloc[-1]['value_classification']})")
    except Exception as e:
        print(f"  FAIL — {e}")
        return

    # ── run all modes ──────────────────────────────────────────────────────────
    results = {}
    for mode, allow_fn in MODES.items():
        trades = []
        for sym, df in data.items():
            if len(df) < WARMUP_H4 + 20:
                continue
            trades.extend(backtest_one(sym, df, fg_df, allow_fn))
        results[mode] = trades

    # ── summary table ──────────────────────────────────────────────────────────
    baseline_pnl = _stats(results["none"])["pnl"]
    print(f"\n{'Mode':<14} {'Trades':>6} {'Win%':>6} {'PnL $':>9} {'$/tr':>7} {'vs base':>8}")
    print("─" * 56)
    for mode, trades in results.items():
        s = _stats(trades)
        if s["n"] == 0:
            print(f"{mode:<14} {'–':>6}")
            continue
        delta = s["pnl"] - baseline_pnl if mode != "none" else 0
        marker = " ◄" if mode != "none" and delta == max(
            _stats(results[m])["pnl"] - baseline_pnl
            for m in results if m != "none"
        ) else ""
        print(f"{mode:<14} {s['n']:>6} {s['win_pct']:>5.0f}% "
              f"{s['pnl']:>+9.2f} {s['per_trade']:>+7.2f} "
              f"{delta:>+8.2f}{marker}")

    # ── per-symbol breakdown for best mode ────────────────────────────────────
    best_mode = max((m for m in results if m != "none"),
                    key=lambda m: _stats(results[m])["pnl"])
    print(f"\nBest mode: {best_mode}")
    print(f"\n{'Mode':<14} {'Symbol':<10} {'Trades':>6} {'Win%':>6} {'PnL $':>9}")
    print("─" * 48)
    for mode in [best_mode, "none"]:
        df_t = pd.DataFrame(results[mode]) if results[mode] else pd.DataFrame()
        for sym in SYMBOLS:
            sub = df_t[df_t["symbol"] == sym] if not df_t.empty else pd.DataFrame()
            if sub.empty:
                print(f"{mode:<14} {sym:<10} {'–':>6}")
                continue
            w = (sub["pnl"] > 0).sum()
            n = len(sub)
            print(f"{mode:<14} {sym:<10} {n:>6} {w/n*100:>5.0f}% {sub['pnl'].sum():>+9.2f}")

    # ── F&G distribution of filtered-out trades ───────────────────────────────
    baseline_trades = results["none"]
    if baseline_trades:
        df_base = pd.DataFrame(baseline_trades)
        print(f"\nF&G distribution at signal time (baseline {len(baseline_trades)} trades):")
        bins = [0, 25, 45, 55, 75, 100]
        labels = ["Extreme Fear(0-25)", "Fear(25-45)", "Neutral(45-55)", "Greed(55-75)", "Extreme Greed(75-100)"]
        df_base["fg_safe"] = df_base["fg"].fillna(-1).astype(int)
        df_base["fg_bin"] = pd.cut(df_base["fg_safe"].clip(0, 99), bins=bins, labels=labels, right=False)
        for label in labels:
            sub = df_base[df_base["fg_bin"] == label]
            if sub.empty:
                continue
            w = (sub["pnl"] > 0).sum()
            n = len(sub)
            print(f"  {label:<24} {n:>3} trades  {w/n*100:>4.0f}% win  {sub['pnl'].sum():>+9.2f}$")


if __name__ == "__main__":
    main()
