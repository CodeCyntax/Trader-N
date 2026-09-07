"""
Stress-test suite for Token Activity & Revival (CTO) Verification.
Verifies that:
- Dead tokens with little or no activity are REJECTED even if bought by smart money.
- Old tokens (>30m) without a confirmed volume surge are REJECTED.
- Old tokens (>30m) WITH a confirmed revival surge (CTO: >=3 buyers, >=1.5 SOL volume) are ACCEPTED.
- Rugged tokens where dev dumped are REJECTED.
"""
import unittest
import time
from pathlib import Path
from core.models import TradeEvent, TradeType, StrategyParameters, WalletProfile
from core.bonding_curve import PumpBondingCurve
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from engine.paper_broker import PaperBroker
from engine.risk_manager import RiskManager
from engine.token_monitor import TokenMonitor
from engine.strategy_evaluator import StrategyEvaluator


class TestTokenActivity(unittest.TestCase):

    def setUp(self):
        self.test_db_path = Path("data_store/test_activity.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.db = DatabaseManager(self.test_db_path)
        self.wallet_tracker = WalletTracker(self.db)
        self.broker = PaperBroker(self.db)
        self.params = StrategyParameters(
            min_wallet_persistence_score=0.40,
            min_volume_5m_sol=0.40,
            min_distinct_buyers_5m=2,
            revival_age_threshold_seconds=1800.0,  # 30 minutes
            revival_min_volume_5m_sol=1.50,
            revival_min_distinct_buyers=3,
            reject_dev_dumped_tokens=True
        )
        self.risk_manager = RiskManager(self.params)
        self.token_monitor = TokenMonitor()
        self.evaluator = StrategyEvaluator(
            wallet_tracker=self.wallet_tracker,
            paper_broker=self.broker,
            risk_manager=self.risk_manager,
            params=self.params,
            token_monitor=self.token_monitor
        )
        self.curve = PumpBondingCurve()
        self.curve.apply_buy(int(15 * 1_000_000_000))  # ~17% curve progress (within valid 5%-75% window)

        # Seed a persistent smart wallet
        self.smart_wallet = "SmartAlphaWallet111111111111111111111111111"
        self.wallet_profile = WalletProfile(
            address=self.smart_wallet,
            first_seen=time.time() - 7200,
            last_seen=time.time(),
            total_trades=10,
            closed_trades=8,
            profitable_trades=7,
            total_volume_sol=12.0,
            realized_pnl_sol=4.5,
            persistence_score=0.85,
            tokens_traded={"MintA", "MintB", "MintC"},
            total_holding_duration_seconds=1200.0
        )
        self.wallet_tracker.wallets[self.smart_wallet] = self.wallet_profile

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_case_1_dead_token_little_or_no_activity_rejected(self):
        """
        Case 1: Token has 0 volume or 1 solitary trade of 0.05 SOL in 5 minutes.
        Even if a smart wallet buys, the agent must REJECT due to insufficient activity.
        """
        dead_mint = "DeadToken11111111111111111111111111111111111"
        now = time.time()

        # Solitary trade of 0.05 SOL
        trade = TradeEvent(
            signature="sig_dead_1",
            mint=dead_mint,
            sol_amount=0.05,
            token_amount=100_000,
            is_buy=True,
            trader_public_key=self.smart_wallet,
            timestamp=now,
            tx_type=TradeType.BUY
        )
        self.token_monitor.record_trade(trade)

        should_buy, conf, size, trigger = self.evaluator.evaluate_entry_signal(
            trade=trade,
            curve=self.curve,
            symbol="DEAD"
        )
        self.assertFalse(should_buy, "Must reject dead token with little to no activity")

    def test_case_2_old_token_without_revival_surge_rejected(self):
        """
        Case 2: Old token (created 60 minutes ago).
        It only has 0.3 SOL in buy volume and 1 buyer.
        Must REJECT because revival volume surge criteria is not met.
        """
        old_mint = "OldToken222222222222222222222222222222222222"
        now = time.time()

        # Register as old token created 3600 seconds ago
        self.token_monitor.get_or_create_activity(
            mint=old_mint,
            created_at=now - 3600
        )

        # 1 small buy of 0.3 SOL
        trade = TradeEvent(
            signature="sig_old_1",
            mint=old_mint,
            sol_amount=0.30,
            token_amount=500_000,
            is_buy=True,
            trader_public_key=self.smart_wallet,
            timestamp=now,
            tx_type=TradeType.BUY
        )
        self.token_monitor.record_trade(trade)

        should_buy, conf, size, trigger = self.evaluator.evaluate_entry_signal(
            trade=trade,
            curve=self.curve,
            symbol="OLD"
        )
        self.assertFalse(should_buy, "Must reject old token without confirmed revival volume")

    def test_case_3_old_token_with_booming_cto_surge_accepted(self):
        """
        Case 3: Old token (created 2 hours ago), BUT experiencing a genuine booming CTO!
        Has 3 distinct buyers, 2.5 SOL in buy volume, and positive net flow in last 5m.
        Must ACCEPT because revival criteria is confirmed!
        """
        cto_mint = "BoomingCTO3333333333333333333333333333333333"
        now = time.time()

        self.token_monitor.get_or_create_activity(
            mint=cto_mint,
            created_at=now - 7200  # 2 hours old
        )

        # Buyer 1 buys 0.8 SOL
        self.token_monitor.record_trade(TradeEvent(
            signature="sig_cto_1",
            mint=cto_mint,
            sol_amount=0.8,
            token_amount=1_500_000,
            is_buy=True,
            trader_public_key="CTOBuyer1111111111111111111111111111111111",
            timestamp=now - 120,
            tx_type=TradeType.BUY
        ))
        # Buyer 2 buys 0.7 SOL
        self.token_monitor.record_trade(TradeEvent(
            signature="sig_cto_2",
            mint=cto_mint,
            sol_amount=0.7,
            token_amount=1_200_000,
            is_buy=True,
            trader_public_key="CTOBuyer2222222222222222222222222222222222",
            timestamp=now - 60,
            tx_type=TradeType.BUY
        ))
        # Smart wallet triggers buy of 1.0 SOL
        smart_trade = TradeEvent(
            signature="sig_cto_3",
            mint=cto_mint,
            sol_amount=1.0,
            token_amount=1_800_000,
            is_buy=True,
            trader_public_key=self.smart_wallet,
            timestamp=now,
            tx_type=TradeType.BUY
        )
        self.token_monitor.record_trade(smart_trade)

        should_buy, conf, size, trigger = self.evaluator.evaluate_entry_signal(
            trade=smart_trade,
            curve=self.curve,
            symbol="CTO_ALPHA"
        )
        self.assertTrue(should_buy, "Must accept genuinely booming revival/CTO token with volume surge")
        self.assertEqual(trigger, self.smart_wallet)

    def test_case_4_dev_rugged_token_strictly_rejected(self):
        """
        Case 4: Creator dumped tokens (dev dump).
        Must REJECT even if a smart wallet attempts to buy afterwards.
        """
        rug_mint = "DevRugged44444444444444444444444444444444444"
        dev_wallet = "DevScammer5555555555555555555555555555555555"
        now = time.time()

        self.token_monitor.get_or_create_activity(
            mint=rug_mint,
            created_at=now - 600,
            dev_wallet=dev_wallet
        )

        # Dev dumps 20M tokens
        self.token_monitor.record_trade(TradeEvent(
            signature="sig_dev_dump",
            mint=rug_mint,
            sol_amount=2.5,
            token_amount=20_000_000,
            is_buy=False,
            trader_public_key=dev_wallet,
            timestamp=now - 100,
            tx_type=TradeType.SELL
        ), dev_wallet=dev_wallet)

        # Smart wallet buys
        trade = TradeEvent(
            signature="sig_buy_post_rug",
            mint=rug_mint,
            sol_amount=1.0,
            token_amount=10_000_000,
            is_buy=True,
            trader_public_key=self.smart_wallet,
            timestamp=now,
            tx_type=TradeType.BUY
        )
        self.token_monitor.record_trade(trade, dev_wallet=dev_wallet)

        should_buy, conf, size, trigger = self.evaluator.evaluate_entry_signal(
            trade=trade,
            curve=self.curve,
            symbol="RUGGED"
        )
        self.assertFalse(should_buy, "Must strictly reject token where dev dumped")


if __name__ == "__main__":
    unittest.main()
