"""
Token Activity & Micro-Volume Monitor.
Tracks real-time rolling 5-minute volume, distinct buyer counts, dev dump status,
and enforces strict activity thresholds to prevent buying dead, abandoned, or rugged tokens.
Validates revival/CTO volume surges before allowing entry into older tokens.
"""
import time
from typing import Dict, Optional, Tuple
from core.models import TokenActivity, TradeEvent, TradeType, StrategyParameters


class TokenMonitor:
    """
    Maintains rolling activity windows for all observed tokens.
    Filters out dead coins with little/no activity and validates revival momentum.
    """

    def __init__(self):
        self.activities: Dict[str, TokenActivity] = {}

    def get_or_create_activity(
        self,
        mint: str,
        created_at: Optional[float] = None,
        dev_wallet: Optional[str] = None
    ) -> TokenActivity:
        if mint not in self.activities:
            self.activities[mint] = TokenActivity(
                mint=mint,
                first_seen=time.time(),
                created_at=created_at or time.time(),
                dev_wallet=dev_wallet,
            )
        else:
            if created_at and not self.activities[mint].created_at:
                self.activities[mint].created_at = created_at
            if dev_wallet and not self.activities[mint].dev_wallet:
                self.activities[mint].dev_wallet = dev_wallet
        return self.activities[mint]

    def record_trade(self, trade: TradeEvent, dev_wallet: Optional[str] = None):
        """Records a live trade and updates rolling volume, buyer breadth, and dev status."""
        mint = trade.mint
        activity = self.get_or_create_activity(mint, dev_wallet=dev_wallet)
        now = trade.timestamp or time.time()

        # Update dev dump flag if dev sells significant tokens
        effective_dev = dev_wallet or activity.dev_wallet
        if (
            trade.tx_type == TradeType.SELL
            and effective_dev
            and trade.trader_public_key == effective_dev
            and trade.token_amount > 5_000_000
        ):
            activity.dev_dumped = True

        # Prune trades older than 5 minutes (300 seconds)
        activity.prune_old_trades(window_seconds=300.0, current_time=now)

        if trade.tx_type == TradeType.BUY:
            activity.recent_buys.append((now, trade.sol_amount, trade.trader_public_key))
        elif trade.tx_type == TradeType.SELL:
            activity.recent_sells.append((now, trade.sol_amount, trade.trader_public_key))

        activity.total_trades += 1

    def is_token_eligible_for_entry(
        self,
        mint: str,
        params: StrategyParameters,
        current_time: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether a token has sufficient genuine volume, buyer breadth,
        and momentum to justify entry. Rejects dead, rugged, or low-activity coins.
        """
        activity = self.activities.get(mint)
        now = current_time or time.time()

        if not activity:
            # If we have literally 0 trade history for this token in memory, it has no activity
            return False, "NO_RECORDED_ACTIVITY"

        # Prune old trades
        activity.prune_old_trades(window_seconds=300.0, current_time=now)

        # 1. Dev Rug Defense: If dev dumped, permanently reject unless explicitly overridden
        if params.reject_dev_dumped_tokens and activity.dev_dumped:
            return False, "DEV_ALREADY_DUMPED_RUGGED"

        # 2. Token Age & Revival (CTO) Verification
        age_seconds = now - (activity.created_at or activity.first_seen)
        is_older_token = age_seconds > params.revival_age_threshold_seconds  # > 30 minutes

        if is_older_token:
            # For older tokens to be eligible, they MUST prove a REAL volume explosion (CTO / Revival)
            # Cannot buy on just 1 smart wallet buy or tiny dust!
            if activity.buy_volume_5m_sol < params.revival_min_volume_5m_sol:
                return False, f"REVIVAL_BUY_VOLUME_TOO_LOW ({activity.buy_volume_5m_sol:.2f} < {params.revival_min_volume_5m_sol:.2f} SOL in 5m)"

            if activity.distinct_buyers_5m < params.revival_min_distinct_buyers:
                return False, f"REVIVAL_BUYER_COUNT_TOO_LOW ({activity.distinct_buyers_5m} < {params.revival_min_distinct_buyers} buyers in 5m)"

            # Ensure net buy pressure (buyers are outstripping sellers)
            if activity.buy_volume_5m_sol < (activity.sell_volume_5m_sol * 1.1):
                return False, f"REVIVAL_NET_FLOW_NEGATIVE (Buys: {activity.buy_volume_5m_sol:.2f} SOL vs Sells: {activity.sell_volume_5m_sol:.2f} SOL)"

        else:
            # Fresh tokens (< 30 minutes) must have minimum baseline activity and multiple buyers
            if activity.total_volume_5m_sol < params.min_volume_5m_sol:
                return False, f"DEAD_TOKEN_VOLUME_TOO_LOW ({activity.total_volume_5m_sol:.2f} < {params.min_volume_5m_sol:.2f} SOL in 5m)"

            if activity.distinct_buyers_5m < params.min_distinct_buyers_5m:
                return False, f"INSUFFICIENT_BUYER_BREADTH ({activity.distinct_buyers_5m} < {params.min_distinct_buyers_5m} buyers in 5m)"

        return True, "ELIGIBLE"

    def prune_stale_activities(self, cutoff_seconds: float = 900.0, max_activities: int = 150):
        """Evicts inactive tokens to keep memory footprint bounded and lightweight."""
        now = time.time()
        cutoff = now - cutoff_seconds
        stale_mints = [
            mint for mint, act in self.activities.items()
            if (act.last_trade_time and act.last_trade_time < cutoff) or ((now - act.first_seen) > cutoff_seconds and act.total_trades == 0)
        ]
        for m in stale_mints:
            self.activities.pop(m, None)

        if len(self.activities) > max_activities:
            sorted_items = sorted(
                self.activities.items(),
                key=lambda x: x[1].last_trade_time or 0.0,
                reverse=True
            )
            self.activities = dict(sorted_items[:max_activities])

    def reset(self):
        """Clears all in-memory rolling token activity windows."""
        self.activities.clear()

