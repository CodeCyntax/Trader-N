"""
Trader-N: Autonomous Solana & Pump.fun AI Trading Agent.
Orchestrates live data ingestion, smart wallet profiling, realistic paper execution,
and continuous episodic learning.
"""
import asyncio
import argparse
import logging
import os
import signal
import sys
import time
from typing import Dict

from core.models import TokenMetadata, TradeEvent, TradeType
from core.bonding_curve import PumpBondingCurve
from core.constants import INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RESERVES
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from engine.paper_broker import PaperBroker
from engine.risk_manager import RiskManager
from engine.token_monitor import TokenMonitor
from learning.ml_brain import LocalOnlineMLEngine
from learning.post_mortem import PostMortemAnalyzer
from learning.policy_tuner import PolicyTuner
from learning.dashboard_reporter import DashboardReporter
from engine.strategy_evaluator import StrategyEvaluator
from data.solana_stream import SolanaTradeStream
from data.pumpportal_stream import PumpPortalTokenStream
from web.server import WebDashboardServer
from cognitive.cluster_tracker import ClusterTracker
from cognitive.token_lifecycle import TokenLifecycleManager
from cognitive.meta_decision import MetaDecisionBrain
from cognitive.counterfactual import CounterfactualEngine
from cognitive.research_agent import AutonomousResearchAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("TraderN")


class TraderAgent:
    """
    Unified coordinator connecting data streams, memory, broker, web dashboard, and learning loops.
    """

    def __init__(self, web_port: int = 8080, enable_web: bool = True, dashboard_interval: float = 2.0):
        self.web_port = web_port
        self.enable_web = enable_web
        self.is_running = False
        self.is_paused = False
        self.dashboard_interval = float(dashboard_interval)

        # 1. Database & Persistence
        self.db = DatabaseManager()

        # 2. Smart Wallet Tracking & Probabilistic Cluster Engine
        self.wallet_tracker = WalletTracker(self.db)
        self.cluster_tracker = ClusterTracker(self.db)

        # 3. Cognitive State & Thesis Lifecycle Manager
        self.token_lifecycle = TokenLifecycleManager(self.db)
        self.meta_brain = MetaDecisionBrain(self.cluster_tracker)
        self.counterfactual_engine = CounterfactualEngine(self.db)
        self.research_agent = AutonomousResearchAgent(self.db)

        # 4. Execution, Risk & Token Momentum Engine
        self.params = self.db.get_strategy_params()
        self.broker = PaperBroker(self.db)
        self.risk_manager = RiskManager(self.params)
        self.token_monitor = TokenMonitor()
        self.ml_engine = LocalOnlineMLEngine(db_manager=self.db)
        self.strategy_evaluator = StrategyEvaluator(
            wallet_tracker=self.wallet_tracker,
            paper_broker=self.broker,
            risk_manager=self.risk_manager,
            params=self.params,
            token_monitor=self.token_monitor,
            ml_engine=self.ml_engine,
            lifecycle_manager=self.token_lifecycle,
            meta_brain=self.meta_brain,
            counterfactual_engine=self.counterfactual_engine,
        )

        # 5. Learning & Cognitive Engine
        self.post_mortem = PostMortemAnalyzer(self.db)
        self.policy_tuner = PolicyTuner(self.db)
        self.reporter = DashboardReporter(self.db, self.broker)

        # 5. Token Metadata & Curves Cache: mint -> {"meta": TokenMetadata, "curve": PumpBondingCurve}
        self.active_tokens: Dict[str, dict] = {}

        # 6. Web Dashboard Server
        self.web_server = WebDashboardServer(self, port=self.web_port) if self.enable_web else None

        # 7. Stream Clients
        self.solana_stream = SolanaTradeStream(self.on_trade_event)
        self.pump_stream = PumpPortalTokenStream(self.on_new_token_event)

    def on_new_token_event(self, meta: TokenMetadata, raw: dict):
        """Called when a new token is deployed on pump.fun."""
        # Screen dev wallet to detect insider clusters
        self.wallet_tracker.register_dev(meta.dev_wallet)

        # Register in token activity monitor
        self.token_monitor.get_or_create_activity(
            mint=meta.mint,
            created_at=meta.created_at,
            dev_wallet=meta.dev_wallet
        )

        # Initialize exact bonding curve
        v_sol = int(raw.get("vSolInBondingCurve", 30.0) * 1e9)
        v_tok = int(raw.get("vTokensInBondingCurve", 1073000000.0) * 1e6)
        curve = PumpBondingCurve.from_curve_reserves(v_sol, v_tok)

        self.active_tokens[meta.mint] = {
            "meta": meta,
            "curve": curve,
        }
        self.broker.set_curve(meta.mint, curve)

    def on_trade_event(self, trade: TradeEvent):
        """Called on every live on-chain pump.fun buy and sell."""
        mint = trade.mint

        # 1. Retrieve or initialize bonding curve
        token_entry = self.active_tokens.get(mint)
        dev_wallet = token_entry["meta"].dev_wallet if token_entry and token_entry.get("meta") else None

        # Record activity and volume velocity
        self.token_monitor.record_trade(trade, dev_wallet=dev_wallet)

        if token_entry:
            curve = token_entry["curve"]
            if trade.virtual_sol_reserves and trade.virtual_token_reserves:
                curve.update_reserves(trade.virtual_sol_reserves, trade.virtual_token_reserves)
        else:
            v_sol = trade.virtual_sol_reserves or INITIAL_VIRTUAL_SOL_LAMPORTS
            v_tok = trade.virtual_token_reserves or INITIAL_VIRTUAL_TOKEN_RESERVES
            curve = PumpBondingCurve.from_curve_reserves(v_sol, v_tok)
            self.active_tokens[mint] = {"meta": None, "curve": curve}

        self.broker.set_curve(mint, curve)

        # Broadcast live trade to browser dashboard
        if self.web_server:
            asyncio.create_task(self.web_server.broadcast_trade(trade.model_dump()))

        # 2. Update smart wallet profile and check persistence
        wallet_profile = self.wallet_tracker.process_trade(trade)

        # 3. Update probabilistic cluster graph & counterfactual shadow prices
        self.cluster_tracker.record_trade(trade, dev_wallet=dev_wallet)
        self.counterfactual_engine.update_price(
            mint=mint,
            current_price_sol=curve.get_spot_price_sol(),
            current_time=trade.timestamp,
        )

        # 4. Position Lifecycle Management
        # Case A: We currently hold an open position in this token
        if mint in self.broker.open_positions:
            position = self.broker.update_position_price(mint, curve)
            if position:
                # Check for exit catalysts
                smart_wallet_exited = (
                    trade.tx_type == TradeType.SELL
                    and position.trigger_wallet
                    and trade.trader_public_key == position.trigger_wallet
                )

                dev_wallet = token_entry["meta"].dev_wallet if token_entry and token_entry.get("meta") else None
                dev_dump = (
                    trade.tx_type == TradeType.SELL
                    and dev_wallet
                    and trade.trader_public_key == dev_wallet
                    and trade.token_amount > 10_000_000
                )

                should_exit, exit_reason, sell_fraction = self.risk_manager.evaluate_exit(
                    position=position,
                    current_bonding_progress=curve.get_progress_pct(),
                    smart_wallet_exited=smart_wallet_exited,
                    dev_dump_detected=dev_dump,
                    return_fraction=True,
                )

                if should_exit and exit_reason:
                    if sell_fraction < 1.0:
                        # Partial sell for Barbell Moonbag Strategy!
                        partial_res = self.broker.execute_partial_sell(
                            mint=mint,
                            fraction=sell_fraction,
                            exit_reason=exit_reason,
                            curve=curve,
                        )
                        if partial_res:
                            upd_pos, sol_harvested = partial_res
                            logger.info(
                                f"💰 [MOONBAG HARVEST] {upd_pos.symbol} ({mint[:6]}...) | "
                                f"Harvested: +{sol_harvested:.4f} SOL | "
                                f"Tokens Left: {upd_pos.tokens_held:,} | "
                                f"Reason: {exit_reason}"
                            )
                    else:
                        closed_res = self.broker.execute_sell(mint, exit_reason=exit_reason, curve=curve)
                        if closed_res:
                            closed_pos, pnl = closed_res
                            logger.info(
                                f"🔔 [POSITION CLOSED] {closed_pos.symbol} ({mint[:6]}...) | "
                                f"PnL: {pnl:+.4f} SOL ({closed_pos.unrealized_pnl_pct:+.1f}%) | "
                                f"Reason: {exit_reason}"
                            )

                            # 1. Update Follower Experience for Trigger Wallet
                            if closed_pos.trigger_wallet:
                                self.wallet_tracker.record_copy_trade_outcome(
                                    address=closed_pos.trigger_wallet,
                                    pnl_sol=pnl,
                                )

                            # 2. Update Online Machine Learning Model Weights
                            if self.ml_engine and hasattr(closed_pos, "entry_price_sol"):
                                act = self.token_monitor.activities.get(mint)
                                trig_prof = self.wallet_tracker.wallets.get(closed_pos.trigger_wallet) if closed_pos.trigger_wallet else None
                                f_pnl = trig_prof.bot_copied_pnl_sol if trig_prof else 0.0
                                b_wins = trig_prof.bot_copied_wins if trig_prof else 0.0
                                b_losses = (trig_prof.bot_copied_trades - b_wins) if trig_prof else 0.0
                                p_score = trig_prof.persistence_score if trig_prof else 0.5
                                vol_5m = act.total_volume_5m_sol if act else 0.0
                                b_count = act.distinct_buyers_5m if act else 1
                                b_vol = act.buy_volume_5m_sol if act else 0.0
                                s_vol = act.sell_volume_5m_sol if act else 0.0
                                age_s = act.age_seconds if act else 0.0
                                now_ts = time.time()
                                vol_1m = sum(b[1] for b in act.recent_buys if (now_ts - b[0]) <= 60.0) if act else 0.0

                                feat = self.ml_engine.extract_features(
                                    persistence_score=p_score,
                                    follower_pnl_sol=f_pnl,
                                    bayesian_wins=b_wins,
                                    bayesian_losses=b_losses,
                                    curve_pct=curve.get_progress_pct(),
                                    volume_5m_sol=vol_5m,
                                    distinct_buyers_5m=b_count,
                                    buy_vol_5m_sol=b_vol,
                                    sell_vol_5m_sol=s_vol,
                                    dev_holding_pct=0.0,
                                    token_age_seconds=age_s,
                                    vol_1m_sol=vol_1m,
                                )
                                ml_log = self.ml_engine.update_online(
                                    x=feat,
                                    return_pct=closed_pos.unrealized_pnl_pct,
                                    is_dev_dump=(exit_reason == "EMERGENCY_DEV_DUMP_DETECTED"),
                                )
                                logger.info(
                                    f"🧠 [ONLINE ML ADAPTED] Brier: {ml_log['brier_score']:.4f} | "
                                    f"Samples: {ml_log['total_updates']}"
                                )

                            # 3. Record token lifecycle invalidation / closure
                            self.token_lifecycle.on_position_closed(
                                mint=mint,
                                symbol=closed_pos.symbol,
                                exit_reason=exit_reason,
                                pnl_sol=pnl,
                                pnl_pct=closed_pos.unrealized_pnl_pct,
                                is_dev_dump=dev_dump,
                            )

                            # 4. Conduct autonomous post-trade learning & heuristic policy tuning
                            log = self.post_mortem.conduct_autopsy(closed_pos, curve)
                            new_params = self.policy_tuner.update_policy_from_learning(log)
                            self.params = new_params
                            self.strategy_evaluator.params = new_params
                            self.risk_manager.params = new_params

        # Case B: We do not hold this token -> Evaluate entry signal (if not paused)
        elif not self.is_paused:
            symbol = token_entry["meta"].symbol if token_entry and token_entry.get("meta") else "COIN"
            should_buy, confidence, size_sol, trigger_wallet = self.strategy_evaluator.evaluate_entry_signal(
                trade=trade,
                curve=curve,
                symbol=symbol,
            )

            if should_buy and size_sol > 0:
                pos = self.broker.execute_buy(
                    mint=mint,
                    symbol=symbol,
                    sol_amount=size_sol,
                    curve=curve,
                    trigger_wallet=trigger_wallet,
                    confidence=confidence,
                )
                if pos:
                    thesis = self.strategy_evaluator.last_decision.thesis if self.strategy_evaluator.last_decision else f"Triggered by persistent wallet {trigger_wallet[:6]}..."
                    self.token_lifecycle.on_position_opened(mint=mint, symbol=symbol, thesis=thesis)
                    logger.info(
                        f"🚀 [POSITION OPENED] {symbol} ({mint[:6]}...) | "
                        f"Size: {size_sol:.3f} SOL | Confidence: {confidence:.2f} | "
                        f"Thesis: {thesis}"
                    )

    def soft_reset(self, balance: float = 10.0) -> float:
        """
        Soft reset: Resets paper portfolio balance only, preserving all learned models,
        wallet profiles, and trade history intact.
        """
        new_bal = self.db.reset_portfolio_balance(balance)
        logger.info(f"SOFT RESET: Balance set to {new_bal:.4f} SOL. All learnings and history preserved.")
        return new_bal

    def hard_reset(self, default_balance: float = 10.0) -> float:
        """
        Hard reset (Factory Reset):
        Wipes all positions, wallets, learnings, and ML weights from SQLite and memory.
        Acts completely new from tick 0.
        """
        # 1. Wipe DB tables
        new_bal = self.db.hard_reset_all_data(default_balance=default_balance)

        # 2. Reset broker open positions and curves
        self.broker.reset()
        self.active_tokens.clear()

        # 3. Reset wallet tracker in-memory caches
        self.wallet_tracker.reset()

        # 4. Reset token monitor activity history
        self.token_monitor.reset()

        # 5. Reset online ML model weights, bias, gradients, and calibration
        self.ml_engine.reset_model()

        # 6. Reset strategy hyperparameters to default and reload
        self.params = self.db.get_strategy_params()
        self.risk_manager.params = self.params
        self.strategy_evaluator.params = self.params
        self.policy_tuner.reset()

        # 7. Reset cognitive architecture subsystems
        self.cluster_tracker.reset()
        self.token_lifecycle.reset()
        self.counterfactual_engine.reset()

        logger.info(f"HARD RESET: Full system wipe completed. Clean slate initialized with {new_bal:.4f} SOL.")
        return new_bal

    async def run_dashboard_loop(self):
        """Periodically refreshes the live terminal dashboard and runs offline research."""
        iteration = 0
        while self.is_running:
            await asyncio.sleep(self.dashboard_interval)
            iteration += 1

            # Resolve counterfactual tracking every 10 iterations (~20s)
            if iteration % 10 == 0:
                self.counterfactual_engine.resolve_counterfactuals(horizon_seconds=3600.0)

            # Run offline autonomous research mining every 100 iterations (~200s)
            if iteration % 100 == 0:
                self.research_agent.run_discovery_cycle()

            print("\n" + self.reporter.render_summary() + "\n")

    async def start(self):
        """Launches streaming threads, background tasks, and web server."""
        self.is_running = True
        logger.info("Starting Trader-N Agent...")
        logger.info(f"Available Paper Balance: {self.broker.get_balance():.4f} SOL")

        if self.web_server:
            await self.web_server.start()

        await self.pump_stream.start()
        await self.solana_stream.start()

        # Initial terminal dashboard output
        print("\n" + self.reporter.render_summary() + "\n")

        # Run background terminal dashboard
        try:
            await self.run_dashboard_loop()
        except asyncio.CancelledError:
            pass

    async def stop(self):
        """Clean shutdown."""
        self.is_running = False
        logger.info("Shutting down Trader-N Agent...")
        if self.web_server:
            await self.web_server.stop()
        await self.pump_stream.stop()
        await self.solana_stream.stop()


def main():
    parser = argparse.ArgumentParser(description="Trader-N: Autonomous Solana & Pump.fun Trading Agent")
    parser.add_argument("--mode", choices=["paper", "analyze"], default="paper", help="Execution mode")
    parser.add_argument("--balance", type=float, help="Set initial paper trading balance in SOL")
    parser.add_argument("--deposit", type=float, help="Deposit SOL into paper balance")
    parser.add_argument("--withdraw", type=float, help="Withdraw SOL from paper balance")
    default_port = int(os.getenv("PORT", 8080))
    parser.add_argument("--interval", type=int, default=15, help="Terminal dashboard refresh interval (seconds)")
    parser.add_argument("--port", type=int, default=default_port, help=f"Web dashboard server port (default: {default_port})")
    parser.add_argument("--no-web", action="store_true", help="Disable the browser web UI dashboard")
    args = parser.parse_args()

    db = DatabaseManager()

    # Balance adjustments
    if args.balance is not None:
        if args.balance <= 0:
            print("Error: Balance must be positive.")
            sys.exit(1)
        with db.get_connection() as conn:
            conn.execute("UPDATE portfolio SET sol_balance = ?, updated_at = ? WHERE id = 1;", (args.balance, time.time()))
            conn.commit()
        print(f"Paper balance set to {args.balance:.4f} SOL.")
        if args.mode != "paper":
            return

    if args.deposit:
        new_bal = db.deposit(args.deposit)
        print(f"Deposited {args.deposit:.4f} SOL. Current balance: {new_bal:.4f} SOL.")
        return

    if args.withdraw:
        try:
            new_bal = db.withdraw(args.withdraw)
            print(f"Withdrew {args.withdraw:.4f} SOL. Current balance: {new_bal:.4f} SOL.")
        except Exception as e:
            print(f"Withdraw failed: {e}")
        return

    # Analysis mode
    if args.mode == "analyze":
        broker = PaperBroker(db)
        reporter = DashboardReporter(db, broker)
        print(reporter.render_summary())
        return

    # Paper trading mode with Web Dashboard
    agent = TraderAgent(
        dashboard_interval=args.interval,
        enable_web=(not args.no_web),
        web_port=args.port,
    )

    async def run_agent():
        try:
            await agent.start()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await agent.stop()

    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\nShutdown requested by user. Exiting cleanly...")


if __name__ == "__main__":
    main()
