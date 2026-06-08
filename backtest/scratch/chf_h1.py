"""
H1 version of chf_12mo.py: same engine bake-off but on the H1 timeframe
(5000 bars ~= 6-8mo). Answers whether the H4 edge of AdxMa/TwoB/EmaPsar over the
live CHF profiles survives on H1. Mechanics: H1, R:R 1.5/1.5 ATR, 2% risk.
"""
import inspect
import pandas as pd
from history.fetcher import fetch_ohlcv
from config.profiles import PIP_CONFIG
from strategy.forex.take_profit import AdxMa, TwoB
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.forex.z_score_adx import ZScoreAdx
from strategy.forex.ema_psar_trend import EmaPsarTrend

ATR_PERIOD = 14
WARMUP = 250
RISK_PCT = 0.02
BALANCE = 10_000.0
SL_MULT = TP_MULT = 1.5


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


def _sig(engine, sub, sym):
    params = inspect.signature(engine.generate_signal).parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return engine.generate_signal(sub, symbol=sym)
    return engine.generate_signal(sub)


def run(sym, df, atr, engine, window_start):
    in_trade = False
    entry = sl = tp = lots = direction = None
    trades = []
    for i in range(WARMUP, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                px = tp if hit_tp else sl
                trades.append(_pnl(entry, px, direction, lots, sym))
                in_trade = False
            continue
        if t < window_start:
            continue
        sig = _sig(engine, df.iloc[:i], sym)
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
    return trades


def stats(tr):
    n = len(tr)
    if n == 0:
        return (0, 0.0, 0.0, 0.0)
    wins = [x for x in tr if x > 0]
    gw, gl = sum(wins), abs(sum(x for x in tr if x <= 0))
    pf = gw / gl if gl > 0 else float("inf")
    return (n, len(wins) / n * 100, gw - gl, pf)


now = pd.Timestamp.now().tz_localize(None)
w12, w6 = now - pd.Timedelta(days=365), now - pd.Timedelta(days=182)

CANDIDATES = {
    "USD/CHF": {
        "BreakoutAdx(30) [LIVE]": BreakoutAdx(period=30, adx_period=14, adx_threshold=20.0, adx_rising_bars=3),
        "AdxMa(21)": AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
        "TwoB(20)": TwoB(lookback=20),
        "EmaPsarTrend": EmaPsarTrend(),
    },
    "EUR/CHF": {
        "ZScoreAdx [LIVE]": ZScoreAdx(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0, z_signal_period=3),
        "AdxMa(21)": AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
        "TwoB(20)": TwoB(lookback=20),
        "EmaPsarTrend": EmaPsarTrend(),
    },
}

for sym, engines in CANDIDATES.items():
    df = fetch_ohlcv(sym, interval="1h", outputsize=5000)
    atr = _atr(df)
    print(f"\n### {sym}   ({len(df)} H1 bars, {df.index[0].date()} -> {df.index[-1].date()})")
    print(f"  {'engine':<26} | {'12m: tr':>7} {'win%':>5} {'PnL$':>8} {'PF':>5} | "
          f"{'6m: tr':>6} {'win%':>5} {'PnL$':>8} {'PF':>5}")
    print("  " + "-" * 86)
    for name, eng in engines.items():
        n12, w12r, p12, pf12 = stats(run(sym, df, atr, eng, w12))
        n6, w6r, p6, pf6 = stats(run(sym, df, atr, eng, w6))
        pf12s = "inf" if pf12 == float("inf") else f"{pf12:.2f}"
        pf6s = "inf" if pf6 == float("inf") else f"{pf6:.2f}"
        print(f"  {name:<26} | {n12:>7} {w12r:>4.0f}% {p12:>+8.0f} {pf12s:>5} | "
              f"{n6:>6} {w6r:>4.0f}% {p6:>+8.0f} {pf6s:>5}")
