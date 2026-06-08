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


class MeanRevertFlagTests(unittest.TestCase):
    def test_revert_symbols_flagged(self):
        import run_mt4

        for s in ["EUR/USD", "USD/CAD", "EUR/CHF", "GBP/JPY", "JP225", "US30", "US500"]:
            self.assertTrue(run_mt4._is_mean_reverting(s), s)
        for s in ["CHF/JPY", "AUD/JPY", "USD/CHF", "USTEC", "DE40", "XAU/USD", "BTC/USD"]:
            self.assertFalse(run_mt4._is_mean_reverting(s), s)


class EarlyExitTests(unittest.TestCase):
    def _declining_df(self, n=30):
        closes = [120.0 - i for i in range(n)]  # newest = lowest → MA5 < MA20
        return pd.DataFrame({
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low":  [c - 0.5 for c in closes],
            "close": closes,
        })

    def test_ma_exit_skipped_for_mean_revert(self):
        import run_mt4

        df = self._declining_df()
        run_mt4._active_signals["GBP/JPY"] = "BUY"
        run_mt4._entry_prices["GBP/JPY"] = df["close"].iloc[-1]  # so impulse exit doesn't fire
        self.addCleanup(run_mt4._active_signals.pop, "GBP/JPY", None)
        self.addCleanup(run_mt4._entry_prices.pop, "GBP/JPY", None)
        with patch.object(run_mt4, "_send_close") as close:
            result = run_mt4._check_early_exit("GBP/JPY", df)
        self.assertFalse(result)
        close.assert_not_called()

    def test_ma_exit_fires_for_trend_pair(self):
        import run_mt4

        df = self._declining_df()
        run_mt4._active_signals["CHF/JPY"] = "BUY"
        run_mt4._entry_prices["CHF/JPY"] = df["close"].iloc[-1]
        self.addCleanup(run_mt4._active_signals.pop, "CHF/JPY", None)
        self.addCleanup(run_mt4._entry_prices.pop, "CHF/JPY", None)
        with patch.object(run_mt4, "_send_close") as close:
            result = run_mt4._check_early_exit("CHF/JPY", df)
        self.assertTrue(result)
        close.assert_called_once()


class RsiMeanRevertTests(unittest.TestCase):
    def _strat(self):
        from strategy.rsi_mean_revert import RSIMeanRevert
        return RSIMeanRevert(period=14, oversold=30, overbought=70)

    def _rsi_series(self, prev, last, n=30):
        vals = [50.0] * n
        vals[-2], vals[-1] = prev, last
        return pd.Series(vals)

    def test_fires_on_cross_into_oversold(self):
        strat = self._strat()
        df = pd.DataFrame({"close": [1.0] * 30})
        with patch.object(strat, "_rsi", return_value=self._rsi_series(35.0, 25.0)):
            self.assertEqual(strat.generate_signal(df), 1)

    def test_no_resignal_while_already_oversold(self):
        strat = self._strat()
        df = pd.DataFrame({"close": [1.0] * 30})
        with patch.object(strat, "_rsi", return_value=self._rsi_series(25.0, 20.0)):
            self.assertEqual(strat.generate_signal(df), 0)

    def test_fires_on_cross_into_overbought(self):
        strat = self._strat()
        df = pd.DataFrame({"close": [1.0] * 30})
        with patch.object(strat, "_rsi", return_value=self._rsi_series(65.0, 75.0)):
            self.assertEqual(strat.generate_signal(df), -1)


if __name__ == "__main__":
    unittest.main()
