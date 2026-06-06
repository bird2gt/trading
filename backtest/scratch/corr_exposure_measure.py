"""
MEASURE step for the portfolio-eur-correlation branch.

Goal (per user): the pain is IDLE CAPITAL / missed profit, not double-bet risk.
In live (run_mt4) there is NO max-position cap and NO margin check — so the
*only* thing that idles capital is the hand correlation filter rejecting a
signal. Therefore:

    idle cost = the trades the hand filter (CORR_GROUPS + INVERSE_CORR_GROUPS)
                would have rejected, measured on the REAL per-pair live engines.

Method (same H4 mechanics as backtest/scratch/chf_12mo.py):
  1. Generate a trade stream per pair (entry_t, exit_t, dir, pnl) over ~1y using
     the actual live engines from Forex().by_symbol (strategy_map).
  2. Merge into one time-ordered portfolio, replay entries in time.
  3. For each entry, ask the live hand filter whether it's blocked given what's
     open at that instant. Report: how OFTEN it blocks, the PnL of the blocked
     trades, and win%/PF of blocked vs taken — so we can tell whether the filter
     is leaving good money on the table or just cutting junk.

Blocking logic is imported from run_mt4 verbatim so the measurement matches
production. Does NOT touch live code.
"""
from collections import defaultdict

import pandas as pd

from history.fetcher import fetch_ohlcv
from config.profiles import PIP_CONFIG, rules_for
from strategy.forex.forex import Forex

# The OLD hand-written forex filter this study measured against. These groups were
# removed from run_mt4 once the net-exposure cap replaced them; kept here verbatim so
# the historical "before" comparison still runs.
CORR_GROUPS = [
    {"EUR/USD", "GBP/USD", "AUD/USD"},
    {"USD/CHF", "USD/CAD"},
]
INVERSE_CORR_GROUPS = [
    {"EUR/USD", "USD/CHF"}, {"GBP/USD", "USD/CHF"}, {"AUD/USD", "USD/CHF"},
    {"EUR/USD", "USD/CAD"}, {"GBP/USD", "USD/CAD"}, {"AUD/USD", "USD/CAD"},
]

ATR_PERIOD = 14
WARMUP = 250
RISK_PCT = 0.02
BALANCE = 10_000.0
OUTPUTSIZE = 2600  # ~1y+ of H4

# Real live per-pair engines — the single dispatcher run_mt4/backtest share.
_FX = Forex()
SYMBOLS = ["EUR/USD", "GBP/USD", "AUD/USD", "USD/CHF", "USD/JPY", "USD/CAD", "EUR/CHF"]


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


def trades_for(sym, df, atr):
    """Single-pair walk-forward using the live engine; returns trade dicts."""
    in_trade = False
    entry = sl = tp = lots = direction = entry_t = None
    out = []
    rules = rules_for(sym)
    sl_mult, tp_mult = rules["sl_mult"], rules["tp_mult"]
    for i in range(WARMUP, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                px = tp if hit_tp else sl
                out.append({
                    "sym": sym, "entry_t": entry_t, "exit_t": t,
                    "dir": "BUY" if direction == 1 else "SELL",
                    "pnl": _pnl(entry, px, direction, lots, sym),
                })
                in_trade = False
            continue
        sig = _FX.generate_signal(df.iloc[:i], symbol=sym)
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - sl_mult * a if sig == 1 else entry + sl_mult * a
        tp = entry + tp_mult * a if sig == 1 else entry - tp_mult * a
        lots = _lots(entry, sl, sym)
        direction, entry_t, in_trade = sig, t, True
    return out


def hand_blocks(sym, action, active):
    """run_mt4._correlated_conflict, parameterized on a local position dict
    (sym -> 'BUY'|'SELL') so we don't mutate live module globals."""
    for group in CORR_GROUPS:
        if sym in group:
            for other in group:
                if other != sym and active.get(other) == action:
                    return True
    opp = "SELL" if action == "BUY" else "BUY"
    for group in INVERSE_CORR_GROUPS:
        if sym in group:
            for other in group:
                if other != sym and active.get(other) == opp:
                    return True
    return False


def replay(all_trades):
    """Walk entries in time. Live has no position cap, so the only reason an
    entry is rejected is the hand correlation filter. Returns (taken, blocked)."""
    events = []
    for t in all_trades:
        events.append((t["entry_t"], "open", t))
        events.append((t["exit_t"], "close", t))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "close" else 1))  # close before open at same ts

    open_pos = {}   # sym -> (dir, trade)
    taken, blocked = [], []
    for _, kind, t in events:
        if kind == "close":
            if t["sym"] in open_pos and open_pos[t["sym"]][1] is t:
                del open_pos[t["sym"]]
            continue
        if t["sym"] in open_pos:        # one position per symbol at a time
            continue                     # not idle capital — same symbol already working
        active = {s: d for s, (d, _t) in open_pos.items()}
        if hand_blocks(t["sym"], t["dir"], active):
            blocked.append(t)
        else:
            open_pos[t["sym"]] = (t["dir"], t)
            taken.append(t)
    return taken, blocked


# ---- currency-netting risk budget ----------------------------------------

def _legs(sym, action):
    """A BUY of BASE/QUOTE adds +1 to BASE, -1 to QUOTE (in lot-risk units)."""
    base, quote = sym.split("/")
    s = 1.0 if action == "BUY" else -1.0
    return {base: s, quote: -s}


def budget_replay(all_trades, budget, min_lot=0.25):
    """Net exposure per currency capped at `budget`. A new entry is sized to the
    largest lot multiple m<=1 that keeps every currency's |net| <= budget. If the
    headroom yields m < min_lot the entry is dropped (micro-lots are noise).

    PnL scales linearly with lot, so a taken trade contributes pnl*m. budget=inf
    reproduces the no-filter book; a hard block is the m in {0,1} special case.
    Returns (total_pnl, list-of-scaled-trade-dicts) for risk stats."""
    events = []
    for t in all_trades:
        events.append((t["entry_t"], "open", t))
        events.append((t["exit_t"], "close", t))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "close" else 1))

    net = defaultdict(float)        # currency -> net exposure currently open
    open_pos = {}                   # sym -> (legs_applied, trade)
    scaled = []
    for _, kind, t in events:
        if kind == "close":
            if t["sym"] in open_pos and open_pos[t["sym"]][1] is t:
                legs, _ = open_pos.pop(t["sym"])
                for ccy, v in legs.items():
                    net[ccy] -= v
            continue
        if t["sym"] in open_pos:
            continue
        legs = _legs(t["sym"], t["dir"])
        # largest m<=1 s.t. |net[ccy] + m*legs[ccy]| <= budget for every leg
        m = 1.0
        for ccy, v in legs.items():
            cur = net[ccy]
            if abs(cur + v) <= budget:
                continue
            # need m where cur + m*v hits ±budget on the side v pushes toward
            limit = budget if v > 0 else -budget
            allowed = (limit - cur) / v
            m = min(m, max(0.0, allowed))
        if m < min_lot:
            continue
        applied = {ccy: m * v for ccy, v in legs.items()}
        for ccy, v in applied.items():
            net[ccy] += v
        open_pos[t["sym"]] = (applied, t)
        st = dict(t)
        st["pnl"] = t["pnl"] * m
        st["m"] = m
        scaled.append(st)
    return sum(s["pnl"] for s in scaled), scaled


def cap_replay(all_trades, cap):
    """Hard net-exposure cap, full lot only (the actual live design): take the
    signal at full size unless it would push |net| on any currency past `cap`,
    else block. cap=inf == no filter; cap=1 == block any same-currency stack.
    This is what goes into run_mt4 — no lot scaling. Returns list of taken trades."""
    events = []
    for t in all_trades:
        events.append((t["entry_t"], "open", t))
        events.append((t["exit_t"], "close", t))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "close" else 1))

    net = defaultdict(float)
    open_pos = {}
    taken = []
    for _, kind, t in events:
        if kind == "close":
            if t["sym"] in open_pos and open_pos[t["sym"]][1] is t:
                legs, _ = open_pos.pop(t["sym"])
                for ccy, v in legs.items():
                    net[ccy] -= v
            continue
        if t["sym"] in open_pos:
            continue
        legs = _legs(t["sym"], t["dir"])
        if any(abs(net[ccy] + v) > cap for ccy, v in legs.items()):
            continue
        for ccy, v in legs.items():
            net[ccy] += v
        open_pos[t["sym"]] = (legs, t)
        taken.append(t)
    return taken


def _stats(trades):
    n = len(trades)
    if n == 0:
        return n, 0.0, 0.0, 0.0
    wins = [x for x in trades if x["pnl"] > 0]
    gw = sum(x["pnl"] for x in wins)
    gl = abs(sum(x["pnl"] for x in trades if x["pnl"] <= 0))
    pf = gw / gl if gl > 0 else float("inf")
    return n, len(wins) / n * 100, sum(x["pnl"] for x in trades), pf


def _risk(trades):
    """Equity curve in CLOSE-time order — so simultaneous correlated losers
    show up as one deep drawdown, not netted away. Returns (PnL, maxDD$, Sharpe)."""
    if not trades:
        return 0.0, 0.0, 0.0
    ordered = sorted(trades, key=lambda t: t["exit_t"])
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in ordered:
        equity += t["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    pnls = pd.Series([t["pnl"] for t in ordered])
    sharpe = pnls.mean() / pnls.std() if pnls.std() > 0 else 0.0  # per-trade Sharpe
    return equity, max_dd, sharpe


def main():
    print("Fetching H4 and generating per-pair trade streams (LIVE engines)...")
    all_trades = []
    span_days = None
    for sym in SYMBOLS:
        df = fetch_ohlcv(sym, interval="4h", outputsize=OUTPUTSIZE)
        atr = _atr(df)
        tr = trades_for(sym, df, atr)
        all_trades.extend(tr)
        span_days = (df.index[-1] - df.index[0]).days
        print(f"  {sym:<8} {len(tr):>4} trades  via {_FX.strategy_name(sym)}")

    print(f"\nTotal trade signals across portfolio: {len(all_trades)} over ~{span_days} days")

    last_t = max(t["entry_t"] for t in all_trades)
    windows = [("18mo", None), ("6mo", 182), ("3mo", 91)]

    for label, days in windows:
        if days is None:
            window = all_trades
        else:
            cutoff = last_t - pd.Timedelta(days=days)
            window = [t for t in all_trades if t["entry_t"] >= cutoff]

        taken, blocked = replay(window)
        _, wt, _, pft = _stats(taken)
        _, wb, _, pfb = _stats(blocked)
        pnl_f, dd_f, sh_f = _risk(taken)          # with filter (current live)
        pnl_n, dd_n, sh_n = _risk(window)         # without filter (take everything)
        pdf = pnl_f / dd_f if dd_f else 0
        pdn = pnl_n / dd_n if dd_n else 0
        verdict = "WITHOUT wins" if (pdn > pdf and sh_n > sh_f) else \
                  "WITH wins" if (pdf > pdn and sh_f > sh_n) else "mixed"

        print(f"\n=== {label} window: {len(window)} signals, {len(blocked)} blocked "
              f"(blocked win {wb:.0f}% PF {pfb:.2f}) ===")
        print(f"  WITH filter:    PnL ${pnl_f:>+7.0f}  maxDD ${dd_f:>6.0f}  "
              f"PnL/DD {pdf:>5.2f}  Sharpe/tr {sh_f:>5.2f}")
        print(f"  WITHOUT filter: PnL ${pnl_n:>+7.0f}  maxDD ${dd_n:>6.0f}  "
              f"PnL/DD {pdn:>5.2f}  Sharpe/tr {sh_n:>5.2f}   -> {verdict}")
        # Net-exposure CAP, full lot only — the actual live design. Pick the cap.
        for cap in (1, 2, 3):
            tk = cap_replay(window, cap)
            pnl_c, dd_c, sh_c = _risk(tk)
            pdc = pnl_c / dd_c if dd_c else 0
            print(f"  CAP={cap}         PnL ${pnl_c:>+7.0f}  maxDD ${dd_c:>6.0f}  "
                  f"PnL/DD {pdc:>5.2f}  Sharpe/tr {sh_c:>5.2f}  ({len(tk)} taken)")

    # Per-symbol idle-capital breakdown on the full period.
    _, blocked_all = replay(all_trades)
    print("\nBlocked trades by symbol (full period, the idle-capital events):")
    by_sym = defaultdict(lambda: [0, 0.0])
    for t in blocked_all:
        by_sym[t["sym"]][0] += 1
        by_sym[t["sym"]][1] += t["pnl"]
    for s, (n, p) in sorted(by_sym.items(), key=lambda kv: -kv[1][0]):
        print(f"  {s:<8} {n:>3} blocked  ${p:>+8.0f}")

    print("\nRobust if WITHOUT wins across all three windows. If it flips on the "
          "shorter windows, the 18mo result is period-dependent, not a real edge.")


if __name__ == "__main__":
    main()
