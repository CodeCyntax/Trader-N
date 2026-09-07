"""
Unit and scenario stress-test suite for Subsystem 1: Smart Wallet Intelligence.
Tests against:
- Micro-trade wash-trading dust
- Ultra-fast MEV / 3-second scalpers
- Pre-mined token dumps without prior buys
- Genuine Alpha Swing Hunters (multi-token, high PnL, healthy holding durations)
"""
import unittest
import time
from pathlib import Path
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from core.models import TradeEvent, TradeType


class TestWalletScenarios(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_wallet_scenarios.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.tracker = WalletTracker(self.db)

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_scenario_1_micro_trade_wash_trader_rejected(self):
        """
        Scenario 1: Wash trader tries to game win rate using 5 micro trades (0.005 SOL).
        Must be disqualified due to insufficient economic commitment (dust volume).
        """
        wash_wallet = "WashTrader11111111111111111111111111111111111"
        now = time.time()

        for i in range(4):
            mint = f"TokenMint_{i % 2}"
            self.tracker.process_trade(TradeEvent(
                signature=f"sig_buy_{i}",
                mint=mint,
                sol_amount=0.005,
                token_amount=100_000,
                is_buy=True,
                trader_public_key=wash_wallet,
                timestamp=now - 300 + (i * 60),
                tx_type=TradeType.BUY
            ))
            self.tracker.process_trade(TradeEvent(
                signature=f"sig_sell_{i}",
                mint=mint,
                sol_amount=0.006,
                token_amount=100_000,
                is_buy=False,
                trader_public_key=wash_wallet,
                timestamp=now - 250 + (i * 60),
                tx_type=TradeType.SELL
            ))

        is_smart, score = self.tracker.is_smart_wallet(wash_wallet)
        self.assertFalse(is_smart, "Micro-wash trader should be disqualified from smart money tracking")

    def test_scenario_2_ultra_fast_scalper_disqualified(self):
        """
        Scenario 2: Ultra-fast scalper executes 4 roundtrips in 3 seconds each.
        Copy-trading them is impossible due to network latency/slippage.
        Must be classified as SCALPER and disqualified.
        """
        scalper = "ScalperBot2222222222222222222222222222222222"
        now = time.time()

        for i in range(4):
            mint = f"TokenFast_{i}"
            self.tracker.process_trade(TradeEvent(
                signature=f"sig_s_buy_{i}",
                mint=mint,
                sol_amount=1.0,
                token_amount=1_000_000,
                is_buy=True,
                trader_public_key=scalper,
                timestamp=now - 500 + (i * 10),
                tx_type=TradeType.BUY
            ))
            self.tracker.process_trade(TradeEvent(
                signature=f"sig_s_sell_{i}",
                mint=mint,
                sol_amount=1.1,
                token_amount=1_000_000,
                is_buy=False,
                trader_public_key=scalper,
                timestamp=now - 497 + (i * 10),  # 3s holding!
                tx_type=TradeType.SELL
            ))

        is_smart, score = self.tracker.is_smart_wallet(scalper)
        profile = self.tracker.wallets[scalper]
        self.assertFalse(is_smart, "Ultra-fast scalpers must not be qualified as copy-targets")
        self.assertLess(profile.avg_holding_duration_seconds, 20.0)

    def test_scenario_3_premined_token_dump_no_unearned_profit(self):
        """
        Scenario 3: A dev or whale dumps 15 SOL worth of tokens without any prior buy.
        Must NOT be credited with fake profits or an inflated win rate!
        """
        dumper = "DumperDev33333333333333333333333333333333333"
        now = time.time()

        self.tracker.process_trade(TradeEvent(
            signature="sig_dump_1",
            mint="MintDump_1",
            sol_amount=15.0,
            token_amount=50_000_000,
            is_buy=False,
            trader_public_key=dumper,
            timestamp=now - 100,
            tx_type=TradeType.SELL
        ))

        profile = self.tracker.wallets[dumper]
        self.assertEqual(profile.profitable_trades, 0)
        self.assertFalse(self.tracker.is_smart_wallet(dumper)[0])

    def test_scenario_4_genuine_alpha_swing_hunter_qualified(self):
        """
        Scenario 4: Genuine alpha hunter trades across 3 distinct tokens,
        holds for 10-15 minutes, achieves 75% win rate and +5.0 SOL profit.
        Must be classified as ALPHA_SWING_HUNTER with high persistence score.
        """
        hunter = "AlphaHunter444444444444444444444444444444444"
        now = time.time()

        # Token 1: 10m hold, +2.5 SOL profit
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_b1",
            mint="Token_Alpha_1",
            sol_amount=1.5,
            token_amount=10_000_000,
            is_buy=True,
            trader_public_key=hunter,
            timestamp=now - 3600,
            tx_type=TradeType.BUY
        ))
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_s1",
            mint="Token_Alpha_1",
            sol_amount=4.0,
            token_amount=10_000_000,
            is_buy=False,
            trader_public_key=hunter,
            timestamp=now - 3000,
            tx_type=TradeType.SELL
        ))

        # Token 2: 12m hold, +3.0 SOL profit
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_b2",
            mint="Token_Alpha_2",
            sol_amount=2.0,
            token_amount=12_000_000,
            is_buy=True,
            trader_public_key=hunter,
            timestamp=now - 2400,
            tx_type=TradeType.BUY
        ))
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_s2",
            mint="Token_Alpha_2",
            sol_amount=5.0,
            token_amount=12_000_000,
            is_buy=False,
            trader_public_key=hunter,
            timestamp=now - 1680,
            tx_type=TradeType.SELL
        ))

        # Token 3: 8m hold, -0.5 SOL loss
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_b3",
            mint="Token_Alpha_3",
            sol_amount=1.0,
            token_amount=5_000_000,
            is_buy=True,
            trader_public_key=hunter,
            timestamp=now - 1200,
            tx_type=TradeType.BUY
        ))
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_s3",
            mint="Token_Alpha_3",
            sol_amount=0.5,
            token_amount=5_000_000,
            is_buy=False,
            trader_public_key=hunter,
            timestamp=now - 720,
            tx_type=TradeType.SELL
        ))

        # Token 4: 8m hold, +1.8 SOL profit
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_b4",
            mint="Token_Alpha_4",
            sol_amount=1.0,
            token_amount=8_000_000,
            is_buy=True,
            trader_public_key=hunter,
            timestamp=now - 600,
            tx_type=TradeType.BUY
        ))
        self.tracker.process_trade(TradeEvent(
            signature="sig_h_s4",
            mint="Token_Alpha_4",
            sol_amount=2.8,
            token_amount=8_000_000,
            is_buy=False,
            trader_public_key=hunter,
            timestamp=now - 120,
            tx_type=TradeType.SELL
        ))

        is_smart, score = self.tracker.is_smart_wallet(hunter)
        profile = self.tracker.wallets[hunter]

        self.assertTrue(is_smart, "Genuine alpha swing hunter must qualify as smart money")
        self.assertGreater(score, 0.65)
        self.assertEqual(profile.closed_trades, 4)
        self.assertEqual(profile.profitable_trades, 3)
        self.assertGreater(profile.realized_pnl_sol, 4.0)
        self.assertGreater(profile.avg_holding_duration_seconds, 60.0)


if __name__ == "__main__":
    unittest.main()
