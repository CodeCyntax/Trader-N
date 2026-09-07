"""
Unit tests for Counterfactual Shadow Ledger Engine.
Verifies registration of passed tokens, 60-minute continuous price tracking,
and resolution into confirmed dodges vs false negative missed runners.
"""
import unittest
import time
from pathlib import Path
from memory.database import DatabaseManager
from cognitive.counterfactual import CounterfactualEngine
from core.models import MetaDecision, BrainVote


class TestCounterfactualEngine(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_counterfactual.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        # Use short horizon of 10 seconds for unit test speed
        self.engine = CounterfactualEngine(self.db, shadow_horizon_seconds=10.0)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def _create_mock_decision(self, mint: str, decision: str = "PASS", symbol: str = "SHADOW") -> MetaDecision:
        vote = BrainVote(
            brain_name="RunnerBrain",
            score=0.45,
            confidence=0.8,
            key_evidence="Test evidence",
            veto=False,
        )
        return MetaDecision(
            mint=mint,
            symbol=symbol,
            decision=decision,
            expected_edge=0.01,
            hurdle_rate=0.05,
            regime="ORGANIC_MOMENTUM",
            brain_votes={"RunnerBrain": vote},
            veto_active=False,
            veto_source=None,
            dominant_reason="Edge below hurdle",
            suggested_size_sol=0.0,
            thesis="Passed due to low edge",
            timestamp=time.time(),
        )

    def test_register_evaluation_tracks_non_trades(self):
        """Passing a token registers it into active shadow ledger."""
        mint = "MintPassTest111111111111111111111111111"
        dec = self._create_mock_decision(mint, decision="PASS")

        self.engine.register_evaluation(dec, spot_price_sol=0.00001, curve_pct=25.0)
        self.assertIn(mint, self.engine.active_shadows)
        rec = self.engine.active_shadows[mint]
        self.assertEqual(rec.symbol, "SHADOW")
        self.assertEqual(rec.initial_price_sol, 0.00001)
        self.assertEqual(rec.status, "TRACKING")

    def test_execute_decision_not_shadowed(self):
        """Tokens that are EXECUTED are not registered into the shadow ledger."""
        mint = "MintExecTest11111111111111111111111111"
        dec = self._create_mock_decision(mint, decision="EXECUTE")

        self.engine.register_evaluation(dec, spot_price_sol=0.00001, curve_pct=25.0)
        self.assertNotIn(mint, self.engine.active_shadows)

    def test_confirmed_rug_dodge_resolution(self):
        """If passed token price drops > 50% upon horizon expiration, it resolves as CONFIRMED_RUG_DODGE."""
        mint = "MintRugTest1111111111111111111111111111"
        start_time = time.time() - 15.0  # 15s ago (> 10s horizon)
        dec = self._create_mock_decision(mint, decision="PASS")
        dec.timestamp = start_time

        self.engine.register_evaluation(dec, spot_price_sol=0.00010, curve_pct=30.0)
        # Manually set evaluation time to simulate elapsed time
        self.engine.active_shadows[mint].evaluation_time = start_time

        # Price drops to 0.00002 (-80% drop)
        self.engine.update_price(mint, current_price_sol=0.00002, current_time=time.time())

        # Should be resolved and removed from active memory
        self.assertNotIn(mint, self.engine.active_shadows)

        # Check DB summary
        summary = self.engine.get_summary()
        self.assertEqual(summary["confirmed_rug_dodges"], 1)
        self.assertGreater(summary["estimated_capital_preserved_sol"], 0.0)

    def test_false_negative_10x_runner_resolution(self):
        """If passed token peaks >= 10x upon horizon expiration, it resolves as FALSE_NEGATIVE_10X_RUNNER."""
        mint = "MintMissedRunner1111111111111111111111"
        start_time = time.time() - 15.0
        dec = self._create_mock_decision(mint, decision="PASS")
        dec.timestamp = start_time

        self.engine.register_evaluation(dec, spot_price_sol=0.00001, curve_pct=20.0)
        self.engine.active_shadows[mint].evaluation_time = start_time

        # Token runs to 12x
        self.engine.update_price(mint, current_price_sol=0.00012, current_time=time.time())

        self.assertNotIn(mint, self.engine.active_shadows)
        summary = self.engine.get_summary()
        self.assertEqual(summary["missed_runners_count"], 1)

    def test_resolve_counterfactuals_batch(self):
        """Batch resolution checks and resolves records older than horizon."""
        mint = "MintBatchResolve111111111111111111111"
        start_time = time.time() - 20.0
        dec = self._create_mock_decision(mint, decision="PASS")
        self.engine.register_evaluation(dec, spot_price_sol=0.0001, curve_pct=25.0)
        self.engine.active_shadows[mint].evaluation_time = start_time

        resolved = self.engine.resolve_counterfactuals(horizon_seconds=10.0)
        self.assertGreaterEqual(resolved, 1)
        self.assertNotIn(mint, self.engine.active_shadows)


if __name__ == "__main__":
    unittest.main()
