"""
Per-Token Lifecycle & Thesis Invalidation Memory Manager.
Prevents repeated-entry death loops, tracks causal trade theses, and enforces regime dissimilarity hurdles.
"""
import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from core.models import TokenLifecycleState
from memory.database import DatabaseManager

logger = logging.getLogger("TokenLifecycle")


class TokenLifecycleManager:
    """
    Tracks each token's macroeconomic and operational lifecycle on Pump.fun.
    Enforces causal invalidation memory so the agent never buys a dying coin repeatedly.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager
        # mint -> lifecycle record
        self.lifecycles: Dict[str, Dict[str, Any]] = {}

    def get_lifecycle(self, mint: str, symbol: str = "TOKEN") -> Dict[str, Any]:
        """Retrieves or creates the lifecycle state for a token."""
        if mint in self.lifecycles:
            return self.lifecycles[mint]

        # Check DB
        if self.db:
            db_entry = self.db.get_token_lifecycle(mint)
            if db_entry:
                self.lifecycles[mint] = db_entry
                return db_entry

        now = time.time()
        new_entry = {
            "mint": mint,
            "symbol": symbol,
            "lifecycle_state": TokenLifecycleState.VIRGIN_SURGE.value,
            "trade_count": 0,
            "last_entry_thesis": None,
            "last_invalidation_reason": None,
            "failure_signatures": [],
            "cooldown_until": 0.0,
            "updated_at": now,
        }
        self.lifecycles[mint] = new_entry
        return new_entry

    def on_position_opened(self, mint: str, symbol: str, thesis: str):
        """Called when a position is opened in this token."""
        lc = self.get_lifecycle(mint, symbol)
        lc["lifecycle_state"] = TokenLifecycleState.IN_POSITION.value
        lc["trade_count"] += 1
        lc["last_entry_thesis"] = thesis
        lc["updated_at"] = time.time()
        self._persist(lc)

    def on_position_closed(
        self,
        mint: str,
        symbol: str,
        exit_reason: str,
        pnl_sol: float,
        pnl_pct: float,
        is_dev_dump: bool = False,
    ):
        """Called when a position exits. Records causal invalidation and updates state."""
        lc = self.get_lifecycle(mint, symbol)
        now = time.time()
        lc["last_invalidation_reason"] = exit_reason

        if is_dev_dump or "DEV_DUMP" in exit_reason:
            lc["lifecycle_state"] = TokenLifecycleState.TERMINAL_RUG.value
            lc["failure_signatures"].append("DEV_DUMP")
            lc["cooldown_until"] = now + 86400.0  # 24h lockout unless genuine CTO
            logger.info(f"🚫 [LIFECYCLE] {symbol} marked TERMINAL_RUG due to dev dump.")
        elif pnl_sol < 0 or pnl_pct <= -5.0:
            lc["lifecycle_state"] = TokenLifecycleState.THESIS_INVALIDATED.value
            sig = "STOP_LOSS" if "STOP" in exit_reason else ("STALL" if "STALL" in exit_reason else "GENERIC_LOSS")
            lc["failure_signatures"].append(sig)
            lc["cooldown_until"] = now + 300.0  # 5 min minimum cooldown
            logger.info(f"⚠️ [LIFECYCLE] {symbol} marked THESIS_INVALIDATED ({exit_reason}). Cooldown active.")
        else:
            # Closed profitably
            lc["lifecycle_state"] = TokenLifecycleState.DISTRIBUTION_CHURN.value
            lc["cooldown_until"] = now + 180.0  # 3 min cooldown to let distribution settle

        lc["updated_at"] = now
        self._persist(lc)

    def can_enter(self, mint: str, current_metrics: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Evaluates whether a token is permitted to be entered based on its lifecycle state
        and regime dissimilarity to prior failure modes.
        """
        lc = self.get_lifecycle(mint, current_metrics.get("symbol", "TOKEN"))
        state = lc["lifecycle_state"]
        now = time.time()

        if state == TokenLifecycleState.IN_POSITION.value:
            return False, "Position already active in token"

        if state == TokenLifecycleState.TERMINAL_RUG.value:
            # Check for genuine Community Takeover (CTO) revival
            dev_dumped = current_metrics.get("dev_dumped", True)
            vol_5m = current_metrics.get("vol_5m_sol", 0.0)
            buyers_5m = current_metrics.get("distinct_buyers_5m", 0)
            age_sec = current_metrics.get("age_seconds", 0.0)

            # CTO Criteria: dev out, high decentralized volume, age > 20 min
            if not dev_dumped and age_sec >= 1200.0 and vol_5m >= 2.0 and buyers_5m >= 4:
                lc["lifecycle_state"] = TokenLifecycleState.CTO_REVIVAL.value
                lc["cooldown_until"] = 0.0
                self._persist(lc)
                return True, "CTO Revival regime verified: dev tokens absorbed, fresh decentralized volume"
            return False, "Token is in TERMINAL_RUG state (dev dump / liquidity collapse)"

        if state == TokenLifecycleState.THESIS_INVALIDATED.value:
            # 1. Cooldown check
            if now < lc["cooldown_until"]:
                rem = int(lc["cooldown_until"] - now)
                return False, f"Token thesis invalidated; in cooldown ({rem}s remaining)"

            # 2. Regime Dissimilarity Check:
            # Do NOT re-enter if same conditions exist that caused previous stop-out
            vol_5m = current_metrics.get("vol_5m_sol", 0.0)
            buyers_5m = current_metrics.get("distinct_buyers_5m", 0)
            net_flow = current_metrics.get("net_flow_ratio", 0.5)

            # Re-entry requires significantly stronger volume and buyer distribution
            if vol_5m < 1.0 or buyers_5m < 3 or net_flow < 0.60:
                return False, "Re-entry denied: insufficient volume/flow dissimilarity from previous failure regime"

            # Re-entry allowed under new thesis
            return True, "Re-entry permitted: volume acceleration and buyer entropy prove new regime"

        if state == TokenLifecycleState.DISTRIBUTION_CHURN.value:
            if now < lc["cooldown_until"]:
                rem = int(lc["cooldown_until"] - now)
                return False, f"Distribution churn cooldown active ({rem}s remaining)"
            return True, "Distribution settled; ready for secondary breakout"

        # VIRGIN_SURGE or CTO_REVIVAL
        return True, "Virgin or CTO token eligible for evaluation"

    def _persist(self, lc: Dict[str, Any]):
        if self.db:
            try:
                self.db.upsert_token_lifecycle(
                    mint=lc["mint"],
                    symbol=lc["symbol"],
                    state=lc["lifecycle_state"],
                    trade_count=lc["trade_count"],
                    last_entry_thesis=lc["last_entry_thesis"],
                    last_invalidation_reason=lc["last_invalidation_reason"],
                    failure_signatures=lc["failure_signatures"],
                    cooldown_until=lc["cooldown_until"],
                )
            except Exception as e:
                logger.warning(f"Failed to persist token lifecycle: {e}")

    def reset(self):
        self.lifecycles.clear()
