import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd


class RunMt4RiskTests(unittest.TestCase):
    def test_jpy_cross_pip_value_uses_usdjpy(self):
        import run_mt4

        def fake_fetch(symbol, outputsize=1, interval="1h"):
            self.assertEqual(symbol, "USD/JPY")
            return pd.DataFrame({"close": [160.0]})

        with patch.object(run_mt4, "fetch_ohlcv", fake_fetch):
            self.assertAlmostEqual(run_mt4._forex_pip_value_usd("USD/JPY", 160.0), 6.25)
            self.assertAlmostEqual(run_mt4._forex_pip_value_usd("NZD/JPY", 92.0), 6.25)
            self.assertAlmostEqual(run_mt4._forex_pip_value_usd("CHF/JPY", 200.0), 6.25)

    def test_send_signal_blocks_adjusted_lots_below_minimum(self):
        import run_mt4

        df = pd.DataFrame(
            {
                "open": [1.0] * 20,
                "high": [1.1] * 20,
                "low": [0.9] * 20,
                "close": [1.0] * 20,
            }
        )
        session = Mock()
        with patch.object(run_mt4, "_calc_lots", return_value=0.01), \
             patch.object(run_mt4, "_bridge_session", session):
            sent = run_mt4.send_signal("EUR/USD", "BUY", df, size_mult=0.2)
        self.assertFalse(sent)
        session.post.assert_not_called()


class BridgeReadinessTests(unittest.TestCase):
    def test_ready_requires_fresh_balance_and_positions(self):
        import broker.mt4_bridge as bridge

        with tempfile.TemporaryDirectory() as tmp:
            old_dir = bridge.MT4_FILES_DIR
            old_stale = bridge.MT4_FILE_STALE_SECONDS
            try:
                bridge.MT4_FILES_DIR = Path(tmp)
                bridge.MT4_FILE_STALE_SECONDS = 30
                self.assertFalse(bridge.ready()["ok"])

                (bridge.MT4_FILES_DIR / "balance.txt").write_text("1234.56", encoding="utf-8")
                (bridge.MT4_FILES_DIR / "positions.txt").write_text("", encoding="utf-8")
                result = bridge.ready()
                self.assertTrue(result["ok"])
                self.assertEqual(result["balance"], 1234.56)
            finally:
                bridge.MT4_FILES_DIR = old_dir
                bridge.MT4_FILE_STALE_SECONDS = old_stale


class LearningTests(unittest.TestCase):
    def test_ustechcash_normalizes_to_ustec(self):
        from analytics.learning import normalize_symbol

        self.assertEqual(normalize_symbol(".USTECHCash"), "USTEC")
        self.assertEqual(normalize_symbol("USTECHCash"), "USTEC")


if __name__ == "__main__":
    unittest.main()
