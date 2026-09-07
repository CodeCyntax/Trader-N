"""
Contrarian Brain: Evaluates crowd FOMO exhaustion, retail trap psychology, and stealth accumulation.
"""
from typing import Dict, Any
from cognitive.brains.base_brain import BaseBrain
from core.models import TradeEvent, BrainVote
from core.bonding_curve import PumpBondingCurve


class ContrarianBrain(BaseBrain):
    """
    Looks for crowd psychology mispricings:
    Fades retail FOMO at the top of curves; spots stealth smart accumulation during quiet consolidations.
    """

    def __init__(self):
        super().__init__("ContrarianBrain")

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        progress_pct = curve.get_progress_pct()
        vol_5m = context.get("vol_5m_sol", 0.0)
        buyers_5m = context.get("distinct_buyers_5m", 1)
        persistence = context.get("persistence_score", 0.0)

        # 1. Retail Top-Chasing Trap:
        # High curve (> 65%), many small buyers (> 8), but zero high-persistence smart wallets
        if progress_pct >= 65.0 and buyers_5m >= 6 and persistence < 0.45:
            score = 0.20
            conf = 0.80
            evidence = f"Crowd FOMO exhaustion at {progress_pct:.1f}% curve. Retail providing exit liquidity without smart money support."
        # 2. Stealth Accumulation Setup:
        # Curve 15% to 40%, moderate volume, high persistence smart buyer entering quietly
        elif 15.0 <= progress_pct <= 45.0 and persistence >= 0.65:
            score = 0.85
            conf = 0.75
            evidence = f"Stealth smart accumulation at {progress_pct:.1f}% curve. High-conviction entry ahead of retail herd."
        # 3. Healthy Early Expansion
        elif progress_pct < 50.0:
            score = 0.65
            conf = 0.60
            evidence = f"Balanced participant profile at {progress_pct:.1f}% curve."
        else:
            score = 0.45
            conf = 0.50
            evidence = f"Neutral crowd posture at {progress_pct:.1f}% curve."

        return BrainVote(
            brain_name=self.name,
            score=round(score, 3),
            confidence=round(conf, 3),
            key_evidence=evidence,
            veto=False,
            metrics={"crowd_fomo": (progress_pct >= 60.0 and persistence < 0.45)},
        )
