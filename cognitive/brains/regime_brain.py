"""
Regime Brain: Evaluates the macro Pump.fun market condition and sets the dynamic hurdle rate.
"""
import time
from typing import Dict, Any, List
from cognitive.brains.base_brain import BaseBrain
from core.models import TradeEvent, BrainVote
from core.bonding_curve import PumpBondingCurve


class RegimeBrain(BaseBrain):
    """
    Identifies the macro market climate:
    ORGANIC_MOMENTUM (favorable), CABAL_PREDATORY (adversarial), or LOW_LIQUIDITY_DEADZONE (dormant).
    """

    def __init__(self):
        super().__init__("RegimeBrain")
        # Rolling recent trade timestamps across ALL tokens
        self.market_trade_timestamps: List[float] = []
        self.current_regime: str = "ORGANIC_MOMENTUM"
        self.current_hurdle: float = 0.05

    def record_market_trade(self, ts: float):
        self.market_trade_timestamps.append(ts)
        cutoff = ts - 300.0
        if len(self.market_trade_timestamps) > 500:
            self.market_trade_timestamps = [t for t in self.market_trade_timestamps if t >= cutoff]

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        now = trade.timestamp or time.time()
        self.record_market_trade(now)

        cutoff = now - 300.0
        recent_market_trades = sum(1 for t in self.market_trade_timestamps if t >= cutoff)
        
        # Check cluster prevalence in context
        cabal_count = context.get("cabal_clusters_count", 0)

        # 1. Classify Macro Regime
        if recent_market_trades < 15:
            regime = "LOW_LIQUIDITY_DEADZONE"
            score = 0.25
            hurdle = 0.15  # High hurdle: cash is active alpha
            evidence = f"Low market liquidity ({recent_market_trades} trades in 5m). Conservative cash posture."
        elif cabal_count >= 10:
            regime = "CABAL_PREDATORY"
            score = 0.40
            hurdle = 0.08  # Elevated hurdle: require clear edge
            evidence = f"Predatory cabal climate ({cabal_count} active sybil clusters). Elevated skepticism."
        else:
            regime = "ORGANIC_MOMENTUM"
            score = 0.80
            hurdle = 0.05  # Standard hurdle
            evidence = f"Healthy organic momentum ({recent_market_trades} market trades in 5m). Favorable launch environment."
        
        self.current_regime = regime
        self.current_hurdle = hurdle

        conf = 0.85

        return BrainVote(
            brain_name=self.name,
            score=round(score, 3),
            confidence=round(conf, 3),
            key_evidence=evidence,
            veto=False,
            metrics={"regime": regime, "hurdle_rate": hurdle, "market_velocity_5m": recent_market_trades},
        )
