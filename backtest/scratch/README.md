# backtest/scratch

Ad-hoc / one-off backtests. Run from the repo root with `PYTHONPATH`:

```bash
PYTHONPATH=. python3 backtest/scratch/chf_h1.py
```

Mechanics mirror `backtest_pair_sweep.py`: dispatched per-symbol engines,
R:R 1.5/1.5 ATR, 2% risk, $10k balance. Data via `history.fetcher.fetch_ohlcv`.

---

## CHF engine bake-off (2026-06-04)

Question: on the week of Mon 2026-06-01 the CHF pairs trended ~70 pips — could
the bot have caught it, and is the live engine choice wrong?

Files:
- `chf_week.py`     — live per-pair engine on USD/CHF & EUR/CHF since Monday
- `chf_engines.py`  — engine swap on that same week
- `chf_12mo.py`     — engine bake-off, **H4**, 12mo/6mo
- `chf_h1.py`       — same bake-off, **H1**, ~6mo

### Conclusion (do NOT change the live profiles)

The week was a clean trend; AdxMa entered Monday near the low on both pairs and
would have made ~$200/pair. But this was a timeframe artifact:

| Pair    | Engine             | H4 6mo PF | H1 6mo PF |
|---------|--------------------|-----------|-----------|
| USD/CHF | BreakoutAdx (LIVE) | 1.11      | **1.26** (best) |
| USD/CHF | AdxMa              | 1.44      | 0.86 (loses) |
| USD/CHF | EmaPsarTrend       | 1.65      | 1.05 |
| EUR/CHF | ZScoreAdx (LIVE)   | inf (3tr) | 1.12 (2tr) |
| EUR/CHF | TwoB               | 2.24      | 0.76 (loses) |
| EUR/CHF | AdxMa              | 0.65      | 1.06 |

- **USD/CHF**: BreakoutAdx is the *best* engine on H1 — keep it.
- **EUR/CHF**: no candidate has a convincing H1 edge — keep ZScoreAdx.

The alternative engines win only on H4; the edge inverts on H1. We left no money
on the table on the timeframe the bot actually trades.
