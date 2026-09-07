"""
Autonomous Risk Manager & Dynamic Sizing Engine.
Decides position sizing based on learned confidence and autonomously manages trade exits.
"""
from __future__ import annotations
import time
from typing import Optional, Tuple, Any, Union
from core.models import PaperPosition, StrategyParameters
from core.constants import (
    INITIAL_BASE_TRADE_SOL,
    MAX_POSITION_SIZE_SOL,
    MAX_PORTFOLIO_ALLOCATION_PCT,
    MAX_CONCURRENT_POSITIONS,
    DEFAULT_TRAILING_STOP_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    MAX_HOLDING_TIME_SECONDS,
)


class RiskManager:
    """
    Dynamically sizes positions and evaluates real-time exit conditions.
    """

    def __init__(self, params: StrategyParameters):
        self.params = params

    def calculate_position_size(
        self,
        portfolio_balance: float,
        confidence_score: float,
        open_positions_count: int,
    ) -> float:
        """
        Calculates autonomous trade sizing.
        Starts at 0.1 SOL on cold-start / baseline confidence (0.5).
        Scales up as confidence increases with learned wallet track record.
        Strictly enforces safety caps (max portfolio allocation and max SOL limit).
        """
        if open_positions_count >= MAX_CONCURRENT_POSITIONS:
            return 0.0

        if portfolio_balance < 0.20:
            return 0.0  # Reserve gas buffer

        # Base cold-start size
        base_size = self.params.base_trade_sol

        if not self.params.confidence_scaling_enabled:
            return min(base_size, portfolio_balance * MAX_PORTFOLIO_ALLOCATION_PCT)

        # Confidence is on scale 0.0 to 1.0. Baseline is 0.5.
        # If confidence = 0.5 -> multiplier = 1.0 (0.1 SOL)
        # If confidence = 0.8 -> multiplier = 1.0 + (0.3 * 2.5) = 1.75 (0.175 SOL)
        # If confidence = 1.0 -> multiplier = 1.0 + (0.5 * 3.0) = 2.50 (0.25 SOL)
        confidence_clamped = min(1.0, max(0.4, confidence_score))
        multiplier = 1.0 + max(0.0, (confidence_clamped - 0.5) * 3.0)
        calculated_size = base_size * multiplier

        # Hard guardrails:
        # 1. Never exceed max trade cap
        size_capped = min(calculated_size, self.params.max_trade_sol, MAX_POSITION_SIZE_SOL)
        # 2. Never exceed 15% of total portfolio
        portfolio_limit = portfolio_balance * MAX_PORTFOLIO_ALLOCATION_PCT
        final_size = min(size_capped, portfolio_limit)

        return round(final_size, 3)

    def evaluate_exit(
        self,
        position: PaperPosition,
        current_bonding_progress: float,
        smart_wallet_exited: bool = False,
        dev_dump_detected: bool = False,
        return_fraction: bool = False,
    ) -> Any:
        """
        Backward-compatible wrapper. If return_fraction=True, returns (should_exit, reason, fraction).
        Otherwise returns (should_exit, reason). When return_fraction=False, only full position exits
        (stop-loss, trailing ratchet, stall timeout, dev dump) are returned.
        """
        should_exit, reason, fraction = self.evaluate_barbell_exit(
            position=position,
            current_bonding_progress=current_bonding_progress,
            smart_wallet_exited=smart_wallet_exited,
            dev_dump_detected=dev_dump_detected,
            allow_partial=return_fraction,
        )
        if return_fraction:
            return should_exit, reason, fraction
        return should_exit, reason

    def evaluate_barbell_exit(
        self,
        position: PaperPosition,
        current_bonding_progress: float,
        smart_wallet_exited: bool = False,
        dev_dump_detected: bool = False,
        allow_partial: bool = True,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Barbell Moonbag Execution Strategy:
        1. Fast Invalidation: Cuts dead trades at -8% to -10% within 90s if momentum fails.
        2. Milestone 1 (+100% / 2x): Sells 50% to return 100% of initial SOL. Trade becomes 100% risk-free!
        3. Milestone 2 (+400% / 5x): Sells 25% of initial tokens (50% remaining) to lock in 2.5x net profit.
        4. Parabolic Moonbag (100x to 10,000x): The remaining 25% bag is given an ultra-wide 35% breathing leash
           and holds through Raydium migration and beyond.
        Returns: (should_exit, reason, sell_fraction)
        """
        now = time.time()
        holding_duration = now - position.entry_timestamp
        gain_pct = position.unrealized_pnl_pct
        highest_price = position.highest_price_sol
        current_price = position.current_price_sol

        # 1. Emergency Exit: Dev dumped or insider rug detected
        if dev_dump_detected:
            return True, "EMERGENCY_DEV_DUMP_DETECTED", 1.0

        # 2. Fast Invalidation Defense:
        # If position stalls for > 90s, never gained > 4%, and net PnL drops to -8% or worse:
        if (
            holding_duration >= 90.0
            and highest_price <= (position.entry_price_sol * 1.04)
            and gain_pct <= -8.0
            and not position.is_moonbag
        ):
            return True, f"FAST_INVALIDATION_MOMENTUM_STALLED ({gain_pct:+.1f}%)", 1.0

        # 3. Barbell Moonbag Partial Profit De-Risking Milestones
        if allow_partial:
            # Milestone 1: At +100% (2x), sell 50% of tokens to return initial SOL capital 100% risk-free
            if gain_pct >= 100.0 and "HALF_INITIAL_SOL" not in position.moonbag_milestones_hit:
                return True, f"MOONBAG_50_PCT_DE_RISK_CAPITAL_RETURNED ({gain_pct:+.1f}%)", 0.50

            # Milestone 2: At +400% (5x), sell 50% of remaining bag to lock guaranteed 2.5x bank profit
            if gain_pct >= 400.0 and "LOCK_MOONBAG_PROFIT" not in position.moonbag_milestones_hit and "HALF_INITIAL_SOL" in position.moonbag_milestones_hit:
                return True, f"MOONBAG_25_PCT_PROFIT_LOCKED ({gain_pct:+.1f}%)", 0.50

        # 4. Smart Money Exit Decoupling:
        if smart_wallet_exited:
            can_decouple = (
                position.is_moonbag
                or (
                    gain_pct >= (self.params.breakeven_lock_threshold_pct * 100.0)
                    and current_bonding_progress >= 30.0
                    and self.params.smart_money_decoupling_pct >= 0.40
                )
            )
            if not can_decouple:
                return True, "TRACKED_SMART_WALLET_EXITED", 1.0

        # 5. Dynamic Multi-Tier Profit Ratchet & Wide Runner Leash
        if highest_price > 0:
            drawdown_from_peak = (highest_price - current_price) / highest_price

            if position.is_moonbag:
                # MOONBAG FREE ROLL: Zero risk (capital already safe).
                # 35% ultra-wide breathing leash from peak allows riding 100x to 10,000x parabolic runs!
                active_leash = 0.35
                if drawdown_from_peak >= active_leash:
                    return True, f"MOONBAG_RUNNER_EXIT ({gain_pct:+.1f}%)", 1.0

            elif gain_pct >= 500.0:
                # TIER 4: MEGA MOONSHOT (> 500% / 5x to 100x+)
                active_leash = min(0.35, max(0.30, self.params.runner_leash_pct + 0.05))
                if drawdown_from_peak >= active_leash or gain_pct < 250.0:
                    return True, f"MEGA_MOONSHOT_RUNNER_EXIT ({gain_pct:+.1f}%)", 1.0

            elif gain_pct >= 100.0:
                # TIER 3: MULTI-BAGGER RUNNER (+100% to +500% / 2x to 5x)
                active_leash = min(0.32, max(0.26, self.params.runner_leash_pct + 0.02))
                if drawdown_from_peak >= active_leash or gain_pct < 40.0:
                    return True, f"MULTI_BAGGER_PROFIT_LOCKED ({gain_pct:+.1f}%)", 1.0

            elif gain_pct >= (self.params.breakeven_lock_threshold_pct * 100.0):
                # TIER 2: BREAKEVEN LOCK (+35% to +100%)
                active_leash = min(0.28, max(0.22, self.params.runner_leash_pct))
                if drawdown_from_peak >= active_leash or gain_pct < 5.0:
                    return True, f"RUNNER_TRAILING_STOP_LOCKED ({gain_pct:+.1f}%)", 1.0

            else:
                # TIER 1: PRE-BREAKOUT / CAPITAL PRESERVATION (< +35%)
                if drawdown_from_peak >= self.params.trailing_stop_pct:
                    reason = (
                        f"TRAILING_STOP_PROFIT_PROTECTION ({gain_pct:+.1f}%)"
                        if gain_pct > 0
                        else f"STOP_LOSS_HIT (-{drawdown_from_peak * 100:.1f}%)"
                    )
                    return True, reason, 1.0

        # 6. Raydium Migration Immunity & Dynamic Holding Horizon
        if self.params.migration_hold_enabled and current_bonding_progress >= 40.0:
            return False, None, 1.0

        max_duration = getattr(self.params, "max_holding_seconds", 3600)
        if holding_duration > max_duration and not position.is_moonbag:
            return True, f"MOMENTUM_STALL_TIMEOUT ({int(holding_duration / 60)}m)", 1.0

        return False, None, 1.0
