"""
Stress-test suite for Barbell Moonbag Execution & Follower Feedback:
- Milestone 1: 50% partial sell at +100% (2x) returning initial SOL capital 100% risk-free.
- Milestone 2: 25% profit lock at +400% (5x) while keeping moonbag runner open.
- Fast Invalidation: immediate cut at -8% on stalled coins (no full -20% stop-out).
- Follower Feedback: toxic copycat wallets penalized and blacklisted after 2 consecutive losses.
"""
import unittest
import time
from pathlib import Path
from core.models import TradeEvent, TradeType, StrategyParameters, WalletProfile, PositionStatus
from core.bonding_curve import PumpBondingCurve
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from engine.paper_broker import PaperBroker
from engine.risk_manager import RiskManager


class TestMoonbagExecution(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_moonbag.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.broker = PaperBroker(self.db)
        self.params = StrategyParameters(runner_leash_pct=0.28, trailing_stop_pct=0.18)
        self.risk_manager = RiskManager(self.params)
        self.wallet_tracker = WalletTracker(self.db)
        self.curve = PumpBondingCurve()
        # Seed 10 SOL balance
        self.db.adjust_balance_for_trade(10.0 - self.db.get_balance())

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_milestone_1_half_derisk_at_2x_returns_initial_capital(self):
        """Tests that at +100% gain, 50% is sold, initial SOL is returned, and position becomes risk-free moonbag."""
        mint = "MoonbagCoin11111111111111111111111111111111"
        initial_cash = self.broker.get_balance()

        # 1. Buy position with 0.20 SOL
        pos = self.broker.execute_buy(
            mint=mint,
            symbol="MOON",
            sol_amount=0.20,
            curve=self.curve,
            trigger_wallet="AlphaLeader1111111111111111111111111111111",
        )
        self.assertIsNotNone(pos)
        self.assertEqual(pos.initial_tokens_held, pos.tokens_held)
        self.assertFalse(pos.is_moonbag)
        entry_cost = pos.entry_sol_cost

        # 2. Simulate price surging 2x (+100% on curve)
        # Pump curve with large buy
        self.curve.apply_buy(int(25 * 1_000_000_000))
        self.broker.update_position_price(mint, self.curve)

        self.assertGreaterEqual(pos.unrealized_pnl_pct, 100.0, "Position must have doubled")

        # 3. Risk manager evaluates exit with return_fraction=True
        should_exit, reason, fraction = self.risk_manager.evaluate_exit(
            position=pos,
            current_bonding_progress=self.curve.get_progress_pct(),
            return_fraction=True
        )
        self.assertTrue(should_exit)
        self.assertEqual(fraction, 0.50, "Must sell exactly 50% of tokens at 2x")
        self.assertIn("MOONBAG_50_PCT_DE_RISK", reason)

        # 4. Execute partial sell
        upd_pos, harvested_sol = self.broker.execute_partial_sell(
            mint=mint,
            fraction=fraction,
            exit_reason=reason,
            curve=self.curve
        )
        self.assertIsNotNone(upd_pos)
        self.assertTrue(upd_pos.is_moonbag, "Position must be flagged as a risk-free moonbag")
        self.assertIn("HALF_INITIAL_SOL", upd_pos.moonbag_milestones_hit)
        self.assertGreaterEqual(harvested_sol, entry_cost * 0.95, "Harvested SOL must return ~100% of initial SOL cost")
        self.assertEqual(upd_pos.status, PositionStatus.OPEN, "Remaining 50% moonbag must remain open!")
        self.assertGreater(upd_pos.tokens_held, 0)

    def test_milestone_2_lock_profit_at_5x(self):
        """Tests that at +400% (5x), 25% of initial tokens is sold to lock in profit."""
        mint = "MoonbagCoin22222222222222222222222222222222"
        pos = self.broker.execute_buy(mint=mint, symbol="GEM", sol_amount=0.15, curve=self.curve)
        pos.is_moonbag = True
        pos.moonbag_milestones_hit.append("HALF_INITIAL_SOL")
        pos.unrealized_pnl_pct = 420.0  # > 400%

        should_exit, reason, fraction = self.risk_manager.evaluate_exit(
            position=pos,
            current_bonding_progress=50.0,
            return_fraction=True
        )
        self.assertTrue(should_exit)
        self.assertEqual(fraction, 0.50)
        self.assertIn("MOONBAG_25_PCT_PROFIT_LOCKED", reason)

    def test_fast_invalidation_stalled_momentum_defense(self):
        """Tests that stalled trades down -8% after 90s are cut immediately rather than taking a -20% stop-out."""
        mint = "DeadSlowCoin3333333333333333333333333333333"
        pos = self.broker.execute_buy(mint=mint, symbol="SLOW", sol_amount=0.10, curve=self.curve)
        pos.entry_timestamp = time.time() - 120.0  # Open for 2 minutes
        pos.highest_price_sol = pos.entry_price_sol * 1.01  # Never pumped
        pos.unrealized_pnl_pct = -8.5  # Down -8.5%

        should_exit, reason, fraction = self.risk_manager.evaluate_exit(
            position=pos,
            current_bonding_progress=10.0,
            return_fraction=True
        )
        self.assertTrue(should_exit)
        self.assertEqual(fraction, 1.0)
        self.assertIn("FAST_INVALIDATION_MOMENTUM_STALLED", reason)

    def test_follower_feedback_blacklists_toxic_wallet(self):
        """Tests that a leader wallet causing 2 consecutive losses for our bot is blacklisted."""
        toxic_wallet = "ToxicLeader4444444444444444444444444444444"
        # Seed wallet profile with high on-chain stats
        prof = WalletProfile(
            address=toxic_wallet,
            first_seen=time.time() - 86400,
            last_seen=time.time(),
            total_trades=20,
            closed_trades=15,
            profitable_trades=12,
            total_volume_sol=25.0,
            realized_pnl_sol=5.0,
            persistence_score=0.85,
            tokens_traded={"T1", "T2", "T3"},
            total_holding_duration_seconds=3000.0
        )
        self.wallet_tracker.wallets[toxic_wallet] = prof
        self.db.upsert_wallet(prof)

        is_smart, score = self.wallet_tracker.is_smart_wallet(toxic_wallet)
        self.assertTrue(is_smart, "Initially qualified as smart money")

        # Record trade 1: loss of -0.03 SOL
        self.wallet_tracker.record_copy_trade_outcome(toxic_wallet, pnl_sol=-0.03)
        prof = self.wallet_tracker.wallets[toxic_wallet]
        self.assertEqual(prof.consecutive_copy_losses, 1)
        self.assertFalse(prof.is_blacklisted_for_copying)

        # Record trade 2: loss of -0.04 SOL (2 consecutive losses!)
        self.wallet_tracker.record_copy_trade_outcome(toxic_wallet, pnl_sol=-0.04)
        prof = self.wallet_tracker.wallets[toxic_wallet]
        self.assertEqual(prof.consecutive_copy_losses, 2)
        self.assertTrue(prof.is_blacklisted_for_copying, "Must be blacklisted after 2 consecutive copy losses")

        # Now verify is_smart_wallet immediately rejects this toxic wallet
        is_smart, score = self.wallet_tracker.is_smart_wallet(toxic_wallet)
        self.assertFalse(is_smart, "Blacklisted toxic wallet must NEVER trigger entries")
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
