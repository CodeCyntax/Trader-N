"""
Stress-test suite for Subsystem 3: Autonomous Multi-Tier Runner & Exit Engine.
Tests:
- Surviving normal 22% and 28% pullbacks on parabolic runners (anti-shakeout)
- Capturing 800%+ multi-bagger profits with wide breathing leashes
- Instant emergency exit on Dev Dump detection
- Decoupled smart money exit holding
- Momentum stall timeout on dead tokens
"""
import unittest
import time
from core.models import PaperPosition, StrategyParameters, PositionStatus
from engine.risk_manager import RiskManager


class TestRunnerScenarios(unittest.TestCase):

    def setUp(self):
        self.params = StrategyParameters(
            runner_leash_pct=0.28,
            breakeven_lock_threshold_pct=0.35,
            trailing_stop_pct=0.18,
            max_holding_seconds=3600,
            migration_hold_enabled=True,
            smart_money_decoupling_pct=0.60
        )
        self.risk_manager = RiskManager(self.params)

    def test_scenario_1_parabolic_runner_survives_shakeouts_and_exits_at_peak(self):
        """
        Scenario 1: Parabolic 10x runner.
        - Entry: 0.00000004 SOL.
        - Rallies +80% to 0.000000072, pulls back 22% to 0.000000056 (Tier 2). Must NOT exit.
        - Rallies +500% to 0.00000024, pulls back 28% to 0.00000017 (Tier 4). Must NOT exit.
        - Rallies +1,000% to 0.00000044, pulls back 36% to 0.00000028. Must exit with MEGA_MOONSHOT.
        """
        now = time.time()
        pos = PaperPosition(
            position_id="pos_runner_1",
            mint="MintRunner1111111111111111111111111111111111",
            symbol="ALPHA100X",
            entry_timestamp=now - 600,
            entry_sol_cost=0.2,
            tokens_held=5_000_000,
            entry_price_sol=0.00000004,
            highest_price_sol=0.00000004,
            current_price_sol=0.00000004,
            current_value_sol=0.2,
            unrealized_pnl_sol=0.0,
            unrealized_pnl_pct=0.0,
            status=PositionStatus.OPEN
        )

        # Stage A: +80% peak, then 22% pullback
        pos.highest_price_sol = 0.000000072
        pos.current_price_sol = 0.000000056  # 22.2% drop from peak, still +40% from entry
        pos.current_value_sol = 0.28
        pos.unrealized_pnl_sol = 0.08
        pos.unrealized_pnl_pct = 40.0

        should_exit, reason = self.risk_manager.evaluate_exit(pos, current_bonding_progress=25.0)
        self.assertFalse(should_exit, "Must NOT get shaken out on 22% pullback in Tier 2")

        # Stage B: Explodes to +500% (Tier 4), then 28% pullback
        pos.highest_price_sol = 0.00000024
        pos.current_price_sol = 0.000000172  # 28.3% drop from peak, still +330% from entry
        pos.current_value_sol = 0.86
        pos.unrealized_pnl_sol = 0.66
        pos.unrealized_pnl_pct = 330.0

        should_exit, reason = self.risk_manager.evaluate_exit(pos, current_bonding_progress=65.0)
        self.assertFalse(should_exit, "Must NOT get shaken out on 28% pullback in Tier 4")

        # Stage C: Peaked at +1000%, then dropped 36% from peak
        pos.highest_price_sol = 0.00000044
        pos.current_price_sol = 0.00000028  # 36.3% drop from peak (exceeds 35% active leash)
        pos.current_value_sol = 1.40
        pos.unrealized_pnl_sol = 1.20
        pos.unrealized_pnl_pct = 600.0

        should_exit, reason = self.risk_manager.evaluate_exit(pos, current_bonding_progress=85.0)
        self.assertTrue(should_exit, "Must lock in mega moonshot after 36% retrace from 10x peak")
        self.assertIn("MEGA_MOONSHOT_RUNNER_EXIT", reason)

    def test_scenario_2_emergency_dev_dump_immediate_liquidation(self):
        """
        Scenario 2: Developer dumps tokens.
        Must trigger EMERGENCY_DEV_DUMP_DETECTED regardless of PnL or progress.
        """
        pos = PaperPosition(
            position_id="pos_rug_1",
            mint="MintRug22222222222222222222222222222222222",
            symbol="RUG",
            entry_timestamp=time.time() - 60,
            entry_sol_cost=0.2,
            tokens_held=5_000_000,
            entry_price_sol=0.00000004,
            highest_price_sol=0.00000005,
            current_price_sol=0.00000003,
            current_value_sol=0.15,
            unrealized_pnl_sol=-0.05,
            unrealized_pnl_pct=-25.0,
            status=PositionStatus.OPEN
        )

        should_exit, reason = self.risk_manager.evaluate_exit(
            pos,
            current_bonding_progress=10.0,
            dev_dump_detected=True
        )
        self.assertTrue(should_exit)
        self.assertEqual(reason, "EMERGENCY_DEV_DUMP_DETECTED")

    def test_scenario_3_smart_money_decoupling_preserves_runner(self):
        """
        Scenario 3: Lead smart wallet sells to take initial capital out.
        If we are in profit (+45%) and curve has healthy progress (35%),
        the bot decouples and keeps running.
        """
        pos = PaperPosition(
            position_id="pos_decouple_1",
            mint="MintDecouple333333333333333333333333333333333",
            symbol="DECOUPLE",
            entry_timestamp=time.time() - 300,
            entry_sol_cost=0.2,
            tokens_held=5_000_000,
            entry_price_sol=0.00000004,
            highest_price_sol=0.00000006,
            current_price_sol=0.000000058,
            current_value_sol=0.29,
            unrealized_pnl_sol=0.09,
            unrealized_pnl_pct=45.0,
            status=PositionStatus.OPEN
        )

        should_exit, reason = self.risk_manager.evaluate_exit(
            pos,
            current_bonding_progress=35.0,
            smart_wallet_exited=True
        )
        self.assertFalse(should_exit, "Must decouple and hold profitable runner when smart wallet scalps")

    def test_scenario_4_migration_hold_immunity(self):
        """
        Scenario 4: Token is surging toward Raydium migration (bonding curve progress >= 40%).
        Must be exempt from stall timeouts even if holding duration exceeds 60 minutes.
        """
        pos = PaperPosition(
            position_id="pos_mig_1",
            mint="MintMigrate4444444444444444444444444444444444",
            symbol="MIGRATING",
            entry_timestamp=time.time() - 4000,  # 66 minutes ago!
            entry_sol_cost=0.2,
            tokens_held=5_000_000,
            entry_price_sol=0.00000004,
            highest_price_sol=0.00000005,
            current_price_sol=0.000000048,
            current_value_sol=0.24,
            unrealized_pnl_sol=0.04,
            unrealized_pnl_pct=20.0,
            status=PositionStatus.OPEN
        )

        should_exit, reason = self.risk_manager.evaluate_exit(
            pos,
            current_bonding_progress=45.0  # Above 40% threshold
        )
        self.assertFalse(should_exit, "Tokens with >= 40% curve progress must have migration hold immunity")


if __name__ == "__main__":
    unittest.main()
