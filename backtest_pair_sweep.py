"""
AUD/USD & USD/CAD: does a per-symbol sl_mult/tp_mult rescue them, or should they
be disabled? Same forex engine as live (dispatched by symbol); only R:R is swept.
"""
import itertools
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.forex import Forex
from config.profiles import PIP_CONFIG

ATR_PERIOD = 14
WARMUP_H4  = 250
INITIAL_BALANCE = 10_000.0
RISK_PCT = 0.02
STRAT = Forex(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0)


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl, sym, balance):
    cfg = PIP_CONFIG[sym]
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    if sl_pips == 0:
        return 0.01
    return max(0.01, min(1.0, round(balance * RISK_PCT / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots, sym):
    cfg = PIP_CONFIG[sym]
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def run(sym, df, sl_mult, tp_mult, window_start):
    atr = _atr(df)
    trades, in_trade, balance = [], False, INITIAL_BALANCE
    for i in range(WARMUP_H4, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                trades.append(_pnl(entry, tp if hit_tp else sl, direction, lots, sym))
                in_trade = False
            continue
        if t < window_start:
            continue
        sig = STRAT.generate_signal(df.iloc[:i], symbol=sym)
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - sl_mult * a if sig == 1 else entry + sl_mult * a
        tp = entry + tp_mult * a if sig == 1 else entry - tp_mult * a
        lots = _lots(entry, sl, sym, balance)
        direction = sig
        in_trade = True
    return trades


def stats(tr):
    n = len(tr)
    if n == 0:
        return (0, 0, 0.0, 0.0, 0.0)
    wins = [x for x in tr if x > 0]
    gw, gl = sum(wins), abs(sum(x for x in tr if x <= 0))
    pf = gw / gl if gl > 0 else float("inf")
    pnl = gw - gl
    return (n, len(wins) / n * 100, pnl, pnl / n, pf)


def main():
    now = pd.Timestamp.now().tz_localize(None)
    w12, w6 = now - pd.Timedelta(days=365), now - pd.Timedelta(days=182)
    grid = list(itertools.product([1.5, 2.0, 2.5, 3.0], [1.5, 2.0, 2.5]))  # (sl, tp)

    for sym in ["AUD/USD", "USD/CAD"]:
        print(f"\n### {sym}  ({STRAT.strategy_name(sym)})")
        df = fetch_ohlcv(sym, interval="4h", outputsize=2600)
        print(f"  {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
        print(f"  {'sl/tp':>8} | {'12m: tr':>7} {'win%':>5} {'PnL$':>8} {'avg$':>7} {'PF':>5} | "
              f"{'6m: tr':>6} {'win%':>5} {'PnL$':>8} {'avg$':>7} {'PF':>5}")
        print("  " + "─" * 92)
        for slm, tpm in grid:
            n12, w12r, p12, a12, pf12 = stats(run(sym, df, slm, tpm, w12))
            n6, w6r, p6, a6, pf6 = stats(run(sym, df, slm, tpm, w6))
            pf12s = "inf" if pf12 == float("inf") else f"{pf12:.2f}"
            pf6s = "inf" if pf6 == float("inf") else f"{pf6:.2f}"
            base = "  <= live (1.5/1.5)" if (slm, tpm) == (1.5, 1.5) else ""
            print(f"  {slm:>3}/{tpm:<4} | {n12:>7} {w12r:>4.0f}% {p12:>+8.0f} {a12:>+7.1f} {pf12s:>5} | "
                  f"{n6:>6} {w6r:>4.0f}% {p6:>+8.0f} {a6:>+7.1f} {pf6s:>5}{base}")


if __name__ == "__main__":
    main()
