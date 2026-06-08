"""
Validate the oil geo-risk ALERT (flag + >=3σ move -> Telegram once/day, no trade
window). Standalone, offline: synthetic frames + stubbed fetch/telegram.

Run: python -m backtest.scratch.oil_geo_window
"""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FLAG = ROOT / "forecasts" / f"{date.today()}_oil_geo.flag"


def _frame(shock_sigmas: float, n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    base_ret = 0.001
    rets = rng.normal(0, base_ret, n)
    price = 80.0 * np.cumprod(1 + rets)
    if shock_sigmas:
        price[-3:] *= (1 + shock_sigmas * base_ret)
    idx = pd.date_range("2026-06-08", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"close": price, "high": price, "low": price, "open": price}, index=idx)


def main():
    import run_mt4

    sent = []
    shock = {"v": 0.0}
    run_mt4.fetch_ohlcv = lambda *a, **k: _frame(shock["v"])
    run_mt4._send_telegram = lambda text: sent.append(text)

    def reset():
        sent.clear()
        run_mt4._oil_geo_alerted.clear()
        run_mt4._oil_geo_alert_day = None

    # 1. Flag clear -> no alert even on a big move.
    FLAG.write_text("0"); reset(); shock["v"] = 5.0
    run_mt4.check_oil_geo_alert("WTI")
    print(f"flag=0, 5sigma -> alerts={len(sent)}")
    assert not sent

    # 2. Flag armed + strong move -> exactly one alert.
    FLAG.write_text("1"); reset(); shock["v"] = 5.0
    run_mt4.check_oil_geo_alert("WTI")
    print(f"flag=1, 5sigma -> alerts={len(sent)} | msg: {sent[0] if sent else None}")
    assert len(sent) == 1

    # 3. Dedup: repeated cycles same day -> still one alert.
    run_mt4.check_oil_geo_alert("WTI")
    run_mt4.check_oil_geo_alert("WTI")
    print(f"flag=1, repeated cycles -> alerts={len(sent)} (deduped)")
    assert len(sent) == 1

    # 4. Flag armed but quiet (<3sigma) -> no alert.
    reset(); shock["v"] = 1.0
    run_mt4.check_oil_geo_alert("WTI")
    print(f"flag=1, 1sigma -> alerts={len(sent)}")
    assert not sent

    # 5. Non-oil symbol -> never alerts.
    reset(); shock["v"] = 5.0
    run_mt4.check_oil_geo_alert("EUR/USD")
    print(f"flag=1, 5sigma, EUR/USD -> alerts={len(sent)}")
    assert not sent

    # 6. Crucial: geo no longer opens a trade window. The trade-window function
    #    must be gone (channel demoted to alert-only).
    assert not hasattr(run_mt4, "is_oil_geo_active"), "trade-window path still present"
    print("trade-window path removed: OK")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        main()
    finally:
        if FLAG.exists():
            FLAG.unlink()
