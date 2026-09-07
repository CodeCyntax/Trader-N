"""
Terminal Dashboard & Analytics Reporter.
Renders clean, informative summaries of portfolio health, persistent smart wallets,
trade performance, and AI learning trajectories.
"""
import time
from typing import List, Dict, Any
from tabulate import tabulate
from memory.database import DatabaseManager
from engine.paper_broker import PaperBroker


class DashboardReporter:
    """
    Renders status and analytical reports for the user.
    """

    def __init__(self, db: DatabaseManager, broker: PaperBroker):
        self.db = db
        self.broker = broker

    def render_summary(self) -> str:
        """Generates a complete overview dashboard string."""
        sections = []
        sections.append("=" * 78)
        sections.append("               TRADER-N: AUTONOMOUS SOLANA / PUMP.FUN AGENT")
        sections.append("=" * 78)

        # 1. Portfolio Overview
        portfolio = self.broker.get_portfolio_summary()
        params = self.db.get_strategy_params()
        closed_trades = self.db.get_closed_positions(limit=100)
        
        realized_pnl = sum(r["unrealized_pnl_sol"] for r in closed_trades) if closed_trades else 0.0
        wins = sum(1 for r in closed_trades if r["unrealized_pnl_sol"] > 0)
        win_rate = (wins / len(closed_trades) * 100.0) if closed_trades else 0.0

        portfolio_table = [
            ["Cash Balance (SOL)", f"{portfolio['cash_sol']:.4f} SOL"],
            ["Open Positions Value", f"{portfolio['positions_value_sol']:.4f} SOL"],
            ["Total Portfolio Equity", f"{portfolio['total_portfolio_sol']:.4f} SOL"],
            ["Total Realized PnL", f"{realized_pnl:+.4f} SOL"],
            ["Win Rate (Closed Trades)", f"{win_rate:.1f}% ({wins}/{len(closed_trades)})"],
            ["Active Open Positions", f"{portfolio['open_positions_count']}"],
            ["Strategy Policy Version", f"v{params.version} (Min Wallet Score: {params.min_wallet_persistence_score})"],
            ["Adaptive Sizing Range", f"{params.base_trade_sol:.2f} SOL - {params.max_trade_sol:.2f} SOL"],
        ]
        sections.append("\n[PORTFOLIO & PERFORMANCE SUMMARY]")
        sections.append(tabulate(portfolio_table, tablefmt="simple"))

        # 2. Open Positions
        open_positions = list(self.broker.open_positions.values())
        sections.append("\n[ACTIVE OPEN POSITIONS]")
        if open_positions:
            pos_headers = ["Symbol", "Mint", "Cost (SOL)", "Val (SOL)", "Unrealized PnL", "Peak Price", "Trigger Wallet"]
            pos_rows = []
            for p in open_positions:
                pos_rows.append([
                    p.symbol[:8],
                    p.mint[:6] + "..." + p.mint[-4:],
                    f"{p.entry_sol_cost:.3f}",
                    f"{p.current_value_sol:.3f}",
                    f"{p.unrealized_pnl_pct:+.1f}% ({p.unrealized_pnl_sol:+.3f})",
                    f"{p.highest_price_sol:.6f}",
                    p.trigger_wallet[:6] + "..." if p.trigger_wallet else "DIRECT"
                ])
            sections.append(tabulate(pos_rows, headers=pos_headers, tablefmt="grid"))
        else:
            sections.append("  (No active positions. Scanning live stream for smart money signals...)")

        # 3. Top Persistent Smart Wallets
        top_wallets = self.db.get_top_persistent_wallets(limit=8)
        sections.append("\n[TOP PERSISTENT SMART WALLETS (Non-Burners)]")
        if top_wallets:
            w_headers = ["Wallet Address", "Score", "Trades", "Tokens", "Win Rate", "Realized PnL", "Active (Hrs)"]
            w_rows = []
            for w in top_wallets:
                wr = (w["profitable_trades"] / w["total_trades"] * 100) if w["total_trades"] > 0 else 0
                w_rows.append([
                    w["address"][:6] + "..." + w["address"][-4:],
                    f"{w['persistence_score']:.3f}",
                    w["total_trades"],
                    w["tokens_traded_count"],
                    f"{wr:.1f}%",
                    f"{w['realized_pnl_sol']:+.3f} SOL",
                    f"{w['active_hours']:.1f}h"
                ])
            sections.append(tabulate(w_rows, headers=w_headers, tablefmt="grid"))
        else:
            sections.append("  (Profiling on-chain wallets from live stream... Filtering out one-off burners...)")

        # 4. Recent Episodic Learnings (Trade Autopsies)
        recent_logs = self.db.get_recent_learnings(limit=4)
        sections.append("\n[RECENT EPISODIC LEARNINGS & AUTOPSIES]")
        if recent_logs:
            for l in recent_logs:
                pnl_str = f"{l['net_pnl_sol']:+.4f} SOL ({l['net_pnl_pct']:+.1f}%)"
                sections.append(
                    f" • [{l['outcome_category']}] Mint: {l['mint'][:6]}... | Net PnL: {pnl_str}\n"
                    f"   Lesson: {l['lesson_learned']}\n"
                    f"   Exit Trigger: {l['exit_reason']}"
                )
        else:
            sections.append("  (No closed trades yet. Lessons will be recorded automatically upon trade exits.)")

        sections.append("\n" + "=" * 78)
        return "\n".join(sections)
