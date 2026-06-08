"""
Validate the oil geo-risk news window (digest flag + ≥3σ price confirmation).
Standalone check in the project style: synthetic 15m frames, no network.

Run: python -m backtest.scratch.oil_geo_window
"""
import sys
import types
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FLAG = ROOT / "forecasts" / f"{date.today()}_oil_geo.flag"


def _frame(shock_sigmas: float, n: int = 200) -> pd.DataFrame:
    """Calm 15m series, then a final 3-bar move of `shock_sigmas` normal sigmas."""
    rng = np.random.default_rng(0)
    base_ret = 0.001  # ~0.1% normal 15m sigma
    rets = rng.normal(0, base_ret, n)
    price = 80.0 * np.cumprod(1 + rets)
    if shock_sigmas:
        # inject the move across the last REACTION_CANDLES (3) bars
        price[-3:] *= (1 + shock_sigmas * base_ret)
    idx = pd.date_range("2026-06-08", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"close": price, "high": price, "low": price, "open": price}, index=idx)


def main():
    from bias.surprise import latest_move_z
    import run_mt4

    # 1. latest_move_z sizing: a ~5σ injected move should read clearly above 3.
    z_big = latest_move_z(_frame(5.0))
    z_calm = latest_move_z(_frame(0.0))
    print(f"latest_move_z: shock≈5σ → {z_big:+.1f} | calm → {z_calm:+.1f}")
    assert z_big is not None and abs(z_big) >= run_mt4.GEO_Z_MIN, "5σ shock not detected"
    assert z_calm is None or abs(z_calm) < run_mt4.GEO_Z_MIN, "calm market falsely flagged"

    # Stub fetch_ohlcv so is_oil_geo_active runs offline.
    shock = {"v": 0.0}
    run_mt4.fetch_ohlcv = lambda *a, **k: _frame(shock["v"])

    # 2. Flag CLEAR → window closed regardless of move.
    FLAG.write_text("0")
    shock["v"] = 5.0
    active, _ = run_mt4.is_oil_geo_active("WTI")
    print(f"flag=0, 5σ move → window {'OPEN' if active else 'closed'}")
    assert not active, "window opened with flag clear"

    # 3. Flag ARMED + strong move → window OPEN.
    FLAG.write_text("1")
    shock["v"] = 5.0
    active, ev = run_mt4.is_oil_geo_active("WTI")
    print(f"flag=1, 5σ move → window {'OPEN' if active else 'closed'} ({ev})")
    assert active, "window did not open on armed flag + shock"

    # 4. Flag ARMED but quiet market (<3σ) → window closed (conservative gate).
    shock["v"] = 1.0
    active, _ = run_mt4.is_oil_geo_active("WTI")
    print(f"flag=1, 1σ move → window {'OPEN' if active else 'closed'}")
    assert not active, "window opened below 3σ threshold"

    # 5. Non-oil symbol never uses this channel.
    shock["v"] = 5.0
    active, _ = run_mt4.is_oil_geo_active("EUR/USD")
    print(f"flag=1, 5σ move, EUR/USD → window {'OPEN' if active else 'closed'}")
    assert not active, "non-oil symbol used oil-geo channel"

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        main()
    finally:
        # leave today's flag as we found it: clear (the live digest rewrites it)
        if FLAG.exists():
            FLAG.unlink()
