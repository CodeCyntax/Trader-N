"""
Unit tests for Probabilistic Cluster Tracker & Identity Drift Engine.
Verifies temporal synchrony detection (<= 2.5s), Bayesian coordination probability,
and Kullback-Leibler (D_KL) behavioral drift suppression.
"""
import unittest
import time
from pathlib import Path
from memory.database import DatabaseManager
from cognitive.cluster_tracker import ClusterTracker
from core.models import TradeEvent, TradeType, ClusterArchetype


class TestClusterTracker(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_clusters.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.tracker = ClusterTracker(self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_temporal_synchrony_and_clustering(self):
        """Two wallets buying the same token within 1.0s should be clustered with high coordination."""
        now = time.time()
        w1 = "WalletInsiderA11111111111111111111111111"
        w2 = "WalletInsiderB22222222222222222222222222"

        # Simulate co-entry on 3 tokens within 1.0 second
        for i in range(3):
            mint = f"TokenCoEntry{i}111111111111111111111111"
            t1 = TradeEvent(
                signature=f"sig_{i}_1",
                mint=mint,
                trader_public_key=w1,
                tx_type=TradeType.BUY,
                sol_amount=1.0,
                token_amount=10000.0,
                timestamp=now + (i * 10),
                bonding_curve_pct=15.0,
            )
            t2 = TradeEvent(
                signature=f"sig_{i}_2",
                mint=mint,
                trader_public_key=w2,
                tx_type=TradeType.BUY,
                sol_amount=1.0,
                token_amount=10000.0,
                timestamp=now + (i * 10) + 0.8,  # 0.8s apart (< 2.5s)
                bonding_curve_pct=16.0,
            )
            self.tracker.record_trade(t1)
            self.tracker.record_trade(t2)

        cluster1 = self.tracker.get_cluster(w1)
        cluster2 = self.tracker.get_cluster(w2)
        self.assertIsNotNone(cluster1)
        self.assertEqual(cluster1.cluster_id, cluster2.cluster_id)
        self.assertGreaterEqual(cluster1.coordination_probability, 0.60)
        self.assertLessEqual(cluster1.avg_entry_delta_seconds, 2.5)

    def test_deployer_sybil_archetype_classification(self):
        """When dev wallet co-buys with another wallet, archetype classifies as DEPLOYER_SYBIL."""
        now = time.time()
        dev = "WalletDevCreator1111111111111111111111111"
        sybil = "WalletSybilClone222222222222222222222222"
        mint = "MintSybilTest11111111111111111111111111"

        t1 = TradeEvent(
            signature="sig_dev",
            mint=mint,
            trader_public_key=dev,
            tx_type=TradeType.BUY,
            sol_amount=2.0,
            token_amount=20000.0,
            timestamp=now,
            bonding_curve_pct=1.0,
        )
        t2 = TradeEvent(
            signature="sig_sybil",
            mint=mint,
            trader_public_key=sybil,
            tx_type=TradeType.BUY,
            sol_amount=1.5,
            token_amount=15000.0,
            timestamp=now + 0.5,
            bonding_curve_pct=3.0,
        )

        self.tracker.record_trade(t1, dev_wallet=dev)
        self.tracker.record_trade(t2, dev_wallet=dev)

        cluster = self.tracker.get_cluster(dev)
        self.assertIsNotNone(cluster)
        self.assertEqual(cluster.archetype, ClusterArchetype.DEPLOYER_SYBIL)

    def test_kl_divergence_behavioral_drift_detection(self):
        """
        Detects significant behavioral shift via D_KL divergence.
        If a wallet historically entered early (<25%) but recently enters late (>50%),
        it is flagged with D_KL drift and suppressed.
        """
        w = "WalletDriftingTrader1111111111111111111"
        now = time.time()

        # 1. Establish historical baseline: 12 early buys (< 25% curve)
        for i in range(12):
            t = TradeEvent(
                signature=f"hist_{i}",
                mint=f"mint_hist_{i}",
                trader_public_key=w,
                tx_type=TradeType.BUY,
                sol_amount=0.5,
                token_amount=5000.0,
                timestamp=now - 5000 + i,
                bonding_curve_pct=15.0,  # Early
            )
            self.tracker.record_trade(t)

        # Baseline check should show no drift
        is_drifting, d_kl, _ = self.tracker.check_identity_drift(w)
        self.assertFalse(is_drifting)

        # 2. Inject recent behavioral shift: 5 late entries (> 50% curve)
        for i in range(5):
            t = TradeEvent(
                signature=f"recent_{i}",
                mint=f"mint_recent_{i}",
                trader_public_key=w,
                tx_type=TradeType.BUY,
                sol_amount=0.5,
                token_amount=5000.0,
                timestamp=now + i,
                bonding_curve_pct=65.0,  # Late
            )
            self.tracker.record_trade(t)

        # D_KL check should trigger drift suppression
        is_drifting, d_kl, msg = self.tracker.check_identity_drift(w)
        self.assertTrue(is_drifting)
        self.assertGreaterEqual(d_kl, 1.25)
        self.assertIn(w, self.tracker.drift_suppressed_wallets)


if __name__ == "__main__":
    unittest.main()
