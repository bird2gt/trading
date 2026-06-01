"""
Compare 3 strategies for XAU/USD and XAG/USD on ~1 year of H4 data.
Split by session (London 08:00, US/Chicago 12:00+16:00, Asian 20:00+00:00+04:00).

Strategy 1 — Asian Range Breakout
  At London open (H4 bar hour=8): trade breakout of Asian session range (bars at 20,0,4).

Strategy 2 — ZScore ADX Trend (momentum, ADX≥20)
  Z-score momentum: price extended above/below mean WITH strong trend (ADX≥20).
  Opposite of current Metals mean-reversion logic.

Strategy 3 — EMA Cross + ATR expansion
  Fast EMA crosses slow EMA while ATR > ATR moving average (expanding volatility).
"""
import time
import pandas as pd
import numpy as np
from history.fetcher import fetch_ohlcv

ATR_PERIOD  = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 1.5
OUTPUTSIZE  = 2200   # ~1 year of H4 bars

SESSIONS = {
    "Asian  (22-08)": {20, 0, 4},
    "London (08-12)": {8},
    "US/CME (12-20)": {12, 16},
    "All sessions  ": None,
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _adx_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff(); dn = -l.diff()
    plus_dm  = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a   = 1 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
    dx  = (100 * (pdi - mdi).abs() / (pdi + mdi)).fillna(0)
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx, pdi, mdi


# ── strategy signal functions (bar-by-bar on df slice) ───────────────────────

def signal_asian_breakout(df: pd.DataFrame, i: int) -> int:
    """Only fires at London open (bar hour == 8). Range = prior 3 H4 asian bars."""
    bar_hour = df.index[i].hour
    if bar_hour != 8:
        return 0
    # prior 3 bars = asian session (hours 4, 0, 20)
    asian = df.iloc[max(0, i - 3): i]
    if len(asian) < 3:
        return 0
    asian_high = asian["high"].max()
    asian_low  = asian["low"].min()
    close = df["close"].iloc[i]
    if close > asian_high:
        return 1
    if close < asian_low:
        return -1
    return 0


def signal_zscore_adx_trend(df: pd.DataFrame, i: int,
                             z_period: int = 20, z_entry: float = 1.5,
                             adx_period: int = 14, adx_threshold: float = 20.0) -> int:
    """Momentum: price extended in trend direction + strong ADX."""
    if i < z_period + adx_period + 2:
        return 0
    sl = df.iloc[:i + 1]
    close = sl["close"]
    sma = close.rolling(z_period).mean()
    std = close.rolling(z_period).std()
    if std.iloc[-1] == 0 or pd.isna(std.iloc[-1]):
        return 0
    z = ((close - sma) / std).iloc[-1]

    adx, pdi, mdi = _adx_series(sl, adx_period)
    if adx.iloc[-1] < adx_threshold:
        return 0

    trend_up = pdi.iloc[-1] > mdi.iloc[-1]
    if trend_up and z > z_entry:
        return 1
    if not trend_up and z < -z_entry:
        return -1
    return 0


def signal_ema_atr(df: pd.DataFrame, i: int,
                   fast: int = 9, slow: int = 21, atr_ma: int = 20) -> int:
    """EMA cross with ATR expansion confirmation."""
    min_bars = slow + atr_ma + 2
    if i < min_bars:
        return 0
    sl = df.iloc[:i + 1]
    close = sl["close"]
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()

    cross_up = ema_f.iloc[-2] <= ema_s.iloc[-2] and ema_f.iloc[-1] > ema_s.iloc[-1]
    cross_dn = ema_f.iloc[-2] >= ema_s.iloc[-2] and ema_f.iloc[-1] < ema_s.iloc[-1]
    if not cross_up and not cross_dn:
        return 0

    atr = _atr_series(sl)
    atr_ma_val = atr.rolling(atr_ma).mean().iloc[-1]
    if pd.isna(atr_ma_val) or atr.iloc[-1] <= atr_ma_val:
        return 0

    return 1 if cross_up else -1


STRATEGIES = {
    "1_AsianBreakout ": signal_asian_breakout,
    "2_ZScoreAdxTrend": signal_zscore_adx_trend,
    "3_EmaCrossATR   ": signal_ema_atr,
}


# ── backtest engine ───────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, signal_fn, allowed_hours: set | None) -> dict:
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

        bar_hour = df.index[i].hour
        if allowed_hours is not None and bar_hour not in allowed_hours:
            continue

        sig = signal_fn(df, i)
        if sig == 0:
            continue

        entry = df["close"].iloc[i]
        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl       = entry - ATR_SL_MULT * atr_val if sig == 1 else entry + ATR_SL_MULT * atr_val
        tp       = entry + ATR_TP_MULT * atr_val  if sig == 1 else entry - ATR_TP_MULT * atr_val
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


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    symbols = ["XAU/USD", "XAG/USD"]
    data = {}

    print(f"Fetching {OUTPUTSIZE} H4 bars (~1 year)...")
    for sym in symbols:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            data[sym] = fetch_ohlcv(sym, outputsize=OUTPUTSIZE, interval="4h")
            print(f"ok ({len(data[sym])} bars, {data[sym].index[0].date()} – {data[sym].index[-1].date()})")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(15)

    col_w = 18
    print()
    print(f"{'Symbol':<10} {'Strategy':<{col_w}} {'Session':<22} {'Trades':>7} {'Win%':>7} {'Expectancy':>12}")
    print("-" * 82)

    for sym, df in data.items():
        for strat_name, fn in STRATEGIES.items():
            for session_name, hours in SESSIONS.items():
                r = backtest(df, fn, hours)
                if r["trades"] == 0:
                    row = f"{'—':>7} {'—':>7} {'—':>12}"
                else:
                    row = (f"{r['trades']:>7} "
                           f"{r['win_rate']:>6.1f}% "
                           f"{r['expectancy']:>+11.3f}R")
                print(f"{sym:<10} {strat_name:<{col_w}} {session_name:<22} {row}")
            print()
        print()
