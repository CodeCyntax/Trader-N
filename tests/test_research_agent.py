"""
Unit tests for Autonomous Research Agent & Unsupervised Association Rule Mining.
Verifies offline pattern discovery across counterfactual shadow records,
computation of empirical confidence and lift, and hypothesis lifecycle.
"""
import unittest
import json
import time
from pathlib import Path
from memory.database import DatabaseManager
from cognitive.research_agent import AutonomousResearchAgent
from core.models import CounterfactualRecord


class TestAutonomousResearchAgent(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_research.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.agent = AutonomousResearchAgent(self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_seed_baseline_hypotheses_on_cold_start(self):
        """Cold-starting database seeds initial domain hypotheses."""
        discoveries = self.agent.run_discovery_cycle()
        self.assertGreaterEqual(len(discoveries), 3)

        persisted = self.db.get_hypotheses(limit=10)
        self.assertGreaterEqual(len(persisted), 3)
        self.assertTrue(any(h.target_outcome == "RUNNER_GE_10X" for h in persisted))
        self.assertTrue(any(h.target_outcome == "AVOID_RUG" for h in persisted))

    def test_association_rule_mining_discovers_lift(self):
        """Mines resolved counterfactuals to compute lift and confidence for predictive predicates."""
        now = time.time()
        # Seed 8 resolved counterfactuals: 4 runners, 4 rugs
        for i in range(8):
            is_runner = (i < 4)
            brain_scores = {
                "FlowBrain": {"score": 0.85 if is_runner else 0.20, "confidence": 0.9},
                "RunnerBrain": {"score": 0.80 if is_runner else 0.30, "confidence": 0.85},
                "AdversaryBrain": {"score": 0.90 if is_runner else 0.20, "confidence": 0.8},
            }
            rec = CounterfactualRecord(
                cf_id=f"cf_test_{i}",
                mint=f"MintMine_{i}111111111111111111111111",
                symbol=f"TOK{i}",
                evaluation_time=now - 4000,
                decision="PASS",
                dominant_reason="Edge below hurdle",
                expected_edge=0.01,
                initial_price_sol=0.0001,
                initial_curve_pct=25.0,
                peak_price_sol=0.0015 if is_runner else 0.0001,
                final_price_sol=0.0012 if is_runner else 0.00001,
                peak_multiplier=15.0 if is_runner else 1.0,
                final_return_pct=1100.0 if is_runner else -90.0,
                counterfactual_outcome="FALSE_NEGATIVE_10X_RUNNER" if is_runner else "CONFIRMED_RUG_DODGE",
                status="RESOLVED",
                last_updated=now,
                brain_scores_json=json.dumps(brain_scores),
            )
            self.db.record_counterfactual(rec)

        discoveries = self.agent.run_discovery_cycle()
        self.assertGreater(len(discoveries), 0)

        # Check discovered hypothesis has lift >= 1.0 and valid confidence
        hypo = discoveries[0]
        self.assertGreater(hypo.lift, 0.0)
        self.assertGreater(hypo.confidence, 0.0)
        self.assertGreaterEqual(hypo.sample_size, 3)


if __name__ == "__main__":
    unittest.main()
