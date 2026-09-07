"""
Counterfactual Shadow Ledger Engine: Tracks and learns from non-traded tokens.
Monitors price evolution of passed tokens over 60 minutes to audit false negatives and confirmed dodges.
"""
import json
import time
import logging
from typing import Dict, List, Optional, Any
from core.models import MetaDecision, CounterfactualRecord
from memory.database import DatabaseManager

logger = logging.getLogger("CounterfactualEngine")


class CounterfactualEngine:
    """
    Maintains a shadow portfolio of every candidate token evaluated and NOT traded.
    Audits what would have happened if we had bought, measuring saved capital vs missed moonshots.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None, shadow_horizon_seconds: float = 3600.0):
        self.db = db_manager
        self.horizon_seconds = shadow_horizon_seconds
        # mint -> CounterfactualRecord
        self.active_shadows: Dict[str, CounterfactualRecord] = {}
        self.recent_decisions: List[Dict[str, Any]] = []

        if self.db:
            self._load_active_shadows()

    def _load_active_shadows(self):
        try:
            persisted = self.db.get_active_counterfactuals()
            for rec in persisted:
                self.active_shadows[rec.mint] = rec
        except Exception as e:
            logger.warning(f"Could not load active counterfactuals: {e}")

    def register_evaluation(
        self,
        decision: MetaDecision,
        spot_price_sol: float,
        curve_pct: float,
    ):
        """Records an evaluation decision (especially PASS or VETO) into the shadow ledger."""
        now = time.time()
        cf_id = f"cf_{decision.mint[:6]}_{int(now)}"

        # Serialize brain votes for causal auditability
        brain_scores = {
            b_name: {
                "score": vote.score,
                "confidence": vote.confidence,
                "evidence": vote.key_evidence,
                "veto": vote.veto,
            }
            for b_name, vote in decision.brain_votes.items()
        }

        # Keep recent decision in rolling memory for UI feed
        dec_summary = {
            "timestamp": now,
            "mint": decision.mint,
            "symbol": decision.symbol,
            "decision": decision.decision,
            "expected_edge": decision.expected_edge,
            "hurdle_rate": decision.hurdle_rate,
            "regime": decision.regime,
            "veto_active": decision.veto_active,
            "veto_source": decision.veto_source,
            "dominant_reason": decision.dominant_reason,
            "brain_scores": brain_scores,
        }
        self.recent_decisions.append(dec_summary)
        if len(self.recent_decisions) > 50:
            self.recent_decisions = self.recent_decisions[-50:]

        # Only shadow-track non-trades (PASS or VETO)
        if decision.decision == "EXECUTE":
            return

        # Avoid duplicate tracking if already active
        if decision.mint in self.active_shadows:
            return

        record = CounterfactualRecord(
            cf_id=cf_id,
            mint=decision.mint,
            symbol=decision.symbol,
            evaluation_time=now,
            decision=decision.decision,
            dominant_reason=decision.dominant_reason,
            expected_edge=decision.expected_edge,
            initial_price_sol=spot_price_sol,
            initial_curve_pct=curve_pct,
            peak_price_sol=spot_price_sol,
            final_price_sol=spot_price_sol,
            peak_multiplier=1.0,
            final_return_pct=0.0,
            counterfactual_outcome="PENDING",
            status="TRACKING",
            last_updated=now,
            brain_scores_json=json.dumps(brain_scores),
        )

        self.active_shadows[decision.mint] = record
        if self.db:
            try:
                self.db.record_counterfactual(record)
            except Exception as e:
                logger.warning(f"Failed to record counterfactual: {e}")

    def update_price(self, mint: str, current_price_sol: float, current_time: Optional[float] = None):
        """Updates real-time price evolution for a shadow-tracked token."""
        record = self.active_shadows.get(mint)
        if not record or record.status != "TRACKING":
            return

        now = current_time or time.time()
        record.last_updated = now
        record.final_price_sol = current_price_sol

        if current_price_sol > record.peak_price_sol:
            record.peak_price_sol = current_price_sol

        if record.initial_price_sol > 0:
            record.peak_multiplier = round(record.peak_price_sol / record.initial_price_sol, 2)
            record.final_return_pct = round(
                (current_price_sol - record.initial_price_sol) / record.initial_price_sol * 100.0, 2
            )

        # Check if horizon reached (60m)
        if (now - record.evaluation_time) >= self.horizon_seconds:
            self._resolve_record(record, now)

    def _resolve_record(self, record: CounterfactualRecord, now: float):
        """Resolves a completed shadow tracking session into an auditable outcome."""
        record.status = "RESOLVED"
        record.last_updated = now

        if record.peak_multiplier >= 10.0:
            record.counterfactual_outcome = "FALSE_NEGATIVE_10X_RUNNER"
            logger.warning(
                f"🚨 [COUNTERFACTUAL ALERT] Missed 10x runner: {record.symbol} ({record.mint[:6]}...) "
                f"peaked at {record.peak_multiplier:.1f}x. Dominant skip reason: {record.dominant_reason}"
            )
        elif record.peak_multiplier >= 3.0:
            record.counterfactual_outcome = "FALSE_NEGATIVE_3X_GAIN"
        elif record.final_return_pct <= -50.0:
            record.counterfactual_outcome = "CONFIRMED_RUG_DODGE"
        else:
            record.counterfactual_outcome = "CONFIRMED_CHOP_DODGE"

        # Remove from active memory dict
        self.active_shadows.pop(record.mint, None)

        if self.db:
            try:
                self.db.record_counterfactual(record)
            except Exception as e:
                logger.warning(f"Failed to persist resolved counterfactual: {e}")

    def resolve_counterfactuals(self, horizon_seconds: Optional[float] = None) -> int:
        """Resolves all shadow records that have reached their evaluation horizon."""
        horizon = horizon_seconds if horizon_seconds is not None else self.horizon_seconds
        now = time.time()
        resolved_count = 0

        # 1. Resolve in-memory active shadows that have exceeded horizon
        to_resolve = [
            rec for rec in list(self.active_shadows.values())
            if (now - rec.evaluation_time) >= horizon
        ]
        for rec in to_resolve:
            self._resolve_record(rec, now)
            resolved_count += 1

        # 2. Resolve in SQLite database
        if self.db:
            try:
                db_resolved = self.db.resolve_counterfactuals(horizon_seconds=horizon, current_time=now)
                resolved_count = max(resolved_count, db_resolved)
            except Exception as e:
                logger.warning(f"Failed to resolve DB counterfactuals: {e}")

        return resolved_count

    def get_summary(self) -> Dict[str, Any]:
        if self.db:
            return self.db.get_counterfactual_summary()
        return {
            "total_counterfactuals_tracked": len(self.active_shadows),
            "currently_tracking": len(self.active_shadows),
            "confirmed_rug_dodges": 0,
            "confirmed_chop_dodges": 0,
            "missed_runners_count": 0,
            "estimated_capital_preserved_sol": 0.0,
        }

    def get_recent_decisions(self, limit: int = 15) -> List[Dict[str, Any]]:
        return self.recent_decisions[-limit:]

    def reset(self):
        self.active_shadows.clear()
        self.recent_decisions.clear()
