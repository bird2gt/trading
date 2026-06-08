"""
GBP/JPY engine selection — add to trading. JPY cross (trend pair like CHF/JPY/AUD/JPY),
so test AdxMa + 2B + Breakout + mean-revert over 12mo+6mo, R:R grid. Pick PF>1.2
in BOTH windows.  Run: python3 -m backtest.scratch.gbpjpy_tune
"""
import itertools, pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.forex.take_profit import AdxMa, TwoB
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.mean_reversion import MeanReversion

ATR_PERIOD, WARMUP, BAL, RISK = 14, 250, 10_000.0, 0.01
PIP_SIZE, PIP_VALUE = 0.01, 7.0   # JPY cross
SYM = "GBP/JPY"

ENGINES = {
    "AdxMa21":     AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
    "AdxMa21/25":  AdxMa(ma_period=21, adx_period=14, adx_threshold=25.0),
    "2B":          TwoB(lookback=20),
    "Breakout20":  BreakoutAdx(period=20, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
    "Breakout24":  BreakoutAdx(period=24, adx_period=14, adx_threshold=25.0, adx_rising_bars=3),
    "MeanRev20":   MeanReversion(period=20, std_mult=2.0),
}
RR = [(1.5, 1.5), (2.0, 1.5), (1.2, 1.8), (2.0, 2.0)]


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl):
    p = abs(entry-sl)/PIP_SIZE
    return 0.01 if p == 0 else max(0.01, min(1.0, round(BAL*RISK/(p*PIP_VALUE), 2)))


def run(engine, df, slm, tpm, w):
    atr = _atr(df); trades, intr = [], False
    for i in range(WARMUP, len(df)):
        if intr:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hs = (d == 1 and l <= sl) or (d == -1 and h >= sl)
            ht = (d == 1 and h >= tp) or (d == -1 and l <= tp)
            if hs or ht:
                ex = tp if ht else sl
                trades.append(round((ex-entry)*d/PIP_SIZE*PIP_VALUE*lots, 2)); intr = False
            continue
        if df.index[i] < w: continue
        sig = engine.generate_signal(df.iloc[:i])
        if sig == 0: continue
        entry = df["close"].iloc[i-1]; a = atr.iloc[i-1]
        if pd.isna(a) or a == 0: continue
        sl = entry-slm*a if sig == 1 else entry+slm*a
        tp = entry+tpm*a if sig == 1 else entry-tpm*a
        lots = _lots(entry, sl); d = sig; intr = True
    return trades


def st(tr):
    n = len(tr)
    if n == 0: return (0, 0.0, 0.0, 0.0)
    w = [x for x in tr if x > 0]; gw, gl = sum(w), abs(sum(x for x in tr if x <= 0))
    return (n, len(w)/n*100, gw-gl, gw/gl if gl > 0 else 9.99)


def main():
    now = pd.Timestamp.now().tz_localize(None)
    w12, w6 = now-pd.Timedelta(days=365), now-pd.Timedelta(days=182)
    df = fetch_ohlcv(SYM, interval="4h", outputsize=2600)
    print(f"### {SYM}  ({len(df)} bars)")
    print(f"{'engine':12} {'sl/tp':>8} | {'12m:tr':>6} {'win%':>5} {'PnL$':>7} {'PF':>5} | {'6m:tr':>5} {'PF':>5}")
    print("─"*72)
    winners = []
    for en, eng in ENGINES.items():
        for slm, tpm in RR:
            n12, w12r, p12, pf12 = st(run(eng, df, slm, tpm, w12))
            n6, _, _, pf6 = st(run(eng, df, slm, tpm, w6))
            mk = ""
            if n12 >= 15 and pf12 > 1.2 and pf6 > 1.2:
                mk = "  <<"; winners.append((en, slm, tpm, pf12, pf6, n12, p12))
            print(f"{en:12} {slm:>3}/{tpm:<4} | {n12:>6} {w12r:>4.0f}% {p12:>+7.0f} {pf12:>5.2f} | {n6:>5} {pf6:>5.2f}{mk}")
    print("\n=== WINNERS ===")
    for w in sorted(winners, key=lambda x: -x[3]):
        print(f"  {w[0]:12} {w[1]}/{w[2]}  12mPF {w[3]:.2f} ({w[5]}tr {w[6]:+.0f}$)  6mPF {w[4]:.2f}")
    if not winners: print("  (none cleared PF>1.2 in both)")


if __name__ == "__main__":
    main()
