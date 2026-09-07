"""
Runner Brain: Evaluates asymmetric 10x to 1,000x convexity and parabolic potential.
"""
from typing import Dict, Any
from cognitive.brains.base_brain import BaseBrain
from core.models import TradeEvent, BrainVote
from core.bonding_curve import PumpBondingCurve


class RunnerBrain(BaseBrain):
    """
    Looks for the mathematical signature of massive runners:
    Sweet-spot bonding curve progression, low dev retention, and high holder dispersion.
    """

    def __init__(self):
        super().__init__("RunnerBrain")

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        progress_pct = curve.get_progress_pct()
        dev_hold = context.get("dev_holding_pct", 0.0)
        age_sec = context.get("age_seconds", 0.0)
        buyers_5m = context.get("distinct_buyers_5m", 1)

        # 1. Curve Positioning Sweet Spot (Convexity Peak: 15% to 45%)
        # Tokens < 10% have high rug mortality; tokens > 60% have capped remaining pump.fun multiples
        if 15.0 <= progress_pct <= 42.0:
            curve_convexity = 0.85
        elif 10.0 <= progress_pct < 15.0:
            curve_convexity = 0.65
        elif 42.0 < progress_pct <= 60.0:
            curve_convexity = 0.55
        elif progress_pct > 70.0:
            curve_convexity = 0.20  # Too late for 10x on bonding curve
        else:
            curve_convexity = 0.35  # Ultra virgin < 10%

        # 2. Dev Supply Drain (Dev holding < 5% = high safety for runners)
        if dev_hold <= 0.02:
            dev_score = 0.90
        elif dev_hold <= 0.07:
            dev_score = 0.70
        elif dev_hold <= 0.15:
            dev_score = 0.40
        else:
            dev_score = 0.10  # Massive dev dump sword hanging over coin

        # 3. Holder Dispersion
        dispersion = min(1.0, buyers_5m / 6.0)

        # 4. Age Velocity
        if age_sec < 60.0:
            age_factor = 0.50  # Very early, unpredictable
        elif age_sec <= 900.0:
            age_factor = 0.85  # Prime runner expansion window (1m - 15m)
        elif age_sec <= 3600.0:
            age_factor = 0.65
        else:
            age_factor = 0.40  # Old token, needs CTO to run

        # Weighted runner potential
        runner_score = (
            curve_convexity * 0.40 +
            dev_score * 0.25 +
            dispersion * 0.20 +
            age_factor * 0.15
        )

        conf = 0.75 if (buyers_5m >= 3 and age_sec >= 60.0) else 0.50

        evidence = (
            f"Curve: {progress_pct:.1f}% (Convexity: {curve_convexity:.2f}), "
            f"Dev Share: {dev_hold:.1%}, Age: {age_sec/60.0:.1f}m, "
            f"Dispersion: {dispersion:.2f}."
        )

        return BrainVote(
            brain_name=self.name,
            score=round(runner_score, 3),
            confidence=round(conf, 3),
            key_evidence=evidence,
            veto=False,
            metrics={"curve_pct": progress_pct, "dev_hold": dev_hold, "convexity": curve_convexity},
        )
