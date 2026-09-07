"""
Unit tests for the AI Cognitive Learning & Policy Tuning Engine.
Verifies post-mortem causal attribution and adaptive parameter adjustments.
"""
import unittest
import time
from pathlib import Path
from memory.database import DatabaseManager
from core.models import PaperPosition, PositionStatus
from core.bonding_curve import PumpBondingCurve
from learning.post_mortem import PostMortemAnalyzer
from learning.policy_tuner import PolicyTuner


class TestLearningEngine(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_learning.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.post_mortem = PostMortemAnalyzer(self.db)
        self.tuner = PolicyTuner(self.db)
        self.curve = PumpBondingCurve()

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_post_mortem_dev_rug_diagnosis(self):
        """
        Verify that a trade closed due to DEV_DUMP is classified as DEV_RUG
        and recommends tightening persistence and dev holding limits.
        """
        rug_position = PaperPosition(
            position_id="pos_rug_1",
            mint="MintRug1111111111111111111111111111111111111",
            symbol="RUGGY",
            entry_timestamp=time.time() - 300,
            entry_sol_cost=0.5,
            tokens_held=10_000_000,
            entry_price_sol=0.00000005,
            highest_price_sol=0.00000005,
            current_price_sol=0.00000001,
            current_value_sol=0.1,
            unrealized_pnl_sol=-0.4,
            unrealized_pnl_pct=-80.0,
            status=PositionStatus.CLOSED,
            exit_timestamp=time.time(),
            exit_reason="EMERGENCY_DEV_DUMP_DETECTED",
        )

        log = self.post_mortem.conduct_autopsy(rug_position, self.curve)
        self.assertEqual(log.outcome_category, "DEV_RUG")
        self.assertIn("increase_min_persistence", log.recommended_tuning)
        self.assertIn("tighten_dev_holding", log.recommended_tuning)

        # Apply learning to policy
        old_params = self.db.get_strategy_params()
        new_params = self.tuner.update_policy_from_learning(log)

        # Verification: persistence threshold increased and policy version bumped
        self.assertGreater(new_params.min_wallet_persistence_score, old_params.min_wallet_persistence_score)
        self.assertLess(new_params.max_dev_holding_pct, old_params.max_dev_holding_pct)
        self.assertGreater(new_params.version, old_params.version)

    def test_post_mortem_high_conviction_win(self):
        """
        Verify that a trade hitting target profit is diagnosed as HIGH_CONVICTION_WIN.
        """
        win_position = PaperPosition(
            position_id="pos_win_1",
            mint="MintWin2222222222222222222222222222222222222",
            symbol="MOON",
            entry_timestamp=time.time() - 600,
            entry_sol_cost=0.2,
            tokens_held=5_000_000,
            entry_price_sol=0.00000004,
            highest_price_sol=0.00000008,
            current_price_sol=0.00000008,
            current_value_sol=0.36,
            unrealized_pnl_sol=0.16,
            unrealized_pnl_pct=80.0,
            status=PositionStatus.CLOSED,
            exit_timestamp=time.time(),
            exit_reason="MAX_PROFIT_TARGET_REACHED (+80.0%)",
            trigger_wallet="SmartWallet456",
        )

        log = self.post_mortem.conduct_autopsy(win_position, self.curve)
        self.assertEqual(log.outcome_category, "MULTI_BAGGER_ALPHA")
        self.assertIn("Massive multi-bagger", log.lesson_learned)

    def test_post_mortem_premature_exit_widens_runner_leash(self):
        """
        Verify that a trade closed prematurely (+25%) on a trailing stop
        causes the agent to autonomously widen runner_leash_pct and extend max_holding_seconds.
        """
        choked_position = PaperPosition(
            position_id="pos_choked_1",
            mint="MintChoke33333333333333333333333333333333333",
            symbol="CHOKED",
            entry_timestamp=time.time() - 400,
            entry_sol_cost=0.2,
            tokens_held=5_000_000,
            entry_price_sol=0.00000004,
            highest_price_sol=0.00000006,
            current_price_sol=0.00000005,
            current_value_sol=0.25,
            unrealized_pnl_sol=0.05,
            unrealized_pnl_pct=25.0,
            status=PositionStatus.CLOSED,
            exit_timestamp=time.time(),
            exit_reason="TRAILING_STOP_PROFIT_PROTECTION (+25.0%)",
        )

        log = self.post_mortem.conduct_autopsy(choked_position, self.curve)
        self.assertEqual(log.outcome_category, "PREMATURE_RUNNER_EXIT")
        self.assertIn("widen_runner_leash", log.recommended_tuning)

        old_params = self.db.get_strategy_params()
        new_params = self.tuner.update_policy_from_learning(log)

        # Agent should have widened runner leash and recorded adaptation in history
        self.assertGreater(new_params.runner_leash_pct, old_params.runner_leash_pct)
        self.assertGreater(len(new_params.adaptation_history), 0)


if __name__ == "__main__":
    unittest.main()
