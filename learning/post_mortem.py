"""
Post-Mortem Trade Autopsy Engine.
Conducts deep retrospective analysis on closed trades to diagnose win/loss factors
and extract persistent episodic lessons.
"""
import uuid
from typing import Dict, Any
from core.models import PaperPosition, EpisodicLog, StrategyParameters
from core.bonding_curve import PumpBondingCurve
from memory.database import DatabaseManager


class PostMortemAnalyzer:
    """
    Analyzes trade results to formulate causal attribution and actionable adjustments.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def conduct_autopsy(
        self,
        position: PaperPosition,
        curve_at_exit: PumpBondingCurve,
        curve_pct_at_entry: float = 25.0,
    ) -> EpisodicLog:
        """
        Diagnoses why a trade succeeded or failed and generates an EpisodicLog.
        """
        net_pnl = position.unrealized_pnl_sol
        net_pct = position.unrealized_pnl_pct
        exit_reason = position.exit_reason or "UNKNOWN"
        curve_pct_at_exit = curve_at_exit.get_progress_pct()

        tuning: Dict[str, Any] = {}

        if net_pnl > 0.0:
            if net_pct >= 50.0:
                category = "MULTI_BAGGER_ALPHA"
                lesson = (
                    f"Massive multi-bagger captured (+{net_pct:.1f}%). "
                    f"Runner holding engine and wide breathing leash successfully allowed parabolic price discovery."
                )
                tuning["reinforce_runner_regime"] = True
                tuning["boost_smart_wallet"] = position.trigger_wallet
                tuning["widen_runner_leash"] = 0.01
            elif "TRAILING_STOP" in exit_reason or "SMART_WALLET" in exit_reason:
                # Check if it was choked too early on a moderate gain (+10% to +45%)
                if 10.0 <= net_pct < 45.0:
                    category = "PREMATURE_RUNNER_EXIT"
                    lesson = (
                        f"Closed at +{net_pct:.1f}%, but exit was triggered prematurely on a pullback. "
                        f"Token needed wider runner breathing room and higher smart money decoupling to reach 10x-100x."
                    )
                    tuning["widen_runner_leash"] = 0.02
                    tuning["extend_holding_seconds"] = 600
                    tuning["increase_decoupling"] = 0.05
                else:
                    category = "TRAILING_STOP_PROFIT"
                    lesson = (
                        f"Captured +{net_pct:.1f}% profit. Trailing stop successfully locked in gains "
                        f"before post-peak retracement."
                    )
            elif "MAX_PROFIT" in exit_reason or "TAKE_PROFIT" in exit_reason:
                category = "HIGH_CONVICTION_WIN"
                lesson = (
                    f"Strong entry on {position.symbol}. Momentum carried to +{net_pct:.1f}%. "
                    f"Trigger wallet {position.trigger_wallet[:8] if position.trigger_wallet else 'SYSTEM'} "
                    f"provided reliable smart-money lead."
                )
                tuning["confidence_boost"] = 0.05
            else:
                category = "SCALP_PROFIT"
                lesson = f"Captured +{net_pct:.1f}% profit on {position.symbol}."
        else:
            # Check for round trip: token was up significantly at peak, but closed red
            peak_gain = ((position.highest_price_sol - position.entry_price_sol) / position.entry_price_sol * 100.0) if position.entry_price_sol > 0 else 0.0
            if peak_gain >= 35.0:
                category = "GREEDY_ROUND_TRIP"
                lesson = (
                    f"Position peaked at +{peak_gain:.1f}%, but round-tripped into a loss ({net_pct:.1f}%). "
                    f"Breakeven profit lock threshold must be tightened to protect profits after significant runs."
                )
                tuning["lower_breakeven_threshold"] = 0.04
                tuning["tighten_stop_pct"] = 0.01
            elif "DEV_DUMP" in exit_reason:
                category = "DEV_RUG"
                lesson = (
                    f"Dev or insider dumped liquidity on {position.symbol}. Net loss: {net_pnl:.4f} SOL. "
                    f"Requires stricter screening against dev-linked wallets and earlier dump signals."
                )
                tuning["increase_min_persistence"] = 0.02
                tuning["tighten_dev_holding"] = 0.02
            elif "STOP_LOSS" in exit_reason:
                category = "TRAILING_STOP_LOSS"
                lesson = (
                    f"Position stopped out at {net_pct:.1f}%. Price retreated from peak {position.highest_price_sol:.8f} SOL. "
                    f"Risk manager prevented total capital loss."
                )
                tuning["review_stop_pct"] = True
            elif "MOMENTUM_STALL" in exit_reason:
                category = "MOMENTUM_STALL"
                lesson = (
                    f"Bonding curve velocity stalled at {curve_pct_at_exit:.1f}%. "
                    f"Exited to free up capital rather than holding decaying asset."
                )
                tuning["tighten_entry_curve_band"] = True
            else:
                category = "STANDARD_LOSS"
                lesson = f"Trade closed with net loss {net_pnl:.4f} SOL due to {exit_reason}."

        log = EpisodicLog(
            log_id=str(uuid.uuid4())[:8],
            position_id=position.position_id,
            mint=position.mint,
            entry_time=position.entry_timestamp,
            exit_time=position.exit_timestamp or position.entry_timestamp,
            net_pnl_sol=round(net_pnl, 4),
            net_pnl_pct=round(net_pct, 2),
            trigger_wallet=position.trigger_wallet,
            trigger_reason=f"Confidence: {position.confidence_score:.2f}",
            exit_reason=exit_reason,
            curve_pct_at_entry=round(curve_pct_at_entry, 1),
            curve_pct_at_exit=round(curve_pct_at_exit, 1),
            outcome_category=category,
            lesson_learned=lesson,
            recommended_tuning=tuning,
        )

        self.db.save_episodic_log(log)
        return log
