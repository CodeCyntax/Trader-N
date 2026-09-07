"""
Unit tests for Smart Wallet Tracker and Persistence Scoring.
Verifies rejection of throwaway burner wallets and qualification of persistent traders.
"""
import unittest
import time
from pathlib import Path
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from core.models import TradeEvent, TradeType


class TestWalletTracker(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_trader.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.tracker = WalletTracker(self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_burner_wallet_rejection(self):
        """
        Verify that a wallet that only trades 1 token (throwaway sniper/dev)
        is flagged as a burner and receives near-zero persistence score.
        """
        burner_addr = "BurnerWallet1111111111111111111111111111111"
        mint = "MintSingleToken1111111111111111111111111111111"

        now = time.time()
        # Simulate 4 trades all on the same token within 5 minutes
        for i in range(4):
            event = TradeEvent(
                mint=mint,
                tx_type=TradeType.BUY if i % 2 == 0 else TradeType.SELL,
                sol_amount=1.5,
                token_amount=10_000_000.0,
                trader_public_key=burner_addr,
                timestamp=now + (i * 30),
            )
            self.tracker.process_trade(event)

        is_smart, score = self.tracker.is_smart_wallet(burner_addr)
        self.assertFalse(is_smart)
        profile = self.tracker.wallets[burner_addr]
        self.assertTrue(profile.is_burner)
        self.assertLessEqual(score, 0.1)

    def test_persistent_smart_wallet_qualification(self):
        """
        Verify that a wallet with multi-day activity, multiple distinct tokens,
        and high realized profit qualifies as a persistent smart wallet.
        """
        smart_addr = "SmartTraderWallet22222222222222222222222222222"
        now = time.time()
        start_time = now - (72 * 3600)  # Active for 3 days (72 hours)

        # Simulate 8 profitable trades across 4 distinct tokens
        tokens = [f"TokenMint{k}22222222222222222222222222222" for k in range(4)]
        
        for idx, token_mint in enumerate(tokens):
            t_entry = start_time + (idx * 18 * 3600)
            # Buy
            self.tracker.process_trade(TradeEvent(
                mint=token_mint,
                tx_type=TradeType.BUY,
                sol_amount=0.5,
                token_amount=1_000_000.0,
                trader_public_key=smart_addr,
                timestamp=t_entry,
            ))
            # Sell for profit (0.8 SOL received vs 0.5 SOL spent)
            self.tracker.process_trade(TradeEvent(
                mint=token_mint,
                tx_type=TradeType.SELL,
                sol_amount=0.8,
                token_amount=1_000_000.0,
                trader_public_key=smart_addr,
                timestamp=t_entry + 600,
            ))

        profile = self.tracker.wallets[smart_addr]
        self.assertEqual(len(profile.tokens_traded), 4)
        self.assertEqual(profile.profitable_trades, 4)
        self.assertGreater(profile.realized_pnl_sol, 1.0)
        self.assertGreaterEqual(profile.persistence_score, 0.40)

        is_smart, score = self.tracker.is_smart_wallet(smart_addr)
        self.assertTrue(is_smart)


if __name__ == "__main__":
    unittest.main()
