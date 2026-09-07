"""
Flow Brain: Evaluates order flow microstructure, volume acceleration, and net order flow imbalances.
"""
from typing import Dict, Any
from cognitive.brains.base_brain import BaseBrain
from core.models import TradeEvent, BrainVote
from core.bonding_curve import PumpBondingCurve


class FlowBrain(BaseBrain):
    """
    Analyzes tick-level order flow dynamics:
    Measures buy-side aggression, volume acceleration, and buyer absorption.
    """

    def __init__(self):
        super().__init__("FlowBrain")

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        vol_5m = context.get("vol_5m_sol", 0.0)
        buy_vol = context.get("buy_vol_5m_sol", 0.0)
        sell_vol = context.get("sell_vol_5m_sol", 0.0)
        vol_1m = context.get("vol_1m_sol", 0.0)
        buyers_5m = context.get("distinct_buyers_5m", 1)

        # 1. Net Order Flow Imbalance [-1.0, 1.0]
        denom = buy_vol + sell_vol + 0.001
        net_flow = (buy_vol - sell_vol) / denom

        # 2. Volume Acceleration (1m pace vs 5m baseline pace)
        baseline_1m_pace = (vol_5m / 5.0) + 0.001
        accel = vol_1m / baseline_1m_pace

        # 3. Buyer Diversity
        # Score calculation
        base_score = 0.50
        flow_boost = net_flow * 0.25  # up to +0.25 if pure buy flow
        accel_boost = min(0.20, max(-0.20, (accel - 1.0) * 0.10))
        diversity_boost = min(0.15, (buyers_5m - 1) * 0.04)

        score = max(0.05, min(0.95, base_score + flow_boost + accel_boost + diversity_boost))

        # Confidence scales with sample size (total volume)
        conf = min(0.90, max(0.35, 0.40 + (vol_5m / 10.0) * 0.35 + (buyers_5m / 10.0) * 0.15))

        evidence = (
            f"Net Flow: {net_flow:+.1%}, Accel: {accel:.1f}x, 5m Vol: {vol_5m:.2f} SOL, "
            f"Buyers: {buyers_5m} distinct."
        )

        return BrainVote(
            brain_name=self.name,
            score=round(score, 3),
            confidence=round(conf, 3),
            key_evidence=evidence,
            veto=False,
            metrics={"net_flow": net_flow, "accel": accel, "vol_5m": vol_5m, "buyers_5m": buyers_5m},
        )
