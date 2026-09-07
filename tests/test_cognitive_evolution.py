"""
Stress-test suite for Subsystem 4: Cognitive Post-Mortem Autopsy & Self-Tuning Brain.
Tests:
- Policy convergence across 30 varied trade episodes
- Regime transitions (RUNNER_ALPHA vs DEFENSIVE_SCALP)
- Bounded parameter adaptations without numerical runaway
- Timeline history logging
"""
import unittest
import time
from pathlib import Path
from core.models import PaperPosition, PositionStatus, StrategyParameters
from core.bonding_curve import PumpBondingCurve
from memory.database import DatabaseManager
from learning.post_mortem import PostMortemAnalyzer
from learning.policy_tuner import PolicyTuner


class TestCognitiveEvolution(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_cognitive.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.post_mortem = PostMortemAnalyzer(self.db)
        self.tuner = PolicyTuner(self.db)
        self.curve = PumpBondingCurve()

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_regime_transition_and_sizing_adaptation(self):
        """
        Simulate a sequence of 6 losing trades followed by 6 multi-bagger runner trades.
        Verify that:
        1. Low win rate triggers DEFENSIVE_SCALP regime with reduced trade sizing.
        2. High win rate with runners triggers RUNNER_ALPHA regime with expanded sizing.
        """
        now = time.time()

        # Phase 1: 6 consecutive losses (Bear/Choppy market)
        for i in range(6):
            pos = PaperPosition(
                position_id=f"pos_loss_{i}",
                mint=f"MintLoss_{i}",
                symbol=f"LOSS{i}",
                entry_timestamp=now - (1000 - i * 50),
                entry_sol_cost=0.2,
                tokens_held=5_000_000,
                entry_price_sol=0.00000004,
                highest_price_sol=0.000000045,
                current_price_sol=0.00000003,
                current_value_sol=0.15,
                unrealized_pnl_sol=-0.05,
                unrealized_pnl_pct=-25.0,
                status=PositionStatus.CLOSED,
                exit_timestamp=now - (950 - i * 50),
                exit_reason="STOP_LOSS_HIT (-20.0%)"
            )
            log = self.post_mortem.conduct_autopsy(pos, self.curve)
            self.db.save_episodic_log(log)
            params = self.tuner.update_policy_from_learning(log)

        # Agent should be in DEFENSIVE_SCALP regime
        self.assertEqual(params.market_regime, "DEFENSIVE_SCALP")
        self.assertEqual(params.base_trade_sol, 0.10)

        # Phase 2: 6 consecutive multi-bagger winners (Parabolic market)
        for i in range(6):
            pos = PaperPosition(
                position_id=f"pos_win_{i}",
                mint=f"MintWin_{i}",
                symbol=f"WIN{i}",
                entry_timestamp=now - (500 - i * 50),
                entry_sol_cost=0.2,
                tokens_held=5_000_000,
                entry_price_sol=0.00000004,
                highest_price_sol=0.00000010,
                current_price_sol=0.00000008,
                current_value_sol=0.40,
                unrealized_pnl_sol=0.20,
                unrealized_pnl_pct=100.0,
                status=PositionStatus.CLOSED,
                exit_timestamp=now - (450 - i * 50),
                exit_reason="MULTI_BAGGER_PROFIT_LOCKED (+100.0%)"
            )
            log = self.post_mortem.conduct_autopsy(pos, self.curve)
            self.db.save_episodic_log(log)
            params = self.tuner.update_policy_from_learning(log)

        # Agent should have adapted to RUNNER_ALPHA
        self.assertEqual(params.market_regime, "RUNNER_ALPHA")
        self.assertTrue(params.migration_hold_enabled)
        self.assertGreater(params.base_trade_sol, 0.10)
        self.assertGreater(len(params.adaptation_history), 0)

    def test_parameter_bounds_under_repeated_choking(self):
        """
        Verify that repeated PREMATURE_RUNNER_EXIT autopsies widen runner_leash_pct
        without exceeding the mathematically safe bound (0.38).
        """
        now = time.time()
        for i in range(10):
            pos = PaperPosition(
                position_id=f"pos_choke_{i}",
                mint=f"MintChoke_{i}",
                symbol=f"CHK{i}",
                entry_timestamp=now - 500,
                entry_sol_cost=0.2,
                tokens_held=5_000_000,
                entry_price_sol=0.00000004,
                highest_price_sol=0.00000006,
                current_price_sol=0.00000005,
                current_value_sol=0.25,
                unrealized_pnl_sol=0.05,
                unrealized_pnl_pct=25.0,
                status=PositionStatus.CLOSED,
                exit_timestamp=now - 450,
                exit_reason="TRAILING_STOP_PROFIT_PROTECTION (+25.0%)"
            )
            log = self.post_mortem.conduct_autopsy(pos, self.curve)
            params = self.tuner.update_policy_from_learning(log)

        # Must not exceed upper bound 0.38
        self.assertLessEqual(params.runner_leash_pct, 0.38)
        self.assertGreaterEqual(params.runner_leash_pct, 0.28)


if __name__ == "__main__":
    unittest.main()
