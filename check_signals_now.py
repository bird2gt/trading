"""Dry-run: what would the bot see RIGHT NOW across the full session-active universe?

Replays the live signal generation + offline filters (market structure, F&G for
crypto) on current H4 data, without touching the EA. Network filters (sentiment,
macro bias, correlation, high-impact calendar) only ADD blocks downstream — they
never create entries — so a candidate here is the *most* that could trade.

Run from the project root:  python3 check_signals_now.py
"""
from datetime import datetime, timezone

import run_mt4 as r
from history.fetcher import fetch_ohlcv
from strategy.structure import market_structure
from analytics.fear_greed import get_value as get_fg_value
from config.profiles import SYMBOL_GROUP


def signal_for(symbol: str, df_closed) -> int:
    """Mirror run_mt4's strategy routing for a symbol on closed bars."""
    group = SYMBOL_GROUP.get(symbol)
    if symbol in r.FOREX_SYMBOLS:
        return r.STRATEGY_FOREX.generate_signal(df_closed, symbol=symbol)
    if group == "crypto":
        return r.STRATEGY_CRYPTO.generate_signal(df_closed)
    if group == "metal":
        if symbol == "XAG/USD":
            df_xau = fetch_ohlcv("XAU/USD", outputsize=221, interval="4h")
            return r.STRATEGY_METALS_XAG.generate_signal(df_closed, df_xau=df_xau.iloc[:-1])
        return r.STRATEGY_METALS_XAU.generate_signal(df_closed)
    if group == "index":
        return r.STRATEGY_INDEX.generate_signal(df_closed)
    if group == "energy":
        return r.STRATEGY_ENERGY.generate_signal(df_closed)
    return 0


def main():
    now = datetime.now(timezone.utc)
    active = r._active_symbols()
    print(f"UTC {now:%Y-%m-%d %H:%M}  weekday={now.weekday()}  "
          f"session-active symbols: {len(active)}")
    print(f"{active}\n")

    print(f"{'Symbol':<9} {'Grp':<12} {'Signal':<6} Verdict")
    print("-" * 72)
    candidates = []
    for sym in active:
        group = SYMBOL_GROUP.get(sym, "?")
        try:
            df = fetch_ohlcv(sym, outputsize=221, interval="4h")
            df_closed = df.iloc[:-1]  # closed bars only — no repaint
            sig = signal_for(sym, df_closed)
            if sig == 0:
                print(f"{sym:<9} {group:<12} {'—':<6} no signal")
                continue
            action = "BUY" if sig == 1 else "SELL"
            struct = market_structure(df_closed)
            if sig == 1 and struct == -1:
                print(f"{sym:<9} {group:<12} {action:<6} BLOCKED — bearish structure")
                continue
            if sig == -1 and struct == 1:
                print(f"{sym:<9} {group:<12} {action:<6} BLOCKED — bullish structure")
                continue
            if group == "crypto":
                fg = get_fg_value(now)
                if fg is not None and ((sig == 1 and fg < 50) or (sig == -1 and fg >= 50)):
                    print(f"{sym:<9} {group:<12} {action:<6} BLOCKED — F&G={fg}")
                    continue
            print(f"{sym:<9} {group:<12} {action:<6} "
                  f"PASSES offline → then checks sentiment/bias/corr/news")
            candidates.append((sym, action))
        except Exception as e:
            print(f"{sym:<9} {group:<12} {'ERR':<6} {e}")

    print(f"\nCandidates passing offline filters: {len(candidates)}")
    for sym, action in candidates:
        print(f"  {action} {sym}")
    print("\nNote: network filters (sentiment/bias/correlation/calendar) can only "
          "block further — real entries are ≤ this count.")


if __name__ == "__main__":
    main()
