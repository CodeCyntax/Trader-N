"""
Meta-Decision Brain: Bayesian Evidentiary Synthesis & Emergent Conviction Engine.
Synthesizes orthogonal brain votes, resolves adversarial vetoes, and enforces causal decision auditability.
"""
import time
import logging
from typing import Dict, Any, Optional
from core.models import TradeEvent, MetaDecision, BrainVote
from core.bonding_curve import PumpBondingCurve
from cognitive.brains.graph_brain import GraphBrain
from cognitive.brains.flow_brain import FlowBrain
from cognitive.brains.runner_brain import RunnerBrain
from cognitive.brains.adversary_brain import AdversaryBrain
from cognitive.brains.contrarian_brain import ContrarianBrain
from cognitive.brains.regime_brain import RegimeBrain
from cognitive.cluster_tracker import ClusterTracker

logger = logging.getLogger("MetaDecisionBrain")


class MetaDecisionBrain:
    """
    Synthesizes independent cognitive brain hypotheses into a final causal decision.
    Trade frequency is an emergent property of positive expected edge over dynamic regime hurdles.
    """

    def __init__(self, cluster_tracker: ClusterTracker):
        self.cluster_tracker = cluster_tracker
        self.graph_brain = GraphBrain(cluster_tracker)
        self.flow_brain = FlowBrain()
        self.runner_brain = RunnerBrain()
        self.adversary_brain = AdversaryBrain(cluster_tracker)
        self.contrarian_brain = ContrarianBrain()
        self.regime_brain = RegimeBrain()

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
        symbol: str = "TOKEN",
    ) -> MetaDecision:
        """
        Runs the full committee of cognitive brains and synthesizes the decision.
        """
        # Inject cluster summary into context for regime & adversary brains
        summary = self.cluster_tracker.get_cluster_summary()
        context.update(summary)

        # 1. Gather votes from all 6 brains
        regime_vote = self.regime_brain.evaluate(mint, trade, curve, context)
        regime = regime_vote.metrics.get("regime", "ORGANIC_MOMENTUM")
        hurdle_rate = float(regime_vote.metrics.get("hurdle_rate", 0.05))

        adversary_vote = self.adversary_brain.evaluate(mint, trade, curve, context)
        graph_vote = self.graph_brain.evaluate(mint, trade, curve, context)
        flow_vote = self.flow_brain.evaluate(mint, trade, curve, context)
        runner_vote = self.runner_brain.evaluate(mint, trade, curve, context)
        contrarian_vote = self.contrarian_brain.evaluate(mint, trade, curve, context)

        votes = {
            "RegimeBrain": regime_vote,
            "AdversaryBrain": adversary_vote,
            "GraphBrain": graph_vote,
            "FlowBrain": flow_vote,
            "RunnerBrain": runner_vote,
            "ContrarianBrain": contrarian_vote,
        }

        # 2. Check Hard Vetoes (e.g. AdversaryBrain triggered sybil trap or dev dump)
        if adversary_vote.veto:
            return MetaDecision(
                mint=mint,
                symbol=symbol,
                decision="PASS",
                expected_edge=-0.50,
                hurdle_rate=hurdle_rate,
                regime=regime,
                brain_votes=votes,
                veto_active=True,
                veto_source=f"AdversaryBrain ({adversary_vote.key_evidence})",
                dominant_reason=adversary_vote.key_evidence,
                suggested_size_sol=0.0,
                thesis="VETOED: Adversarial trap detected.",
                timestamp=time.time(),
            )

        # 3. Dynamic Regime-Conditioned Weighting
        if regime == "CABAL_PREDATORY":
            weights = {
                "AdversaryBrain": 0.35,
                "GraphBrain": 0.30,
                "FlowBrain": 0.15,
                "RunnerBrain": 0.10,
                "ContrarianBrain": 0.10,
            }
        elif regime == "LOW_LIQUIDITY_DEADZONE":
            weights = {
                "FlowBrain": 0.35,
                "AdversaryBrain": 0.25,
                "GraphBrain": 0.20,
                "RunnerBrain": 0.10,
                "ContrarianBrain": 0.10,
            }
        else:  # ORGANIC_MOMENTUM
            weights = {
                "RunnerBrain": 0.25,
                "FlowBrain": 0.25,
                "GraphBrain": 0.20,
                "AdversaryBrain": 0.15,
                "ContrarianBrain": 0.15,
            }

        # 4. Bayesian Evidentiary Synthesis Score
        synthesized_score = sum(
            weights[b_name] * votes[b_name].score * votes[b_name].confidence
            for b_name in weights
        )

        mean_confidence = sum(votes[b].confidence for b in weights) / len(weights)
        frictions = 0.025  # LP 100 bps buy/sell + network priority fee + slippage
        uncertainty_penalty = (1.0 - mean_confidence) * 0.06

        # Expected edge above breakeven: centered around score 0.50
        expected_edge = round(((synthesized_score - 0.40) * 0.45) - frictions - uncertainty_penalty, 4)

        # 5. Conviction Hurdle Evaluation
        if expected_edge > hurdle_rate:
            decision = "EXECUTE"
            dominant_reasons = []
            if runner_vote.score >= 0.70:
                dominant_reasons.append(f"high runner convexity ({runner_vote.score:.2f})")
            if flow_vote.score >= 0.70:
                dominant_reasons.append(f"accelerating order flow ({flow_vote.score:.2f})")
            if graph_vote.score >= 0.70:
                dominant_reasons.append(f"clean smart money topology ({graph_vote.score:.2f})")
            
            reason_str = ", ".join(dominant_reasons) if dominant_reasons else "broad multi-brain consensus"
            thesis = f"High-conviction {regime} entry driven by {reason_str}. Expected edge: {expected_edge:+.3f} (Hurdle: {hurdle_rate:.3f})."
            dominant_reason = thesis
        else:
            decision = "PASS"
            thesis = "PASS: Insufficient expected edge to overcome regime friction hurdle."
            # Identify weakest brain
            weakest = min(weights.keys(), key=lambda b: votes[b].score)
            dominant_reason = f"Expected edge ({expected_edge:+.3f}) below {regime} hurdle ({hurdle_rate:.3f}). Dragged by {weakest}: {votes[weakest].key_evidence}"

        return MetaDecision(
            mint=mint,
            symbol=symbol,
            decision=decision,
            expected_edge=expected_edge,
            hurdle_rate=hurdle_rate,
            regime=regime,
            brain_votes=votes,
            veto_active=False,
            veto_source=None,
            dominant_reason=dominant_reason,
            suggested_size_sol=0.0,  # Sized by risk manager if executed
            thesis=thesis,
            timestamp=time.time(),
        )

    def get_weights_for_regime(self, regime: str) -> Dict[str, float]:
        """Returns dynamic cognitive brain weights for a given market regime."""
        if regime == "CABAL_PREDATORY":
            return {
                "AdversaryBrain": 0.35,
                "GraphBrain": 0.30,
                "FlowBrain": 0.15,
                "RunnerBrain": 0.10,
                "ContrarianBrain": 0.10,
            }
        elif regime == "LOW_LIQUIDITY_DEADZONE":
            return {
                "FlowBrain": 0.35,
                "AdversaryBrain": 0.25,
                "GraphBrain": 0.20,
                "RunnerBrain": 0.10,
                "ContrarianBrain": 0.10,
            }
        else:  # ORGANIC_MOMENTUM
            return {
                "RunnerBrain": 0.25,
                "FlowBrain": 0.25,
                "GraphBrain": 0.20,
                "AdversaryBrain": 0.15,
                "ContrarianBrain": 0.15,
            }

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns comprehensive real-time telemetry of the multi-brain committee."""
        current_regime = getattr(self.regime_brain, "current_regime", "ORGANIC_MOMENTUM")
        current_hurdle = getattr(self.regime_brain, "current_hurdle", 0.05)
        return {
            "active_regime": current_regime,
            "hurdle_rate": current_hurdle,
            "brain_weights": self.get_weights_for_regime(current_regime),
            "brains": [
                {"name": "GraphBrain", "role": "Topology & Sybil Clusters", "drift_suppression": True},
                {"name": "FlowBrain", "role": "Microstructure & Velocity", "order_flow_ratio": True},
                {"name": "RunnerBrain", "role": "10x-100x Convexity Curve", "parabolic_potential": True},
                {"name": "AdversaryBrain", "role": "Honeypot & Cabal Veto", "veto_power": True},
                {"name": "ContrarianBrain", "role": "Stealth Accumulation vs FOMO", "exhaustion_fade": True},
                {"name": "RegimeBrain", "role": "Macro Climate & Hurdle", "hurdle_setter": True},
            ],
        }

