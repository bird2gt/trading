"""
Backtest the oil geo-risk news-window TRIGGER on real WTI/BRENT 15m history.

Caveat: we have no historical oil_geo.flag (the digest detector only runs going
forward), so this can't reconstruct *when* a geopolitical flag was armed. It
therefore tests the PRICE trigger in isolation — i.e. "if the window opened on
every >=Z-sigma 15m impulse, how would the news-breakout entry have done?" That
is the upper bound on the channel's activity and the honest test of the trigger.

Entry = first close where |z of the 3-bar move| >= Z (one position at a time).
SL/TP = ATR_BREAKOUT_MULT * ATR15m (matches live news-breakout: 1.0x, tight).
Direction = sign of the impulse (momentum, as the live breakout does).

Run: python -m backtest.scratch.oil_geo_backtest
"""
import pandas as pd
from history.fetcher import fetch_ohlcv
from bias.surprise import SIGMA_LOOKBACK, REACTION_CANDLES

ATR_PERIOD = 14
ATR_MULT = 1.0          # ATR_BREAKOUT_MULT in run_mt4 (tight news SL/TP)
RISK_PCT = 0.005        # energy profile
BALANCE = 2152.0


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def backtest(sym: str, z_thresh: float, skip_gap_bar: bool = False) -> dict:
    df = fetch_ohlcv(sym, outputsize=5000, interval="15min")
    c = df["close"].reset_index(drop=True)
    h = df["high"].reset_index(drop=True)
    l = df["low"].reset_index(drop=True)
    a = _atr(df).reset_index(drop=True)
    t = df.index
    # gap bar = first bar of a new session (>2h since previous bar) — weekend gap
    gap = [False] * len(c)
    for i in range(1, len(c)):
        if (t[i] - t[i - 1]).total_seconds() > 2 * 3600:
            gap[i] = True

    trades = []
    i = SIGMA_LOOKBACK + REACTION_CANDLES
    while i < len(c):
        if skip_gap_bar and gap[i]:
            i += 1
            continue
        base = c.iloc[i - REACTION_CANDLES]
        move = (c.iloc[i] - base) / base
        sigma = c.pct_change().iloc[max(0, i - REACTION_CANDLES - SIGMA_LOOKBACK):i - REACTION_CANDLES].std()
        if not sigma or sigma == 0 or pd.isna(a.iloc[i]):
            i += 1
            continue
        z = move / sigma
        if abs(z) < z_thresh:
            i += 1
            continue
        # open trade
        d = 1 if z > 0 else -1
        entry = c.iloc[i]
        atr_e = a.iloc[i]
        sl = entry - d * ATR_MULT * atr_e
        tp = entry + d * ATR_MULT * atr_e
        exit_i = None
        for j in range(i + 1, len(c)):
            if d > 0:
                if l.iloc[j] <= sl:
                    trades.append(-1.0); exit_i = j; break
                if h.iloc[j] >= tp:
                    trades.append(+1.0); exit_i = j; break
            else:
                if h.iloc[j] >= sl:
                    trades.append(-1.0); exit_i = j; break
                if l.iloc[j] <= tp:
                    trades.append(+1.0); exit_i = j; break
        if exit_i is None:
            break  # last trade still open, ignore
        i = exit_i + 1  # one position at a time

    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x < 0]
    n = len(trades)
    wr = len(wins) / n if n else 0
    # R:R is 1:1 (ATR_MULT both sides), so PnL in R = wins - losses
    pf = (len(wins) * 1.0) / (len(losses) * 1.0) if losses else float("inf")
    total_R = sum(trades)
    usd = total_R * BALANCE * RISK_PCT
    return {"n": n, "wr": wr, "pf": pf, "total_R": total_R, "usd": usd}


def main():
    print(f"Oil geo-trigger backtest — WTI/BRENT 15m, news-breakout 1xATR, 1:1 R:R")
    print(f"(no historical flag — pure price trigger, upper bound on activity)\n")
    for sym in ["WTI", "BRENT"]:
        print(f"=== {sym} ===")
        for z in [2.0, 3.0, 4.0]:
            r = backtest(sym, z)
            rg = backtest(sym, z, skip_gap_bar=True)
            print(f"  z>={z}: n={r['n']:3d} WR={r['wr']:.0%} PF={r['pf']:.2f} "
                  f"tot={r['total_R']:+.1f}R (${r['usd']:+.0f})  "
                  f"| skip-gap: n={rg['n']:3d} WR={rg['wr']:.0%} PF={rg['pf']:.2f} "
                  f"tot={rg['total_R']:+.1f}R (${rg['usd']:+.0f})")
        print()


if __name__ == "__main__":
    main()
