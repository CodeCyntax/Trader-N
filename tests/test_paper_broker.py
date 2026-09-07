"""
Unit tests for Paper Broker and realistic execution.
"""
import unittest
from pathlib import Path
from memory.database import DatabaseManager
from engine.paper_broker import PaperBroker
from core.bonding_curve import PumpBondingCurve


class TestPaperBroker(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_broker.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.broker = PaperBroker(self.db)
        self.curve = PumpBondingCurve()

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_initial_balance(self):
        """Verify default starting balance of 10 SOL."""
        self.assertEqual(self.broker.get_balance(), 10.0)

    def test_deposit_and_withdraw(self):
        """Verify capital deposit and withdrawal operations."""
        new_bal = self.db.deposit(5.0)
        self.assertEqual(new_bal, 15.0)

        withdrawn_bal = self.db.withdraw(3.0)
        self.assertEqual(withdrawn_bal, 12.0)

        # Attempt to withdraw more than available
        with self.assertRaises(ValueError):
            self.db.withdraw(20.0)

    def test_realistic_buy_execution(self):
        """Verify buy order deducts cost + network fees and holds exact tokens."""
        mint = "MintTestPaper11111111111111111111111111111111"
        pos = self.broker.execute_buy(
            mint=mint,
            symbol="TEST",
            sol_amount=0.5,
            curve=self.curve,
            trigger_wallet="Wallet123",
            confidence=0.7,
        )

        self.assertIsNotNone(pos)
        self.assertEqual(pos.symbol, "TEST")
        self.assertGreater(pos.tokens_held, 0)
        # Balance should be deducted by 0.5 + network fee (approx 0.500505 SOL)
        self.assertLess(self.broker.get_balance(), 9.5)
        self.assertIn(mint, self.broker.open_positions)

    def test_realistic_sell_execution(self):
        """Verify sell order calculates exact PnL and credits portfolio balance."""
        mint = "MintTestPaper22222222222222222222222222222222"
        self.broker.execute_buy(
            mint=mint,
            symbol="TEST2",
            sol_amount=0.5,
            curve=self.curve,
        )

        # Execute sell
        closed_res = self.broker.execute_sell(mint, exit_reason="TAKE_PROFIT", curve=self.curve)
        self.assertIsNotNone(closed_res)
        closed_pos, pnl = closed_res

        self.assertEqual(closed_pos.status.value, "closed")
        self.assertNotIn(mint, self.broker.open_positions)
        # Because we bought and sold immediately on the same curve, PnL reflects 1% buy fee + 1% sell fee + AMM curve impact + gas
        self.assertLess(pnl, 0.0)
        self.assertGreater(pnl, -0.05)


if __name__ == "__main__":
    unittest.main()
