"""
Unit tests for the 6 Cognitive Brains in Trader-N.
Verifies GraphBrain, FlowBrain, RunnerBrain, AdversaryBrain (with VETO power),
ContrarianBrain, and RegimeBrain.
"""
import unittest
import time
from cognitive.brains.graph_brain import GraphBrain
from cognitive.brains.flow_brain import FlowBrain
from cognitive.brains.runner_brain import RunnerBrain
from cognitive.brains.adversary_brain import AdversaryBrain
from cognitive.brains.contrarian_brain import ContrarianBrain
from cognitive.brains.regime_brain import RegimeBrain
from cognitive.cluster_tracker import ClusterTracker
from core.models import TradeEvent, TradeType, ClusterHypothesis, ClusterArchetype
from core.bonding_curve import PumpBondingCurve


class TestCognitiveBrains(unittest.TestCase):

    def setUp(self):
        self.tracker = ClusterTracker()
        self.curve = PumpBondingCurve()
        self.trade = TradeEvent(
            signature="test_sig",
            mint="MintTestBrain11111111111111111111111111",
            trader_public_key="WalletBuyer11111111111111111111111111",
            tx_type=TradeType.BUY,
            sol_amount=1.0,
            token_amount=10000.0,
            timestamp=time.time(),
            bonding_curve_pct=25.0,
        )

    def test_adversary_brain_veto_on_dev_dump(self):
        """AdversaryBrain exercises hard veto when dev has dumped."""
        brain = AdversaryBrain(self.tracker)
        context = {
            "dev_dumped": True,
            "dev_holding_pct": 0.0,
            "is_burner": False,
        }
        vote = brain.evaluate(self.trade.mint, self.trade, self.curve, context)
        self.assertTrue(vote.veto)
        self.assertLessEqual(vote.score, 0.10)
        self.assertIn("developer dumped", vote.key_evidence.lower())

    def test_adversary_brain_veto_on_cabal_cluster(self):
        """AdversaryBrain exercises hard veto when buyer belongs to an INSIDER_CABAL cluster."""
        brain = AdversaryBrain(self.tracker)
        # Register an insider cabal cluster for buyer
        cid = "cluster_cabal_test"
        self.tracker.clusters[cid] = ClusterHypothesis(
            cluster_id=cid,
            member_addresses=[self.trade.trader_public_key],
            archetype=ClusterArchetype.INSIDER_CABAL,
            coordination_probability=0.85,
            avg_entry_delta_seconds=0.5,
            total_co_trades=3,
            shared_token_mints=[self.trade.mint],
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.tracker.wallet_to_cluster[self.trade.trader_public_key] = cid

        context = {"dev_dumped": False, "is_burner": False, "dev_holding_pct": 0.01}
        vote = brain.evaluate(self.trade.mint, self.trade, self.curve, context)
        self.assertTrue(vote.veto)
        self.assertIn("insider cabal", vote.key_evidence.lower())

    def test_adversary_brain_no_veto_on_large_swarm(self):
        """AdversaryBrain does NOT veto when cluster has > 20 members (broad retail swarm)."""
        brain = AdversaryBrain(self.tracker)
        cid = "cluster_swarm_test"
        # 25 members
        members = [self.trade.trader_public_key] + [f"SwarmMember_{i}" for i in range(24)]
        self.tracker.clusters[cid] = ClusterHypothesis(
            cluster_id=cid,
            member_addresses=members,
            archetype=ClusterArchetype.INSIDER_CABAL,
            coordination_probability=0.90,
            avg_entry_delta_seconds=0.5,
            total_co_trades=10,
        )
        self.tracker.wallet_to_cluster[self.trade.trader_public_key] = cid

        context = {"dev_dumped": False, "is_burner": False, "dev_holding_pct": 0.01}
        vote = brain.evaluate(self.trade.mint, self.trade, self.curve, context)
        self.assertFalse(vote.veto)
        self.assertIn("swarm", vote.key_evidence.lower())

    def test_flow_brain_evaluates_microstructure(self):
        """FlowBrain scores high on accelerating net buy volume and distinct buyers."""
        brain = FlowBrain()
        bullish_context = {
            "vol_5m_sol": 15.0,
            "vol_1m_sol": 10.0,  # 66% in last 1 min -> high acceleration
            "buy_vol_5m_sol": 14.0,
            "sell_vol_5m_sol": 1.0,  # > 90% buy flow
            "distinct_buyers_5m": 8,
        }
        vote = brain.evaluate(self.trade.mint, self.trade, self.curve, bullish_context)
        self.assertFalse(vote.veto)
        self.assertGreaterEqual(vote.score, 0.70)
        self.assertGreaterEqual(vote.confidence, 0.80)

    def test_runner_brain_convexity_curve(self):
        """RunnerBrain gives premium score in the 15%-42% curve sweet-spot with minimal dev holding."""
        brain = RunnerBrain()
        # Set curve reserves to ~23.5% progress (virtual_sol = 50 SOL)
        self.curve.virtual_sol = int(50.0 * 1e9)
        self.curve.real_tokens_remaining = int(500_000_000 * 1e6)

        sweet_context = {
            "dev_holding_pct": 0.01,  # 1% dev hold
            "distinct_buyers_5m": 9,
            "age_seconds": 180.0,
        }
        vote = brain.evaluate(self.trade.mint, self.trade, self.curve, sweet_context)
        self.assertFalse(vote.veto)
        self.assertGreaterEqual(vote.score, 0.75)
        self.assertIn("Convexity", vote.key_evidence)

    def test_contrarian_brain_fades_retail_exhaustion(self):
        """ContrarianBrain suppresses score when curve is late (>65%) and retail FOMO churn is peaking."""
        brain = ContrarianBrain()
        # Late curve: 90 SOL virtual (60 SOL real / 85 SOL = 70.6% progress)
        self.curve.virtual_sol = int(90.0 * 1e9)
        self.curve.real_tokens_remaining = int(100_000_000 * 1e6)

        fomo_context = {
            "distinct_buyers_5m": 25,
            "vol_5m_sol": 80.0,
            "vol_1m_sol": 50.0,
            "persistence_score": 0.30,  # Low persistence retail
        }
        vote = brain.evaluate(self.trade.mint, self.trade, self.curve, fomo_context)
        self.assertLessEqual(vote.score, 0.45)
        self.assertIn("FOMO exhaustion", vote.key_evidence)

    def test_regime_brain_hurdle_calibration(self):
        """RegimeBrain sets hurdle rate based on macro activity."""
        brain = RegimeBrain()
        now = time.time()

        # Simulate deadzone: only 2 trades in 5 minutes
        brain.market_trade_timestamps = [now - 100, now - 50]
        context = {"cabal_clusters_count": 0}
        vote_dead = brain.evaluate(self.trade.mint, self.trade, self.curve, context)
        self.assertEqual(vote_dead.metrics["regime"], "LOW_LIQUIDITY_DEADZONE")
        self.assertGreaterEqual(vote_dead.metrics["hurdle_rate"], 0.10)

        # Simulate organic momentum: 25 trades in 5 minutes
        brain.market_trade_timestamps = [now - (i * 5) for i in range(25)]
        vote_organic = brain.evaluate(self.trade.mint, self.trade, self.curve, context)
        self.assertEqual(vote_organic.metrics["regime"], "ORGANIC_MOMENTUM")
        self.assertEqual(vote_organic.metrics["hurdle_rate"], 0.05)


if __name__ == "__main__":
    unittest.main()
