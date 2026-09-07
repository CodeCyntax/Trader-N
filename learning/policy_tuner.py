import time
from typing import Optional, Dict, Any, List
from core.models import StrategyParameters, EpisodicLog
from memory.database import DatabaseManager


class PolicyTuner:
    """
    Translates post-mortem learnings into persistent parameter updates.
    Continuously optimizes runner leashes, profit ratchets, holding horizons,
    and market regimes based on real trade feedback.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.current_params = self.db.get_strategy_params()

    def update_policy_from_learning(self, latest_log: EpisodicLog) -> StrategyParameters:
        """
        Adjusts strategy hyperparameters using reinforcement feedback from the latest trade.
        """
        params = self.db.get_strategy_params()
        recommendations = latest_log.recommended_tuning
        modified = False
        changes_applied: List[str] = []

        # 1. Dev Rug Defense: If we took a loss from a dev dump, raise the persistence bar
        if "increase_min_persistence" in recommendations:
            increment = recommendations["increase_min_persistence"]
            old_val = params.min_wallet_persistence_score
            params.min_wallet_persistence_score = round(min(0.75, old_val + increment), 3)
            modified = True
            changes_applied.append(f"Min persistence increased to {params.min_wallet_persistence_score:.2f}")

        if "tighten_dev_holding" in recommendations:
            old_dev_max = params.max_dev_holding_pct
            params.max_dev_holding_pct = round(max(0.04, old_dev_max - 0.01), 3)
            modified = True
            changes_applied.append(f"Max dev holding tightened to {params.max_dev_holding_pct * 100:.0f}%")

        # 2. Runner Leash & Moonbag Optimization (Anti-Premature Selling)
        if "widen_runner_leash" in recommendations:
            increment = recommendations["widen_runner_leash"]
            old_leash = getattr(params, "runner_leash_pct", 0.28)
            new_leash = round(min(0.38, old_leash + increment), 3)
            if new_leash != old_leash:
                params.runner_leash_pct = new_leash
                modified = True
                changes_applied.append(f"Runner breathing leash widened to {new_leash * 100:.1f}%")

        if "extend_holding_seconds" in recommendations:
            inc_secs = recommendations["extend_holding_seconds"]
            old_secs = getattr(params, "max_holding_seconds", 3600)
            new_secs = min(7200, old_secs + inc_secs)
            if new_secs != old_secs:
                params.max_holding_seconds = new_secs
                modified = True
                changes_applied.append(f"Max holding horizon extended to {int(new_secs / 60)}m")

        if "increase_decoupling" in recommendations:
            inc_dec = recommendations["increase_decoupling"]
            old_dec = getattr(params, "smart_money_decoupling_pct", 0.60)
            new_dec = round(min(0.85, old_dec + inc_dec), 2)
            if new_dec != old_dec:
                params.smart_money_decoupling_pct = new_dec
                modified = True
                changes_applied.append(f"Smart money decoupling increased to {new_dec * 100:.0f}%")

        # 3. Round-Trip Profit Defense (Anti-Greed)
        if "lower_breakeven_threshold" in recommendations:
            dec = recommendations["lower_breakeven_threshold"]
            old_be = getattr(params, "breakeven_lock_threshold_pct", 0.35)
            new_be = round(max(0.20, old_be - dec), 2)
            if new_be != old_be:
                params.breakeven_lock_threshold_pct = new_be
                modified = True
                changes_applied.append(f"Breakeven lock threshold lowered to +{new_be * 100:.0f}%")

        # 4. Performance-based Dynamic Sizing & Regime Adaptation (Rolling 15-Trade Window)
        recent_logs = self.db.get_recent_learnings(limit=15)
        if len(recent_logs) >= 5:
            profitable_count = sum(1 for r in recent_logs if r["net_pnl_sol"] > 0)
            recent_win_rate = profitable_count / len(recent_logs)
            runners_count = sum(1 for r in recent_logs if (r["net_pnl_pct"] or 0) >= 40.0)

            # Regime Determination
            if runners_count >= 2 and recent_win_rate >= 0.45:
                if params.market_regime != "RUNNER_ALPHA":
                    params.market_regime = "RUNNER_ALPHA"
                    params.migration_hold_enabled = True
                    modified = True
                    changes_applied.append("Market regime shifted to RUNNER_ALPHA (Migration holding active)")
            elif recent_win_rate <= 0.35:
                if params.market_regime != "DEFENSIVE_SCALP":
                    params.market_regime = "DEFENSIVE_SCALP"
                    modified = True
                    changes_applied.append("Market regime shifted to DEFENSIVE_SCALP (Tighter risk controls)")

            # Position Sizing Ceiling Adaptation
            if recent_win_rate >= 0.50 and runners_count >= 2:
                if params.max_trade_sol < 0.60:
                    params.max_trade_sol = round(params.max_trade_sol + 0.05, 2)
                    modified = True
                    changes_applied.append(f"Max trade ceiling expanded to {params.max_trade_sol:.2f} SOL")
                if params.base_trade_sol < 0.20:
                    params.base_trade_sol = round(params.base_trade_sol + 0.02, 2)
                    modified = True
                    changes_applied.append(f"Base trade size expanded to {params.base_trade_sol:.2f} SOL")
            elif recent_win_rate <= 0.35:
                if params.base_trade_sol > 0.10:
                    params.base_trade_sol = 0.10
                    modified = True
                    changes_applied.append("Base trade size reset to 0.10 SOL (Defensive)")
                if params.max_trade_sol > 0.35:
                    params.max_trade_sol = 0.35
                    modified = True
                    changes_applied.append("Max trade ceiling reset to 0.35 SOL (Defensive)")

        if modified:
            params.version += 1
            params.total_policy_adaptations = getattr(params, "total_policy_adaptations", 0) + 1

            # Log adaptation timeline
            history = getattr(params, "adaptation_history", [])
            history.insert(0, {
                "version": params.version,
                "timestamp": time.time(),
                "catalyst": latest_log.outcome_category,
                "token": latest_log.mint[:6] if latest_log.mint else "SYSTEM",
                "changes": changes_applied,
                "reasoning": latest_log.lesson_learned[:120] + "..." if len(latest_log.lesson_learned) > 120 else latest_log.lesson_learned
            })
            params.adaptation_history = history[:20]  # Keep last 20 adaptations

            self.db.save_strategy_params(params)
            self.current_params = params

        return params

    def reset(self):
        """Reloads parameters from database after a reset."""
        self.current_params = self.db.get_strategy_params()

