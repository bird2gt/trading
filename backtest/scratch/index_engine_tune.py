"""
Engine tuning for JP225 / EU50 / US30. Breakout failed (these are range-y:
efficiency 0.18-0.23), so test mean-reversion & z-score families plus an R:R grid.
Goal: find an engine+params with PF>1.2 holding in BOTH 12mo and 6mo windows.

Run: python3 -m backtest.scratch.index_engine_tune
"""
import itertools
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.mean_reversion import MeanReversion
from strategy.rsi_mean_revert import RSIMeanRevert
from strategy.forex.z_score_adx import ZScoreAdx
from strategy.forex.breakout_adx import BreakoutAdx

ATR_PERIOD = 14
WARMUP = 250
INITIAL_BALANCE = 10_000.0
RISK_PCT = 0.005
PIP_SIZE, PIP_VALUE = 1.0, 1.0

SYMBOLS = ["US500", "USTEC"]   # already traded on Breakout — does mean-revert beat it?

# engine menu spanning mean-revert (right family for range markets) + a trend control
ENGINES = {
    "MeanRev20/2.0":  MeanReversion(period=20, std_mult=2.0),
    "MeanRev20/2.5":  MeanReversion(period=20, std_mult=2.5),
    "MeanRev30/2.0":  MeanReversion(period=30, std_mult=2.0),
    "RSI14/30-70":    RSIMeanRevert(period=14, oversold=30, overbought=70),
    "RSI14/25-75":    RSIMeanRevert(period=14, oversold=25, overbought=75),
    "RSI10/20-80":    RSIMeanRevert(period=10, oversold=20, overbought=80),
    "ZScore20/2.0":   ZScoreAdx(z_period=20, z_entry=2.0, adx_threshold=20.0),
    "ZScore20/2.5":   ZScoreAdx(z_period=20, z_entry=2.5, adx_threshold=20.0),
}
RR_GRID = [(1.2, 1.8), (1.5, 1.5), (2.0, 2.0), (1.0, 2.0)]  # (sl, tp) ATR mults


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl, balance):
    sl_pips = abs(entry - sl) / PIP_SIZE
    if sl_pips == 0:
        return 0.01
    return max(0.01, min(1.0, round(balance * RISK_PCT / (sl_pips * PIP_VALUE), 2)))


def _pnl(entry, exit_, direction, lots):
    return round((exit_ - entry) * direction / PIP_SIZE * PIP_VALUE * lots, 2)


def run(engine, df, sl_mult, tp_mult, window_start):
    atr = _atr(df)
    trades, in_trade = [], False
    for i in range(WARMUP, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                trades.append(_pnl(entry, tp if hit_tp else sl, direction, lots))
                in_trade = False
            continue
        if t < window_start:
            continue
        try:
            sig = engine.generate_signal(df.iloc[:i])
        except TypeError:
            sig = engine.generate_signal(df.iloc[:i], None)
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - sl_mult * a if sig == 1 else entry + sl_mult * a
        tp = entry + tp_mult * a if sig == 1 else entry - tp_mult * a
        lots = _lots(entry, sl, INITIAL_BALANCE)
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
    for sym in SYMBOLS:
        try:
            df = fetch_ohlcv(sym, interval="4h", outputsize=2600)
        except Exception as e:
            print(f"\n### {sym}: NO DATA ({type(e).__name__})"); continue
        print(f"\n### {sym}  ({len(df)} bars)")
        print(f"{'engine':14} {'sl/tp':>8} | {'12m:tr':>6} {'win%':>5} {'PnL$':>7} {'PF':>5} | {'6m:tr':>5} {'win%':>5} {'PnL$':>7} {'PF':>5}")
        print("─" * 90)
        winners = []
        for ename, engine in ENGINES.items():
            for slm, tpm in RR_GRID:
                n12, w12r, p12, pf12 = stats(run(engine, df, slm, tpm, w12))
                n6, w6r, p6, pf6 = stats(run(engine, df, slm, tpm, w6))
                pf12s = "inf" if pf12 == float("inf") else f"{pf12:.2f}"
                pf6s = "inf" if pf6 == float("inf") else f"{pf6:.2f}"
                mark = ""
                if n12 >= 15 and pf12 > 1.2 and pf6 > 1.2:
                    mark = "  <<"; winners.append((ename, slm, tpm, pf12, pf6, n12, p12))
                print(f"{ename:14} {slm:>3}/{tpm:<4} | {n12:>6} {w12r:>4.0f}% {p12:>+7.0f} {pf12s:>5} | "
                      f"{n6:>5} {w6r:>4.0f}% {p6:>+7.0f} {pf6s:>5}{mark}")
        if winners:
            print(f"  WINNERS for {sym}:")
            for w in sorted(winners, key=lambda x: -x[3]):
                print(f"    {w[0]:14} {w[1]}/{w[2]}  12mPF {w[3]:.2f} ({w[5]}tr {w[6]:+.0f}$)  6mPF {w[4]:.2f}")
        else:
            print(f"  (no engine cleared PF>1.2 in both windows for {sym})")


if __name__ == "__main__":
    main()
