"""
Intermarket filter comparison — 1 year of H4 data.
Tests 3 group-filter approaches on top of BreakoutADX:
  0. Baseline      — no intermarket filter
  1. Leader        — signal allowed only if BTC +DI/-DI matches direction
  2. Breadth       — both BTC and ETH must trend same direction
  3. Corr+Momentum — rolling correlation high AND group momentum agrees

Crypto only (BTC + ETH). BTC = group leader.
"""
import time
import pandas as pd
import numpy as np
from history.fetcher import fetch_ohlcv
from strategy.crypto.breakout import Breakout

SYMBOLS      = ["BTC/USD", "ETH/USD"]
LEADER       = "BTC/USD"
TEST_H4      = 2190   # ~1 year 24/7
WARMUP_H4    = 300
TOTAL_H4     = TEST_H4 + WARMUP_H4

ATR_PERIOD   = 14
SL_MULT      = 1.5
TP_MULT      = 2.0
INITIAL_BAL  = 10_000.0
RISK_PCT     = 0.02

STRATEGY = Breakout(period=20, adx_period=14, adx_threshold=25.0,
                    vol_ma=20, vol_mult=1.2, adx_rising_bars=5)

ADX_PERIOD   = 14   # for DI computation in filters
CORR_PERIOD  = 20
MOM_PERIOD   = 10
CORR_MIN     = 0.5


# ── indicator helpers ─────────────────────────────────────────────────────────

def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _di(df: pd.DataFrame, period: int = ADX_PERIOD):
    """Returns (plus_di, minus_di) as last scalar values."""
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff(); dn = -l.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    tr  = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a   = 1 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = (100 * pdm.ewm(alpha=a, adjust=False).mean() / atr).iloc[-1]
    mdi = (100 * mdm.ewm(alpha=a, adjust=False).mean() / atr).iloc[-1]
    return pdi, mdi


# ── intermarket filters ───────────────────────────────────────────────────────

def allow_leader(df_asset, df_leader, signal: int) -> bool:
    """Signal must align with BTC +DI/-DI direction."""
    if df_leader is None or len(df_leader) < ADX_PERIOD * 2:
        return True
    pdi, mdi = _di(df_leader)
    leader_up = pdi > mdi
    return (signal == 1 and leader_up) or (signal == -1 and not leader_up)


def allow_breadth(df_asset, df_leader, signal: int) -> bool:
    """Both asset and leader must trend in the same direction."""
    if df_leader is None or len(df_leader) < ADX_PERIOD * 2:
        return True
    pdi_a, mdi_a = _di(df_asset)
    pdi_l, mdi_l = _di(df_leader)
    asset_up  = pdi_a > mdi_a
    leader_up = pdi_l > mdi_l
    both_up   = asset_up and leader_up
    both_dn   = (not asset_up) and (not leader_up)
    return (signal == 1 and both_up) or (signal == -1 and both_dn)


def allow_corr_mom(df_asset, df_leader, signal: int) -> bool:
    """Rolling correlation must be high AND group momentum must agree."""
    if df_leader is None or len(df_leader) < CORR_PERIOD + MOM_PERIOD + 2:
        return True

    ret_a = df_asset["close"].pct_change().dropna()
    ret_l = df_leader["close"].pct_change().reindex(ret_a.index).dropna()

    if len(ret_a) < CORR_PERIOD or len(ret_l) < CORR_PERIOD:
        return True

    # Align indices
    common = ret_a.index.intersection(ret_l.index)
    if len(common) < CORR_PERIOD:
        return True
    ra = ret_a.loc[common]
    rl = ret_l.loc[common]

    corr = ra.iloc[-CORR_PERIOD:].corr(rl.iloc[-CORR_PERIOD:])
    if pd.isna(corr) or corr < CORR_MIN:
        return False  # low correlation — assets decoupled, skip

    group_mom = (ra.iloc[-MOM_PERIOD:].sum() + rl.iloc[-MOM_PERIOD:].sum()) / 2
    return (signal == 1 and group_mom > 0) or (signal == -1 and group_mom < 0)


FILTERS = {
    "Baseline":    None,
    "Leader":      allow_leader,
    "Breadth":     allow_breadth,
    "Corr+Mom":    allow_corr_mom,
}


# ── backtest engine ───────────────────────────────────────────────────────────

def backtest_one(symbol: str, df: pd.DataFrame, df_leader: pd.DataFrame | None,
                 filter_fn) -> list[dict]:
    atr      = _atr_series(df)
    trades   = []
    in_trade = False
    balance  = INITIAL_BAL
    start_i  = max(WARMUP_H4, len(df) - TEST_H4)

    for i in range(start_i, len(df)):
        bar_time = df.index[i]

        if in_trade:
            h = df["high"].iloc[i]
            l = df["low"].iloc[i]
            hit_sl = (direction ==  1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction ==  1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p  = tp if hit_tp else sl
                pnl     = (exit_p - entry_price) * direction
                sl_dist = abs(entry_price - sl)
                lots    = max(0.01, min(2.0, round(balance * RISK_PCT / sl_dist, 2)))
                pnl_usd = round(pnl * lots, 2)
                balance += pnl_usd
                trades.append({
                    "symbol":  symbol,
                    "entry_t": entry_t,
                    "dir":     direction,
                    "pnl":     pnl_usd,
                    "result":  "W" if hit_tp else "L",
                    "balance": round(balance, 2),
                })
                in_trade = False
            continue

        df_closed = df.iloc[:i]
        signal    = STRATEGY.generate_signal(df_closed)
        if signal == 0:
            continue

        # Apply intermarket filter (skip for BTC — it IS the leader)
        if filter_fn is not None and symbol != LEADER:
            leader_closed = df_leader.iloc[:i] if df_leader is not None else None
            if not filter_fn(df_closed, leader_closed, signal):
                continue

        entry_price = df["close"].iloc[i - 1]
        atr_val     = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl        = entry_price - SL_MULT * atr_val if signal ==  1 else entry_price + SL_MULT * atr_val
        tp        = entry_price + TP_MULT * atr_val if signal ==  1 else entry_price - TP_MULT * atr_val
        direction = signal
        entry_t   = bar_time
        in_trade  = True

    return trades


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Intermarket filter comparison — 1 year H4  ({TEST_H4} bars + {WARMUP_H4} warmup)\n"
          f"Strategy: BreakoutADX(adx≥25, rising≥5)  SL={SL_MULT}×ATR  TP={TP_MULT}×ATR\n")

    print("Fetching data...")
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

    df_leader = data.get(LEADER)

    # ── results table ──────────────────────────────────────────────────────────
    print(f"\n{'Filter':<14} {'Sym':<10} {'Tr':>4} {'W':>4} {'L':>4} {'Win%':>6} {'PnL $':>9} {'$/tr':>7}")
    print("─" * 62)

    summary = {}
    for fname, fn in FILTERS.items():
        group_trades = []
        for sym in SYMBOLS:
            if sym not in data:
                continue
            dl = df_leader if sym != LEADER else None
            trades = backtest_one(sym, data[sym], dl, fn)
            group_trades.extend(trades)

            if trades:
                n   = len(trades)
                w   = sum(1 for t in trades if t["result"] == "W")
                pnl = sum(t["pnl"] for t in trades)
                print(f"{fname:<14} {sym:<10} {n:>4} {w:>4} {n-w:>4} "
                      f"{w/n*100:>5.0f}% {pnl:>+9.2f} {pnl/n:>+7.2f}")
            else:
                print(f"{fname:<14} {sym:<10}    –")

        if group_trades:
            n   = len(group_trades)
            w   = sum(1 for t in group_trades if t["result"] == "W")
            pnl = sum(t["pnl"] for t in group_trades)
            print(f"{'':14} {'TOTAL':<10} {n:>4} {w:>4} {n-w:>4} "
                  f"{w/n*100:>5.0f}% {pnl:>+9.2f} {pnl/n:>+7.2f}")
            summary[fname] = {"n": n, "win_pct": w/n*100, "pnl": pnl, "per_trade": pnl/n}
        print()

    # ── verdict ────────────────────────────────────────────────────────────────
    print("─" * 62)
    print(f"\n{'Filter':<14} {'Trades':>7} {'Win%':>6} {'Total PnL':>10} {'$/trade':>8}")
    print("─" * 44)
    for fname, s in summary.items():
        marker = " ◄" if s["pnl"] == max(v["pnl"] for v in summary.values()) else ""
        print(f"{fname:<14} {s['n']:>7} {s['win_pct']:>5.0f}% "
              f"{s['pnl']:>+10.2f} {s['per_trade']:>+8.2f}{marker}")


if __name__ == "__main__":
    main()
