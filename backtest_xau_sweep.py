"""
XAU parameter sweep: find a ZScoreAdxTrend setting (entry filter + R:R) that turns
gold's strong trend into positive strategy P&L instead of churn.
Same engine as backtest_rank.py, XAU-only, session-hour gate {8,12,16}.
"""
import itertools
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.metals import ZScoreAdxTrend, MetalsSession
from config.profiles import PIP_CONFIG

ATR_PERIOD = 14
WARMUP_H4  = 250
INITIAL_BALANCE = 10_000.0
RISK_PCT = 0.02
SESSION_HOURS = {8, 12, 16}
SYM = "XAU/USD"
CFG = PIP_CONFIG[SYM]  # pip_size 0.01, pip_value 1.0


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl, balance):
    sl_pips = abs(entry - sl) / CFG["pip_size"]
    if sl_pips == 0:
        return 0.01
    return max(0.01, min(1.0, round(balance * RISK_PCT / (sl_pips * CFG["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots):
    pips = (exit_ - entry) * direction / CFG["pip_size"]
    return round(pips * CFG["pip_value"] * lots, 2)


def run(df, strat, sl_mult, tp_mult, window_start):
    # Faithful to live: MetalsSession applies the session-hour gate on the last
    # CLOSED bar (df_closed.index[-1]); only the inner momentum strat is swapped.
    ms = MetalsSession("XAUUSD")
    ms._strat = strat
    atr = _atr(df)
    trades, in_trade, balance = [], False, INITIAL_BALANCE
    for i in range(WARMUP_H4, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p = tp if hit_tp else sl
                trades.append(_pnl(entry, exit_p, direction, lots))
                in_trade = False
            continue
        if t < window_start:
            continue
        sig = ms.generate_signal(df.iloc[:i])  # closed bars; internal hour gate
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - sl_mult * a if sig == 1 else entry + sl_mult * a
        tp = entry + tp_mult * a if sig == 1 else entry - tp_mult * a
        lots = _lots(entry, sl, balance)
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
    print(f"Fetching {SYM}...")
    df = fetch_ohlcv(SYM, interval="4h", outputsize=2600)
    print(f"  {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}\n")
    now = pd.Timestamp.now().tz_localize(None)
    w12 = now - pd.Timedelta(days=365)
    w6  = now - pd.Timedelta(days=182)

    grid = list(itertools.product(
        [1.5, 2.0, 2.5],            # z_entry
        [20.0, 25.0, 30.0],         # adx_threshold
        [(1.5, 1.5), (1.5, 2.5), (2.0, 3.0)],  # (sl_mult, tp_mult)
    ))

    print(f"{'z':>4} {'adx':>4} {'sl/tp':>8} | "
          f"{'12m: tr':>7} {'win%':>5} {'PnL$':>9} {'avg$':>7} {'PF':>5} | "
          f"{'6m: tr':>6} {'win%':>5} {'PnL$':>9} {'avg$':>7} {'PF':>5}")
    print("─" * 104)
    baseline = (1.5, 20.0, (1.5, 1.5))
    for z, adx, (slm, tpm) in grid:
        strat = ZScoreAdxTrend(z_period=20, z_entry=z, adx_period=14, adx_threshold=adx)
        n12, w12r, p12, a12, pf12 = stats(run(df, strat, slm, tpm, w12))
        n6, w6r, p6, a6, pf6 = stats(run(df, strat, slm, tpm, w6))
        pf12s = "inf" if pf12 == float("inf") else f"{pf12:.2f}"
        pf6s = "inf" if pf6 == float("inf") else f"{pf6:.2f}"
        mark = "  <= baseline" if (z, adx, (slm, tpm)) == baseline else ""
        print(f"{z:>4} {adx:>4.0f} {slm:>3}/{tpm:<4} | "
              f"{n12:>7} {w12r:>4.0f}% {p12:>+9.0f} {a12:>+7.1f} {pf12s:>5} | "
              f"{n6:>6} {w6r:>4.0f}% {p6:>+9.0f} {a6:>+7.1f} {pf6s:>5}{mark}")


if __name__ == "__main__":
    main()
