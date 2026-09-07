"""
Strategy Evaluator: Synthesizes smart wallet activity, bonding curve progress,
and dev risk heuristics to generate actionable trade signals.
Upgraded to delegate to TokenLifecycleManager, MetaDecisionBrain, and CounterfactualEngine.
"""
from typing import Optional, Tuple, Dict, Any
from core.models import TradeEvent, TradeType, StrategyParameters, MetaDecision
from core.bonding_curve import PumpBondingCurve
from memory.wallet_tracker import WalletTracker
from engine.paper_broker import PaperBroker
from engine.risk_manager import RiskManager
from engine.token_monitor import TokenMonitor
from learning.ml_brain import LocalOnlineMLEngine
from cognitive.token_lifecycle import TokenLifecycleManager
from cognitive.meta_decision import MetaDecisionBrain
from cognitive.counterfactual import CounterfactualEngine


class StrategyEvaluator:
    """
    Evaluates incoming market events to identify high-probability entries.
    Combines rule-based safety filters with multi-brain cognitive synthesis
    and shadow counterfactual tracking.
    """

    def __init__(
        self,
        wallet_tracker: WalletTracker,
        paper_broker: PaperBroker,
        risk_manager: RiskManager,
        params: StrategyParameters,
        token_monitor: Optional[TokenMonitor] = None,
        ml_engine: Optional[LocalOnlineMLEngine] = None,
        lifecycle_manager: Optional[TokenLifecycleManager] = None,
        meta_brain: Optional[MetaDecisionBrain] = None,
        counterfactual_engine: Optional[CounterfactualEngine] = None,
    ):
        self.wallet_tracker = wallet_tracker
        self.broker = paper_broker
        self.risk_manager = risk_manager
        self.params = params
        self.token_monitor = token_monitor
        self.ml_engine = ml_engine
        self.lifecycle_manager = lifecycle_manager
        self.meta_brain = meta_brain
        self.counterfactual_engine = counterfactual_engine
        self.last_decision: Optional[MetaDecision] = None

    def evaluate_entry_signal(
        self,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        symbol: str = "TOKEN",
    ) -> Tuple[bool, float, float, Optional[str]]:
        """
        Evaluates if an incoming buy trade from an on-chain participant
        should trigger an autonomous copy-entry for the agent.

        Returns:
            (should_buy, confidence_score, calculated_size_sol, trigger_wallet)
        """
        # We only evaluate entries triggered by buys
        if trade.tx_type != TradeType.BUY:
            return False, 0.0, 0.0, None

        # Do not re-enter if we already have an open position in this mint
        if trade.mint in self.broker.open_positions:
            return False, 0.0, 0.0, None

        # Check bonding curve boundaries
        progress_pct = curve.get_progress_pct()
        if progress_pct < self.params.min_curve_pct or progress_pct > self.params.max_curve_pct:
            return False, 0.0, 0.0, None

        # Check token activity, dev rug history, and revival volume surge
        if self.token_monitor:
            eligible, reason = self.token_monitor.is_token_eligible_for_entry(
                mint=trade.mint,
                params=self.params,
                current_time=trade.timestamp,
            )
            if not eligible:
                return False, 0.0, 0.0, None

        # Check if buyer is a verified persistent smart wallet
        buyer_addr = trade.trader_public_key
        is_smart, persistence_score = self.wallet_tracker.is_smart_wallet(buyer_addr)

        if not is_smart or persistence_score < self.params.min_wallet_persistence_score:
            return False, 0.0, 0.0, None

        # Extract context metrics
        act = self.token_monitor.activities.get(trade.mint) if self.token_monitor else None
        vol_5m = act.total_volume_5m_sol if act else 0.0
        buyers_5m = act.distinct_buyers_5m if act else 1
        buy_vol = act.buy_volume_5m_sol if act else trade.sol_amount
        sell_vol = act.sell_volume_5m_sol if act else 0.0
        dev_hold = 0.0
        age_sec = act.age_seconds if act else 0.0
        now = trade.timestamp or 0.0
        vol_1m = sum(b[1] for b in act.recent_buys if (now - b[0]) <= 60.0) if act else trade.sol_amount
        dev_dumped = act.dev_dumped if act else False
        wallet_prof = self.wallet_tracker.wallets.get(buyer_addr)
        is_burner = wallet_prof.is_burner if wallet_prof else False

        context: Dict[str, Any] = {
            "symbol": symbol,
            "persistence_score": persistence_score,
            "vol_5m_sol": vol_5m,
            "buy_vol_5m_sol": buy_vol,
            "sell_vol_5m_sol": sell_vol,
            "vol_1m_sol": vol_1m,
            "distinct_buyers_5m": buyers_5m,
            "age_seconds": age_sec,
            "dev_holding_pct": dev_hold,
            "dev_dumped": dev_dumped,
            "is_burner": is_burner,
            "net_flow_ratio": (buy_vol - sell_vol) / (buy_vol + sell_vol + 0.001),
        }

        # 1. Per-Token Lifecycle & Thesis Memory Gate
        if self.lifecycle_manager:
            can_enter, reason = self.lifecycle_manager.can_enter(trade.mint, context)
            if not can_enter:
                return False, 0.0, 0.0, None

        # 2. Multi-Brain Meta-Decision Committee (if active)
        if self.meta_brain:
            decision = self.meta_brain.evaluate(trade.mint, trade, curve, context, symbol=symbol)
            self.last_decision = decision
            if self.counterfactual_engine:
                self.counterfactual_engine.register_evaluation(
                    decision=decision,
                    spot_price_sol=curve.get_spot_price_sol(),
                    curve_pct=progress_pct,
                )
            if decision.decision != "EXECUTE":
                return False, 0.0, 0.0, None

            confidence = round(min(0.95, max(0.45, 0.50 + decision.expected_edge * 2.0)), 3)
        else:
            # Baseline heuristic & online ML evaluation
            curve_sweetness = 1.0 - abs(progress_pct - 35.0) / 45.0
            curve_factor = max(0.2, min(1.0, curve_sweetness))
            heuristic_conf = (persistence_score * 0.65) + (curve_factor * 0.35)
            heuristic_conf = round(min(1.0, max(0.4, heuristic_conf)), 3)

            if self.ml_engine:
                follower_pnl = wallet_prof.bot_copied_pnl_sol if wallet_prof else 0.0
                bot_wins = wallet_prof.bot_copied_wins if wallet_prof else 0.0
                bot_losses = (wallet_prof.bot_copied_trades - bot_wins) if wallet_prof else 0.0

                features = self.ml_engine.extract_features(
                    persistence_score=persistence_score,
                    follower_pnl_sol=follower_pnl,
                    bayesian_wins=bot_wins,
                    bayesian_losses=bot_losses,
                    curve_pct=progress_pct,
                    volume_5m_sol=vol_5m,
                    distinct_buyers_5m=buyers_5m,
                    buy_vol_5m_sol=buy_vol,
                    sell_vol_5m_sol=sell_vol,
                    dev_holding_pct=dev_hold,
                    token_age_seconds=age_sec,
                    vol_1m_sol=vol_1m,
                )

                ml_win_prob = self.ml_engine.predict_win_probability(features)
                alpha_blend = min(1.0, self.ml_engine.total_updates / 30.0)
                confidence = ((1.0 - alpha_blend) * heuristic_conf) + (alpha_blend * ml_win_prob)
                confidence = round(min(1.0, max(0.1, confidence)), 3)

                if confidence < 0.45:
                    return False, 0.0, 0.0, None
            else:
                confidence = heuristic_conf

        # Compute autonomous position size
        portfolio_balance = self.broker.get_balance()
        open_count = len(self.broker.open_positions)
        suggested_size = self.risk_manager.calculate_position_size(
            portfolio_balance=portfolio_balance,
            confidence_score=confidence,
            open_positions_count=open_count,
        )

        if suggested_size <= 0.0:
            return False, 0.0, 0.0, None

        return True, confidence, suggested_size, buyer_addr
