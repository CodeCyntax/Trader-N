"""
Graph Brain: Evaluates entity coordination, cluster archetypes, and identity reputation.
"""
from typing import Dict, Any
from cognitive.brains.base_brain import BaseBrain
from core.models import TradeEvent, BrainVote, ClusterArchetype
from core.bonding_curve import PumpBondingCurve
from cognitive.cluster_tracker import ClusterTracker


class GraphBrain(BaseBrain):
    """
    Evaluates on-chain entity graphs: unmasks cabals, deployer stealth sybils,
    and weights genuine decentralized alpha vs puppet clusters.
    """

    def __init__(self, cluster_tracker: ClusterTracker):
        super().__init__("GraphBrain")
        self.cluster_tracker = cluster_tracker

    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        buyer = trade.trader_public_key
        persistence = context.get("persistence_score", 0.0)

        # 1. Check identity drift
        is_drifting, d_kl, drift_msg = self.cluster_tracker.check_identity_drift(buyer)

        # 2. Check cluster membership
        cluster = self.cluster_tracker.get_cluster(buyer)

        if cluster:
            coord_prob = cluster.coordination_probability
            arch = cluster.archetype

            if arch == ClusterArchetype.DEPLOYER_SYBIL:
                score = 0.05
                conf = 0.90
                evidence = f"Deployer sybil cluster detected (Coordination P={coord_prob:.2f}). Direct insider link."
            elif arch == ClusterArchetype.INSIDER_CABAL:
                if len(cluster.member_addresses) <= 20:
                    score = 0.15
                    conf = 0.85
                    evidence = f"Insider cabal bundle detected ({len(cluster.member_addresses)} wallets, sync={cluster.avg_entry_delta_seconds:.1f}s). High dump risk."
                else:
                    score = 0.45
                    conf = 0.60
                    evidence = f"Broad participant cluster ({len(cluster.member_addresses)} wallets). Mild caution."
            elif arch == ClusterArchetype.COPY_RETAIL:
                score = 0.35
                conf = 0.70
                evidence = f"Copy retail follower cluster. Jaccard overlap={cluster.jaccard_token_overlap:.2f}. Late entry profile."
            elif arch == ClusterArchetype.ORGANIC_SMART:
                score = min(0.95, 0.65 + persistence * 0.30)
                conf = 0.80
                evidence = f"Verified organic smart cluster (P={coord_prob:.2f}). High historical persistence ({persistence:.2f})."
            else:
                score = 0.50
                conf = 0.50
                evidence = f"Unclassified cluster (Coordination P={coord_prob:.2f}, {len(cluster.member_addresses)} members)."
        else:
            # Unclustered wallet
            if persistence >= 0.60:
                score = min(0.90, 0.50 + persistence * 0.40)
                conf = 0.75
                evidence = f"Independent high-conviction smart wallet ({persistence:.2f} score). No sybil cluster links."
            elif persistence >= 0.40:
                score = 0.55
                conf = 0.50
                evidence = f"Moderate persistence wallet ({persistence:.2f} score). Clean topological graph."
            else:
                score = 0.35
                conf = 0.45
                evidence = f"Low persistence or newly observed wallet ({persistence:.2f} score)."

        if is_drifting:
            score = max(0.15, score * 0.60)
            conf = max(0.30, conf * 0.50)
            evidence += f" [ALERT: Identity drift suppressed D_KL={d_kl:.2f}]"

        return BrainVote(
            brain_name=self.name,
            score=round(score, 3),
            confidence=round(conf, 3),
            key_evidence=evidence,
            veto=False,
            metrics={"d_kl": d_kl, "is_drifting": is_drifting, "cluster_id": cluster.cluster_id if cluster else None},
        )
