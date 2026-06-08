"""
Did the live per-pair engine give a tradeable entry on USD/CHF & EUR/CHF since
Monday 2026-06-01? Same dispatch as live (strategy.forex.Forex), H4 bars,
live R:R = 1.5/1.5 ATR. Full history loaded for warmup; signals only fire from
window_start onward.
"""
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.forex import Forex
from config.profiles import PIP_CONFIG

ATR_PERIOD = 14
WARMUP_H4 = 250
RISK_PCT = 0.02
BALANCE = 10_000.0
SL_MULT = TP_MULT = 1.5
STRAT = Forex()
WINDOW = pd.Timestamp("2026-06-01")


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl, sym):
    cfg = PIP_CONFIG[sym]
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    return max(0.01, min(1.0, round(BALANCE * RISK_PCT / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots, sym):
    cfg = PIP_CONFIG[sym]
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


for sym in ["USD/CHF", "EUR/CHF"]:
    df = fetch_ohlcv(sym, interval="4h", outputsize=2600)
    atr = _atr(df)
    print(f"\n### {sym}  —  {STRAT.strategy_name(sym)}")
    print(f"  H4 history: {len(df)} bars, {df.index[0].date()} -> {df.index[-1]}")

    in_trade = False
    entry = sl = tp = lots = direction = None
    trades = []
    bars_in_window = df.index[df.index >= WINDOW]
    print(f"  H4 bars since Monday: {len(bars_in_window)}")

    for i in range(WARMUP_H4, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                px = tp if hit_tp else sl
                pnl = _pnl(entry, px, direction, lots, sym)
                trades.append(pnl)
                print(f"    EXIT  {t}  {'TP' if hit_tp else 'SL'} @ {px:.5f}  "
                      f"PnL ${pnl:+.0f}")
                in_trade = False
            continue
        if t < WINDOW:
            continue
        sig = STRAT.generate_signal(df.iloc[:i], symbol=sym)
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - SL_MULT * a if sig == 1 else entry + SL_MULT * a
        tp = entry + TP_MULT * a if sig == 1 else entry - TP_MULT * a
        lots = _lots(entry, sl, sym)
        direction = sig
        in_trade = True
        print(f"    ENTRY {t}  {'LONG' if sig==1 else 'SHORT'} @ {entry:.5f}  "
              f"SL {sl:.5f}  TP {tp:.5f}  lots {lots}")

    if in_trade:
        cur = df['close'].iloc[-1]
        upnl = _pnl(entry, cur, direction, lots, sym)
        print(f"    OPEN  still in trade @ {df.index[-1]}  mark {cur:.5f}  "
              f"unrealized ${upnl:+.0f}")
    if not trades and not in_trade:
        print("    no entries this week")
    if trades:
        print(f"  realized: {len(trades)} trade(s), net ${sum(trades):+.0f}")
