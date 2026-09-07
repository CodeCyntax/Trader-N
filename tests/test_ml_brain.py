"""
Stress-test suite for LocalOnlineMLEngine:
- Mathematical robustness: zero division immunity, strictly bounded features [0, 1]
- Inference speed (< 50 microseconds)
- Online AdaGrad convergence & bounded weight updates
- SQLite state persistence & weight restoration
"""
import unittest
import time
from pathlib import Path
from learning.ml_brain import LocalOnlineMLEngine
from memory.database import DatabaseManager


class TestLocalOnlineMLEngine(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_ml.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.ml_engine = LocalOnlineMLEngine(db_manager=self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_feature_extraction_boundedness_and_safety(self):
        """Tests that all features are strictly bounded in [0.0, 1.0] under extreme values."""
        # Extreme case 1: all zeros / negative values
        feat_zero = self.ml_engine.extract_features(
            persistence_score=-5.0,
            follower_pnl_sol=-10.0,
            bayesian_wins=0,
            bayesian_losses=0,
            curve_pct=-10.0,
            volume_5m_sol=0.0,
            distinct_buyers_5m=0,
            buy_vol_5m_sol=0.0,
            sell_vol_5m_sol=0.0,
            dev_holding_pct=0.0,
            token_age_seconds=-100.0,
            vol_1m_sol=0.0,
        )
        self.assertEqual(len(feat_zero), 10)
        for val in feat_zero:
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

        # Extreme case 2: massive numbers (overflow stress test)
        feat_huge = self.ml_engine.extract_features(
            persistence_score=100.0,
            follower_pnl_sol=500.0,
            bayesian_wins=1000,
            bayesian_losses=10,
            curve_pct=500.0,
            volume_5m_sol=100_000.0,
            distinct_buyers_5m=50_000,
            buy_vol_5m_sol=100_000.0,
            sell_vol_5m_sol=0.0,
            dev_holding_pct=2.0,
            token_age_seconds=1_000_000.0,
            vol_1m_sol=100_000.0,
        )
        self.assertEqual(len(feat_huge), 10)
        for val in feat_huge:
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

    def test_inference_latency_sub_millisecond(self):
        """Verifies prediction executes in under 50 microseconds per trade."""
        features = [0.8, 0.7, 0.6, 0.35, 0.5, 0.4, 0.8, 0.02, 0.2, 0.6]
        start = time.perf_counter()
        for _ in range(1000):
            p = self.ml_engine.predict_win_probability(features)
        total_time = time.perf_counter() - start
        avg_latency_us = (total_time / 1000) * 1_000_000
        self.assertLess(avg_latency_us, 50.0, f"Inference latency too slow: {avg_latency_us:.2f} us")
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_online_gradient_learning_and_boundedness(self):
        """Verifies AdaGrad learning updates weights predictably and stays bounded in [-4.0, 4.0]."""
        high_alpha_feat = [0.9, 0.8, 0.75, 0.35, 0.8, 0.7, 0.9, 0.01, 0.1, 0.8]
        initial_prob = self.ml_engine.predict_win_probability(high_alpha_feat)

        # Simulate 10 successful runner trades with high returns (+80%)
        for _ in range(10):
            self.ml_engine.update_online(high_alpha_feat, return_pct=80.0)

        boosted_prob = self.ml_engine.predict_win_probability(high_alpha_feat)
        self.assertGreater(boosted_prob, initial_prob, "Model must learn to increase win probability on runners")

        # Verify all weights stay within hyperbox projection [-4.0, 4.0]
        for w in self.ml_engine.weights:
            self.assertGreaterEqual(w, -4.0)
            self.assertLessEqual(w, 4.0)

    def test_sqlite_persistence_and_restoration(self):
        """Verifies weights and calibration metrics survive process restart."""
        feat = [0.5] * 10
        self.ml_engine.update_online(feat, return_pct=50.0)
        saved_weights = list(self.ml_engine.weights)
        saved_brier = self.ml_engine.rolling_brier_score

        # Instantiate fresh engine instance connecting to same test DB
        restored_engine = LocalOnlineMLEngine(db_manager=self.db)
        self.assertEqual(restored_engine.total_updates, 1)
        self.assertEqual(len(restored_engine.weights), 10)
        for w_orig, w_rest in zip(saved_weights, restored_engine.weights):
            self.assertAlmostEqual(w_orig, w_rest, places=4)
        self.assertAlmostEqual(restored_engine.rolling_brier_score, saved_brier, places=4)


if __name__ == "__main__":
    unittest.main()
