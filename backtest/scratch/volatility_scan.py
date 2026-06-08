"""
Raw tradability scan — volatility & trendiness, engine-agnostic. Answers "is there
enough movement to extract profit from", NOT "does our current engine work".

Metrics (H4 bars, 12mo + 6mo):
  ATR%      — ATR(14) as % of price (normalized vol, comparable across instruments)
  ADR%      — avg daily high-low range as % of price (intraday room)
  efficiency— |net move over N bars| / sum(|bar moves|): trend vs chop (higher = trendier)
  swing%    — avg % size of 20-bar swing highs→lows (how big the exploitable swings are)

Reference set = instruments we already trade well, so candidates are judged relative
to a known-good baseline rather than absolute thresholds.

Run: python3 -m backtest.scratch.volatility_scan
"""
import numpy as np
import pandas as pd
from history.fetcher import fetch_ohlcv

ATR_PERIOD = 14
BARS_PER_DAY_H4 = 6

REFERENCE = ["CHF/JPY", "USD/CAD", "DE40", "XAU/USD"]      # known-good baselines
CANDIDATES = ["GBP/CHF", "AUD/JPY", "EUR/AUD", "EUR/GBP", "GBP/JPY", "CAD/JPY",
              "US30", "JP225", "UK100", "EU50", "FRA40"]


def atr_pct(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean()
    return (atr / c * 100).dropna()


def adr_pct(df):
    daily = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    return ((daily["high"] - daily["low"]) / daily["close"] * 100).dropna()


def efficiency(df, window=BARS_PER_DAY_H4 * 5):
    """Fraction of motion that is directional over rolling `window` bars (5 days)."""
    c = df["close"]
    net = (c - c.shift(window)).abs()
    gross = c.diff().abs().rolling(window).sum()
    return (net / gross).replace([np.inf, -np.inf], np.nan).dropna()


def swing_pct(df, lookback=20):
    """Avg % distance between rolling 20-bar high and low (exploitable swing size)."""
    hi = df["high"].rolling(lookback).max()
    lo = df["low"].rolling(lookback).min()
    return ((hi - lo) / df["close"] * 100).dropna()


def scan(sym, w):
    df = fetch_ohlcv(sym, interval="4h", outputsize=2600)
    df = df[df.index >= w]
    if len(df) < 60:
        return None
    return (
        atr_pct(df).mean(),
        adr_pct(df).mean(),
        efficiency(df).mean(),
        swing_pct(df).mean(),
        len(df),
    )


def main():
    now = pd.Timestamp.now().tz_localize(None)
    w12, w6 = now - pd.Timedelta(days=365), now - pd.Timedelta(days=182)
    hdr = f"{'symbol':8} | {'ATR%12m':>7} {'ADR%12m':>7} {'eff12m':>6} {'swing%':>6} | {'ATR%6m':>6} {'eff6m':>5}"

    def block(title, syms):
        print(f"\n### {title}")
        print(hdr); print("─" * len(hdr))
        for s in syms:
            try:
                r12 = scan(s, w12); r6 = scan(s, w6)
            except Exception as e:
                print(f"{s:8} | NO DATA ({type(e).__name__})"); continue
            if r12 is None:
                print(f"{s:8} | too few bars"); continue
            a12, d12, e12, sw12, n = r12
            a6, d6, e6, sw6, _ = r6 if r6 else (0, 0, 0, 0, 0)
            print(f"{s:8} | {a12:>6.2f}% {d12:>6.2f}% {e12:>6.2f} {sw12:>5.1f}% | {a6:>5.2f}% {e6:>5.2f}")

    block("REFERENCE (торгуем успешно)", REFERENCE)
    block("CANDIDATES", CANDIDATES)
    print("\nЧитать: ATR%/ADR%/swing% — амплитуда движения (больше = больше потенциала).")
    print("eff (efficiency 0..1) — доля направленного хода: >0.35 трендовый, <0.25 шумный/диапазонный.")


if __name__ == "__main__":
    main()
