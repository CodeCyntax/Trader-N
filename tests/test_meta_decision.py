"""
Unit tests for MetaDecisionBrain & Evidentiary Committee Synthesis.
Verifies dynamic hurdle conviction, adversarial vetoes, and causal auditability.
"""
import unittest
import time
from cognitive.meta_decision import MetaDecisionBrain
from cognitive.cluster_tracker import ClusterTracker
from core.models import TradeEvent, TradeType, ClusterHypothesis, ClusterArchetype
from core.bonding_curve import PumpBondingCurve


class TestMetaDecisionBrain(unittest.TestCase):

    def setUp(self):
        self.tracker = ClusterTracker()
        self.meta_brain = MetaDecisionBrain(self.tracker)
        self.curve = PumpBondingCurve()
        self.trade = TradeEvent(
            signature="test_meta_sig",
            mint="MintMetaTest11111111111111111111111111",
            trader_public_key="WalletMetaBuyer111111111111111111111111",
            tx_type=TradeType.BUY,
            sol_amount=1.0,
            token_amount=10000.0,
            timestamp=time.time(),
            bonding_curve_pct=25.0,
        )

    def test_adversarial_veto_overrides_all_other_brains(self):
        """Even under maximum organic flow and runner scores, an adversary veto immediately halts execution."""
        # Force adversary veto via dev dump
        context = {
            "dev_dumped": True,
            "vol_5m_sol": 100.0,
            "distinct_buyers_5m": 20,
            "buy_vol_5m_sol": 99.0,
            "sell_vol_5m_sol": 1.0,
            "dev_holding_pct": 0.0,
            "is_burner": False,
        }
        decision = self.meta_brain.evaluate(self.trade.mint, self.trade, self.curve, context, symbol="VETOED")
        self.assertEqual(decision.decision, "PASS")
        self.assertTrue(decision.veto_active)
        self.assertIn("AdversaryBrain", decision.veto_source)
        self.assertEqual(decision.symbol, "VETOED")
        self.assertIn("developer dumped", decision.dominant_reason.lower())

    def test_high_conviction_execute_decision(self):
        """When multi-brain synthesis achieves positive expected edge over hurdle, decision is EXECUTE."""
        # Set market velocity for organic momentum
        now = time.time()
        self.meta_brain.regime_brain.market_trade_timestamps = [now - i for i in range(30)]

        # Set bonding curve to prime 23.5% sweet spot
        self.curve.virtual_sol = int(50.0 * 1e9)
        self.curve.real_tokens_remaining = int(500_000_000 * 1e6)

        high_conviction_context = {
            "dev_dumped": False,
            "dev_holding_pct": 0.005,
            "persistence_score": 0.85,
            "vol_5m_sol": 25.0,
            "vol_1m_sol": 18.0,
            "buy_vol_5m_sol": 24.0,
            "sell_vol_5m_sol": 1.0,
            "distinct_buyers_5m": 12,
            "age_seconds": 120.0,
            "is_burner": False,
        }

        decision = self.meta_brain.evaluate(self.trade.mint, self.trade, self.curve, high_conviction_context, symbol="MOON")
        self.assertEqual(decision.decision, "EXECUTE")
        self.assertFalse(decision.veto_active)
        self.assertGreater(decision.expected_edge, decision.hurdle_rate)
        self.assertIn("High-conviction", decision.thesis)
        self.assertEqual(len(decision.brain_votes), 6)

    def test_insufficient_edge_produces_pass_with_attribution(self):
        """When expected edge does not beat hurdle, decision is PASS with identified dragging brain."""
        # Low liquidity and weak flow
        context = {
            "dev_dumped": False,
            "dev_holding_pct": 0.05,
            "vol_5m_sol": 0.5,
            "vol_1m_sol": 0.1,
            "buy_vol_5m_sol": 0.2,
            "sell_vol_5m_sol": 0.3,
            "distinct_buyers_5m": 2,
            "age_seconds": 600.0,
            "is_burner": False,
        }
        decision = self.meta_brain.evaluate(self.trade.mint, self.trade, self.curve, context, symbol="SLOW")
        self.assertEqual(decision.decision, "PASS")
        self.assertFalse(decision.veto_active)
        self.assertLessEqual(decision.expected_edge, decision.hurdle_rate)
        self.assertIn("Dragged by", decision.dominant_reason)


if __name__ == "__main__":
    unittest.main()
