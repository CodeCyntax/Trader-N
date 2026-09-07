"""
Unit tests for Token Lifecycle & Thesis Memory Manager.
Verifies state transitions, thesis invalidation, re-entry cooldowns,
and CTO (Community Takeover) revival regime verification.
"""
import unittest
import time
from pathlib import Path
from memory.database import DatabaseManager
from cognitive.token_lifecycle import TokenLifecycleManager
from core.models import TokenLifecycleState


class TestTokenLifecycleManager(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_lifecycle.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.manager = TokenLifecycleManager(self.db)
        self.mint = "MintTestLifecycle1111111111111111111111111"

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_initial_virgin_surge_allows_entry(self):
        """New token starts in VIRGIN_SURGE and allows entry."""
        allowed, reason = self.manager.can_enter(self.mint, {"symbol": "TEST"})
        self.assertTrue(allowed)
        self.assertIn("eligible", reason.lower())
        record = self.manager.get_lifecycle(self.mint)
        self.assertEqual(record["lifecycle_state"], TokenLifecycleState.VIRGIN_SURGE.value)

    def test_in_position_blocks_duplicate_entry(self):
        """Once position is opened, cannot re-enter while still in position."""
        self.manager.on_position_opened(self.mint, "TEST", "Initial test thesis")
        record = self.manager.get_lifecycle(self.mint)
        self.assertEqual(record["lifecycle_state"], TokenLifecycleState.IN_POSITION.value)

        allowed, reason = self.manager.can_enter(self.mint, {})
        self.assertFalse(allowed)
        self.assertIn("already active", reason.lower())

    def test_reentry_denial_on_identical_failure_regime(self):
        """After invalidation, identical regime entry is rejected within cooldown."""
        self.manager.on_position_opened(self.mint, "TEST", "Initial test thesis")
        self.manager.on_position_closed(
            mint=self.mint,
            symbol="TEST",
            exit_reason="STOP_LOSS_HIT",
            pnl_sol=-0.1,
            pnl_pct=-15.0,
        )
        record = self.manager.get_lifecycle(self.mint)
        self.assertEqual(record["lifecycle_state"], TokenLifecycleState.THESIS_INVALIDATED.value)

        # Attempt to re-enter immediately with normal market metrics
        allowed, reason = self.manager.can_enter(self.mint, {
            "vol_5m_sol": 0.5,
            "distinct_buyers_5m": 1,
            "net_flow_ratio": 0.1,
            "dev_dumped": False,
        })
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason.lower())

    def test_reentry_approval_under_genuine_cto(self):
        """When dev dumps and buyers take over, state transitions to CTO_REVIVAL and allows re-entry."""
        self.manager.on_position_opened(self.mint, "TEST", "Initial test thesis")
        self.manager.on_position_closed(
            mint=self.mint,
            symbol="TEST",
            exit_reason="DEV_DUMP_EXIT",
            pnl_sol=-0.2,
            pnl_pct=-20.0,
            is_dev_dump=True,
        )

        # Simulate genuine CTO takeover: dev is out (not dumping), token age > 20m, decentralized buyers
        cto_context = {
            "symbol": "TEST",
            "vol_5m_sol": 15.0,
            "distinct_buyers_5m": 10,
            "age_seconds": 1800.0,
            "dev_dumped": False,
        }
        allowed, reason = self.manager.can_enter(self.mint, cto_context)
        self.assertTrue(allowed)
        self.assertIn("cto revival", reason.lower())

        record = self.manager.get_lifecycle(self.mint)
        self.assertEqual(record["lifecycle_state"], TokenLifecycleState.CTO_REVIVAL.value)

    def test_terminal_rug_permanent_denial(self):
        """Terminal rug marks token as dead and blocks entry if dev dumped and no CTO."""
        self.manager.on_position_closed(
            mint=self.mint,
            symbol="TEST",
            exit_reason="DEV_DUMP_FATAL",
            pnl_sol=-0.5,
            pnl_pct=-95.0,
            is_dev_dump=True,
        )
        record = self.manager.get_lifecycle(self.mint)
        self.assertEqual(record["lifecycle_state"], TokenLifecycleState.TERMINAL_RUG.value)

        allowed, reason = self.manager.can_enter(self.mint, {"distinct_buyers_5m": 2, "dev_dumped": True})
        self.assertFalse(allowed)
        self.assertIn("terminal_rug", reason.lower())


if __name__ == "__main__":
    unittest.main()
