"""
Candidate-pair sweep for adding 3 new symbols. For each candidate, run every
available forex engine over 12mo + 6mo windows and report PF/win%/PnL. Pick
winners with PF > 1.2 holding up in BOTH half-years (same bar as CHF/JPY/NZD/CAD).

Run: python3 -m backtest.scratch.new_pairs_sweep
"""
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.forex.take_profit import AdxMa, TwoB
from strategy.mean_reversion import MeanReversion

ATR_PERIOD = 14
WARMUP = 250
INITIAL_BALANCE = 10_000.0
RISK_PCT = 0.02
SL_MULT, TP_MULT = 1.5, 1.5  # live defaults; per-pair tuning comes after a pair is chosen

CANDIDATES = ["EUR/GBP", "EUR/JPY", "GBP/JPY", "AUD/JPY", "CAD/JPY",
              "GBP/CHF", "EUR/AUD", "AUD/NZD"]

# pip specs for sizing/PnL (not yet in live PIP_CONFIG — added here for the sweep only)
PIP = {
    "EUR/GBP": (0.0001, 13.0), "EUR/JPY": (0.01, 7.0), "GBP/JPY": (0.01, 7.0),
    "AUD/JPY": (0.01, 7.0), "CAD/JPY": (0.01, 7.0), "GBP/CHF": (0.0001, 11.0),
    "EUR/AUD": (0.0001, 7.0), "AUD/NZD": (0.0001, 6.0),
}

ENGINES = {
    "BreakoutAdx20": BreakoutAdx(period=20, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
    "BreakoutAdx24": BreakoutAdx(period=24, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
    "AdxMa21":       AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
    "2B":            TwoB(lookback=20),
    "MeanRevert":    MeanReversion(),
}


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl, pip_size, pip_value, balance):
    sl_pips = abs(entry - sl) / pip_size
    if sl_pips == 0:
        return 0.01
    return max(0.01, min(1.0, round(balance * RISK_PCT / (sl_pips * pip_value), 2)))


def _pnl(entry, exit_, direction, lots, pip_size, pip_value):
    pips = (exit_ - entry) * direction / pip_size
    return round(pips * pip_value * lots, 2)


def run(engine, df, sym, window_start):
    pip_size, pip_value = PIP[sym]
    atr = _atr(df)
    trades, in_trade = [], False
    for i in range(WARMUP, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                trades.append(_pnl(entry, tp if hit_tp else sl, direction, lots, pip_size, pip_value))
                in_trade = False
            continue
        if t < window_start:
            continue
        sig = engine.generate_signal(df.iloc[:i])
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - SL_MULT * a if sig == 1 else entry + SL_MULT * a
        tp = entry + TP_MULT * a if sig == 1 else entry - TP_MULT * a
        lots = _lots(entry, sl, pip_size, pip_value, INITIAL_BALANCE)
        direction = sig
        in_trade = True
    return trades


def stats(tr):
    n = len(tr)
    if n == 0:
        return (0, 0.0, 0.0, 0.0)
    wins = [x for x in tr if x > 0]
    gw, gl = sum(wins), abs(sum(x for x in tr if x <= 0))
    pf = gw / gl if gl > 0 else float("inf")
    return (n, len(wins) / n * 100, gw - gl, pf)


def main():
    now = pd.Timestamp.now().tz_localize(None)
    w12, w6 = now - pd.Timedelta(days=365), now - pd.Timedelta(days=182)
    rows = []
    for sym in CANDIDATES:
        try:
            df = fetch_ohlcv(sym, interval="4h", outputsize=2600)
        except Exception as e:
            print(f"{sym}: NO DATA ({type(e).__name__})")
            continue
        if len(df) < WARMUP + 50:
            print(f"{sym}: too few bars ({len(df)})")
            continue
        for ename, engine in ENGINES.items():
            n12, w12r, p12, pf12 = stats(run(engine, df, sym, w12))
            n6, w6r, p6, pf6 = stats(run(engine, df, sym, w6))
            rows.append((sym, ename, n12, w12r, p12, pf12, n6, w6r, p6, pf6))

    # print grouped by symbol
    hdr = f"{'pair':8} {'engine':13} | {'12m:tr':>6} {'win%':>5} {'PnL$':>8} {'PF':>5} | {'6m:tr':>5} {'win%':>5} {'PnL$':>8} {'PF':>5}"
    print("\n" + hdr)
    print("─" * len(hdr))
    cur = None
    for r in rows:
        sym, en, n12, w12r, p12, pf12, n6, w6r, p6, pf6 = r
        if sym != cur:
            print("─" * len(hdr)); cur = sym
        pf12s = "inf" if pf12 == float("inf") else f"{pf12:.2f}"
        pf6s = "inf" if pf6 == float("inf") else f"{pf6:.2f}"
        print(f"{sym:8} {en:13} | {n12:>6} {w12r:>4.0f}% {p12:>+8.0f} {pf12s:>5} | "
              f"{n6:>5} {w6r:>4.0f}% {p6:>+8.0f} {pf6s:>5}")

    # rank: best engine per pair by 12m PF, require both windows PF>1.2 and >=15 trades/12m
    print("\n=== WINNERS (PF>1.2 in 12m AND 6m, >=15 trades/12m) ===")
    best = {}
    for r in rows:
        sym, en, n12, w12r, p12, pf12, n6, w6r, p6, pf6 = r
        if n12 >= 15 and pf12 > 1.2 and pf6 > 1.2:
            if sym not in best or pf12 > best[sym][5]:
                best[sym] = r
    if not best:
        print("  (none cleared the bar)")
    for sym, r in sorted(best.items(), key=lambda kv: -kv[1][5]):
        _, en, n12, w12r, p12, pf12, n6, w6r, p6, pf6 = r
        print(f"  {sym:8} {en:13}  12m PF {pf12:.2f} ({n12}tr, {p12:+.0f}$)  6m PF {pf6:.2f}")


if __name__ == "__main__":
    main()
