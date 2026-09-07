"""
Tests for DatabaseManager analytics, equity curve generator, and data exporters.
"""
import unittest
import time
import tempfile
from pathlib import Path
from memory.database import DatabaseManager
from core.models import PaperPosition, PositionStatus


class TestDatabaseAnalytics(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_analytics.db"
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_empty_equity_curve_and_metrics(self):
        curve = self.db.get_equity_curve_history()
        self.assertGreaterEqual(len(curve), 1)
        self.assertEqual(curve[0]["symbol"], "START")
        self.assertEqual(curve[0]["equity_sol"], 10.0)

        metrics = self.db.get_performance_metrics()
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["win_rate_pct"], 0.0)
        self.assertEqual(metrics["net_pnl_sol"], 0.0)

    def test_populated_equity_curve_and_metrics(self):
        now = time.time()
        # Add a winning closed trade
        pos1 = PaperPosition(
            position_id="pos_1",
            mint="Mint11111111111111111111111111111111111111",
            symbol="WINNER",
            entry_timestamp=now - 200,
            entry_sol_cost=0.5,
            tokens_held=100000,
            entry_price_sol=0.000005,
            highest_price_sol=0.000010,
            current_price_sol=0.000008,
            current_value_sol=0.8,
            unrealized_pnl_sol=0.3,
            unrealized_pnl_pct=60.0,
            status=PositionStatus.CLOSED,
            exit_timestamp=now - 100,
            exit_sol_received=0.8,
            exit_reason="TAKE_PROFIT",
            confidence_score=0.85,
        )
        self.db.save_position(pos1)

        # Add a losing closed trade
        pos2 = PaperPosition(
            position_id="pos_2",
            mint="Mint22222222222222222222222222222222222222",
            symbol="LOSER",
            entry_timestamp=now - 80,
            entry_sol_cost=0.5,
            tokens_held=100000,
            entry_price_sol=0.000005,
            highest_price_sol=0.000005,
            current_price_sol=0.000004,
            current_value_sol=0.4,
            unrealized_pnl_sol=-0.1,
            unrealized_pnl_pct=-20.0,
            status=PositionStatus.CLOSED,
            exit_timestamp=now - 10,
            exit_sol_received=0.4,
            exit_reason="STOP_LOSS",
            confidence_score=0.60,
        )
        self.db.save_position(pos2)

        # Check Equity Curve
        curve = self.db.get_equity_curve_history()
        self.assertEqual(len(curve), 3)  # START, pos1, pos2
        self.assertEqual(curve[0]["equity_sol"], 10.0)
        self.assertEqual(curve[1]["cum_pnl_sol"], 0.3)
        self.assertEqual(curve[1]["equity_sol"], 10.3)
        self.assertEqual(curve[2]["cum_pnl_sol"], 0.2)
        self.assertEqual(curve[2]["equity_sol"], 10.2)

        # Check Performance Metrics
        metrics = self.db.get_performance_metrics()
        self.assertEqual(metrics["total_trades"], 2)
        self.assertEqual(metrics["wins"], 1)
        self.assertEqual(metrics["losses"], 1)
        self.assertEqual(metrics["win_rate_pct"], 50.0)
        self.assertEqual(metrics["gross_profit_sol"], 0.3)
        self.assertEqual(metrics["gross_loss_sol"], 0.1)
        self.assertEqual(metrics["profit_factor"], 3.0)
        self.assertEqual(metrics["net_pnl_sol"], 0.2)
        self.assertEqual(metrics["max_win_pct"], 60.0)
        self.assertEqual(metrics["max_loss_pct"], -20.0)
        self.assertIn("TAKE_PROFIT", metrics["exit_reasons"])
        self.assertIn("STOP_LOSS", metrics["exit_reasons"])

        # Check Exporters
        trades = self.db.export_all_trades_rows()
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["symbol"], "LOSER")
        self.assertEqual(trades[1]["symbol"], "WINNER")

        learnings = self.db.export_all_learnings_records()
        self.assertIn("total_autopsies", learnings)
        self.assertIn("counterfactual_ledger", learnings)
        self.assertIn("discovered_hypotheses", learnings)


if __name__ == "__main__":
    unittest.main()
