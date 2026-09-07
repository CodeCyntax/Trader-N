"""
Unit tests verifying Soft Reset and Hard Reset mechanics:
- Soft Reset: sets balance, preserves positions, wallets, learnings, and ML weights.
- Hard Reset: wipes all database tables, in-memory positions, ML weights, and resets policy version to 1.
"""
import unittest
import time
from pathlib import Path
from core.models import WalletProfile, PaperPosition, PositionStatus, StrategyParameters
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from engine.paper_broker import PaperBroker
from engine.risk_manager import RiskManager
from engine.token_monitor import TokenMonitor
from learning.ml_brain import LocalOnlineMLEngine
from learning.policy_tuner import PolicyTuner


class DummyAgent:
    """Mock agent wiring all subsystems for reset testing."""
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.wallet_tracker = WalletTracker(self.db)
        self.params = self.db.get_strategy_params()
        self.broker = PaperBroker(self.db)
        self.risk_manager = RiskManager(self.params)
        self.token_monitor = TokenMonitor()
        self.ml_engine = LocalOnlineMLEngine(db_manager=self.db)
        self.policy_tuner = PolicyTuner(self.db)
        self.active_tokens = {}

    def soft_reset(self, balance: float = 10.0) -> float:
        return self.db.reset_portfolio_balance(balance)

    def hard_reset(self, default_balance: float = 10.0) -> float:
        new_bal = self.db.hard_reset_all_data(default_balance=default_balance)
        self.broker.reset()
        self.active_tokens.clear()
        self.wallet_tracker.reset()
        self.token_monitor.reset()
        self.ml_engine.reset_model()
        self.params = self.db.get_strategy_params()
        self.risk_manager.params = self.params
        self.policy_tuner.reset()
        return new_bal


class TestAgentResets(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_reset.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.agent = DummyAgent(self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_soft_reset_preserves_learnings_and_positions(self):
        """Soft reset must change portfolio balance but keep all history, positions, and ML intact."""
        # 1. Seed wallet
        w = WalletProfile(address="Leader111111111111111111111111111111111", persistence_score=0.88, realized_pnl_sol=5.0)
        self.db.upsert_wallet(w)

        # 2. Seed open position
        pos = PaperPosition(
            position_id="pos_soft_1",
            mint="MintSoft1111111111111111111111111111111111",
            symbol="SOFT",
            entry_timestamp=time.time(),
            entry_sol_cost=0.20,
            tokens_held=1_000_000,
            entry_price_sol=0.00000002,
            highest_price_sol=0.00000002,
            current_price_sol=0.00000002,
            current_value_sol=0.20,
            status=PositionStatus.OPEN
        )
        self.db.save_position(pos)
        self.agent.broker.open_positions[pos.mint] = pos

        # 3. Train ML step to alter weights
        feat = [0.5] * 10
        self.agent.ml_engine.update_online(feat, return_pct=25.0)
        updates_before = self.agent.ml_engine.total_updates
        self.assertGreater(updates_before, 0)

        # 4. Execute Soft Reset
        new_bal = self.agent.soft_reset(balance=50.0)
        self.assertEqual(new_bal, 50.0)
        self.assertEqual(self.db.get_balance(), 50.0)

        # 5. Verify data preserved
        self.assertIsNotNone(self.db.get_wallet("Leader111111111111111111111111111111111"))
        self.assertEqual(len(self.db.get_open_positions()), 1)
        self.assertEqual(self.agent.ml_engine.total_updates, updates_before)

    def test_hard_reset_wipes_all_data_clean_slate(self):
        """Hard reset must completely wipe all tables, in-memory state, and ML weights back to v1."""
        # 1. Seed wallet, positions, and modify ML
        w = WalletProfile(address="Leader222222222222222222222222222222222", persistence_score=0.92, realized_pnl_sol=12.0)
        self.db.upsert_wallet(w)

        pos = PaperPosition(
            position_id="pos_hard_1",
            mint="MintHard2222222222222222222222222222222222",
            symbol="HARD",
            entry_timestamp=time.time(),
            entry_sol_cost=0.50,
            tokens_held=2_000_000,
            entry_price_sol=0.00000003,
            highest_price_sol=0.00000003,
            current_price_sol=0.00000003,
            current_value_sol=0.50,
            status=PositionStatus.OPEN
        )
        self.db.save_position(pos)
        self.agent.broker.open_positions[pos.mint] = pos

        # Mutate ML model weights
        feat = [0.8] * 10
        self.agent.ml_engine.update_online(feat, return_pct=100.0)
        self.assertGreater(self.agent.ml_engine.total_updates, 0)

        # Advance policy version
        params = self.agent.params
        params.version = 15
        self.db.save_strategy_params(params)

        # 2. Execute Hard Reset
        new_bal = self.agent.hard_reset(default_balance=10.0)
        self.assertEqual(new_bal, 10.0)
        self.assertEqual(self.db.get_balance(), 10.0)

        # 3. Verify all DB tables are wiped
        with self.db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM paper_positions;").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM wallets;").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM wallet_tokens;").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM episodic_learnings;").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM online_model_state;").fetchone()[0], 0)
            # Strategy version reset to 1
            strat_ver = conn.execute("SELECT version FROM strategy_state WHERE id = 1;").fetchone()[0]
            self.assertEqual(strat_ver, 1)

        # 4. Verify in-memory state wiped
        self.assertEqual(len(self.agent.broker.open_positions), 0)
        self.assertEqual(len(self.agent.wallet_tracker.wallets), 0)
        self.assertEqual(self.agent.ml_engine.total_updates, 0)
        self.assertEqual(self.agent.params.version, 1)


if __name__ == "__main__":
    unittest.main()
