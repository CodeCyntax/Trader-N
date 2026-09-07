"""
Adversary Brain: Red Team auditor detecting sybil traps, copy-bot honeypots, and dev dump traps.
Holds Non-Linear Veto Power.
"""
from typing import Dict, Any
from cognitive.brains.base_brain import BaseBrain
from core.models import TradeEvent, BrainVote, ClusterArchetype
from core.bonding_curve import PumpBondingCurve
from cognitive.cluster_tracker import ClusterTracker


class AdversaryBrain(BaseBrain):
    """
    Simulates the attacker's perspective:
    Identifies copy-trading traps, liquidity rugs, and insider syndicates.
    Can issue hard vetoes to protect capital.
    """

    def __init__(self, cluster_tracker: ClusterTracker):
        super().__init__("AdversaryBrain")
        self.cluster_tracker = cluster_tracker

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        buyer = trade.trader_public_key
        dev_dumped = context.get("dev_dumped", False)
        dev_hold = context.get("dev_holding_pct", 0.0)
        vol_5m = context.get("vol_5m_sol", 0.0)
        buyers_5m = context.get("distinct_buyers_5m", 1)
        is_burner = context.get("is_burner", False)

        # 1. Dev Dump Trap -> Instant Hard Veto
        if dev_dumped:
            return BrainVote(
                brain_name=self.name,
                score=0.0,
                confidence=1.0,
                key_evidence="HARD VETO: Developer dumped tokens on-chain. Fatal rug trap.",
                veto=True,
                metrics={"trap_type": "DEV_DUMP"},
            )

        # 2. Deployer / Insider Cabal Syndicate -> Hard Veto
        cluster = self.cluster_tracker.get_cluster(buyer)
        if cluster:
            if cluster.archetype == ClusterArchetype.DEPLOYER_SYBIL:
                return BrainVote(
                    brain_name=self.name,
                    score=0.05,
                    confidence=0.95,
                    key_evidence=f"HARD VETO: Funder/deployer stealth sybil cluster ({cluster.cluster_id}).",
                    veto=True,
                    metrics={"trap_type": "DEPLOYER_SYBIL"},
                )
            if cluster.archetype == ClusterArchetype.INSIDER_CABAL and cluster.coordination_probability >= 0.85:
                # True insider cabals are small syndicates (<= 20 wallets)
                if len(cluster.member_addresses) <= 20:
                    return BrainVote(
                        brain_name=self.name,
                        score=0.10,
                        confidence=0.90,
                        key_evidence=f"HARD VETO: High-confidence insider cabal cluster ({len(cluster.member_addresses)} members, P={cluster.coordination_probability:.2f}).",
                        veto=True,
                        metrics={"trap_type": "INSIDER_CABAL"},
                    )
                else:
                    # Broad retail or market swarm (> 20 members), not an insider cabal
                    return BrainVote(
                        brain_name=self.name,
                        score=0.50,
                        confidence=0.60,
                        key_evidence=f"Broad participant swarm ({len(cluster.member_addresses)} members). No cabal veto.",
                        veto=False,
                        metrics={"trap_type": "RETAIL_SWARM"},
                    )

        # 3. Micro-Bait Copy-Bot Trap
        # Single micro trade (< 0.02 SOL) to trigger bots while dev holds > 12%
        if trade.sol_amount < 0.02 and dev_hold > 0.12 and buyers_5m <= 2:
            return BrainVote(
                brain_name=self.name,
                score=0.15,
                confidence=0.85,
                key_evidence=f"HARD VETO: Micro-bait signature (Trade: {trade.sol_amount:.3f} SOL, Dev: {dev_hold:.1%}). Likely bot trap.",
                veto=True,
                metrics={"trap_type": "MICRO_BAIT"},
            )

        # 4. Solitary Burner Volume Trap
        if is_burner and vol_5m < 0.20 and buyers_5m <= 1:
            return BrainVote(
                brain_name=self.name,
                score=0.20,
                confidence=0.80,
                key_evidence="HARD VETO: Solitary burner wallet trade with zero community breadth.",
                veto=True,
                metrics={"trap_type": "BURNER_SOLITARY"},
            )

        # Standard Safety Scoring
        safety_score = 1.0
        penalties = []

        if dev_hold > 0.08:
            penalty = (dev_hold - 0.08) * 3.0
            safety_score -= penalty
            penalties.append(f"Dev supply ({dev_hold:.1%})")

        if buyers_5m <= 2:
            safety_score -= 0.15
            penalties.append("Low buyer breadth (<=2)")

        if cluster and cluster.coordination_probability >= 0.60:
            safety_score -= 0.20
            penalties.append(f"Cluster overlap P={cluster.coordination_probability:.2f}")

        safety_score = max(0.20, min(0.95, safety_score))
        conf = 0.80

        evidence = (
            f"Adversarial audit passed (Safety: {safety_score:.2f}). " +
            (f"Flags: {', '.join(penalties)}" if penalties else "Clean anti-sybil profile.")
        )

        return BrainVote(
            brain_name=self.name,
            score=round(safety_score, 3),
            confidence=round(conf, 3),
            key_evidence=evidence,
            veto=False,
            metrics={"safety_score": safety_score, "penalties": penalties},
        )
