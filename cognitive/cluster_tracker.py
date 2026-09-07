"""
Probabilistic Cluster Tracker & Identity Evolution (Drift) Engine.
Unmasks entity syndicates, temporal bundle synchrony, and behavioral regime shifts.
"""
from __future__ import annotations
import math
import time
import logging
from typing import Dict, List, Set, Optional, Tuple, Any
from core.models import TradeEvent, TradeType, ClusterHypothesis, ClusterArchetype
from memory.database import DatabaseManager

logger = logging.getLogger("ClusterTracker")


class ClusterTracker:
    """
    Tracks probabilistic on-chain wallet clusters and detects behavioral identity drift.
    Prevents trusting 'smart' wallets that have shifted regimes or are part of sybil cabals.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager
        # In-memory fast tracking caches
        # mint -> list of recent buys: [(timestamp, wallet_addr, sol_amount)]
        self.recent_mint_buys: Dict[str, List[Tuple[float, str, float]]] = {}
        # wallet -> set of tokens traded
        self.wallet_tokens: Dict[str, Set[str]] = {}
        # wallet -> list of past trades: [{"curve_pct": float, "size_sol": float, "timestamp": float}]
        self.wallet_trade_history: Dict[str, List[Dict[str, float]]] = {}
        # cluster_id -> ClusterHypothesis
        self.clusters: Dict[str, ClusterHypothesis] = {}
        # wallet_address -> cluster_id
        self.wallet_to_cluster: Dict[str, str] = {}
        # wallet_address -> is_suppressed_due_to_drift
        self.drift_suppressed_wallets: Dict[str, float] = {}  # wallet -> suppression expiry

        if self.db:
            self._load_clusters_from_db()

    def _load_clusters_from_db(self):
        try:
            persisted = self.db.get_all_clusters(limit=100)
            for c in persisted:
                self.clusters[c.cluster_id] = c
                for addr in c.member_addresses:
                    self.wallet_to_cluster[addr] = c.cluster_id
        except Exception as e:
            logger.warning(f"Could not load clusters from DB: {e}")

    def record_trade(self, trade: TradeEvent, dev_wallet: Optional[str] = None):
        """Processes an incoming trade to detect timing synchrony and cluster coordination."""
        buyer = trade.trader_public_key
        mint = trade.mint
        ts = trade.timestamp or time.time()

        # Update wallet token set
        if buyer not in self.wallet_tokens:
            self.wallet_tokens[buyer] = set()
        self.wallet_tokens[buyer].add(mint)

        # Update trade history for identity tracking
        if buyer not in self.wallet_trade_history:
            self.wallet_trade_history[buyer] = []
        self.wallet_trade_history[buyer].append({
            "curve_pct": trade.bonding_curve_pct or 20.0,
            "size_sol": trade.sol_amount,
            "timestamp": ts,
        })
        if len(self.wallet_trade_history[buyer]) > 50:
            self.wallet_trade_history[buyer] = self.wallet_trade_history[buyer][-50:]

        if trade.tx_type != TradeType.BUY:
            return

        # Maintain rolling 5-minute buy window for mint
        if mint not in self.recent_mint_buys:
            self.recent_mint_buys[mint] = []
        
        # Prune older than 300s
        cutoff = ts - 300.0
        self.recent_mint_buys[mint] = [b for b in self.recent_mint_buys[mint] if b[0] >= cutoff]

        # Detect temporal co-entry with other wallets within 2.0 seconds
        for prev_ts, prev_buyer, prev_size in self.recent_mint_buys[mint]:
            if prev_buyer == buyer:
                continue

            delta_t = abs(ts - prev_ts)
            if delta_t <= 2.5:  # Coordinated entry within 2.5s
                self._record_coordination(buyer, prev_buyer, delta_t, dev_wallet)

        self.recent_mint_buys[mint].append((ts, buyer, trade.sol_amount))

    def _record_coordination(
        self,
        wallet_a: str,
        wallet_b: str,
        delta_t: float,
        dev_wallet: Optional[str] = None
    ):
        """Merges or creates a cluster between wallet_a and wallet_b."""
        cluster_id_a = self.wallet_to_cluster.get(wallet_a)
        cluster_id_b = self.wallet_to_cluster.get(wallet_b)

        # Calculate token overlap Jaccard index
        tokens_a = self.wallet_tokens.get(wallet_a, set())
        tokens_b = self.wallet_tokens.get(wallet_b, set())
        union_len = len(tokens_a.union(tokens_b))
        jaccard = (len(tokens_a.intersection(tokens_b)) / union_len) if union_len > 0 else 0.0

        target_cluster: Optional[ClusterHypothesis] = None

        if cluster_id_a and cluster_id_a in self.clusters:
            target_cluster = self.clusters[cluster_id_a]
            if wallet_b not in target_cluster.member_addresses:
                target_cluster.member_addresses.append(wallet_b)
                self.wallet_to_cluster[wallet_b] = cluster_id_a
        elif cluster_id_b and cluster_id_b in self.clusters:
            target_cluster = self.clusters[cluster_id_b]
            if wallet_a not in target_cluster.member_addresses:
                target_cluster.member_addresses.append(wallet_a)
                self.wallet_to_cluster[wallet_a] = cluster_id_b
        else:
            # Create new cluster
            cid = f"cluster_{wallet_a[:4]}_{wallet_b[:4]}_{int(time.time())}"
            target_cluster = ClusterHypothesis(
                cluster_id=cid,
                member_addresses=[wallet_a, wallet_b],
                coordination_probability=0.55,
                archetype=ClusterArchetype.UNKNOWN,
            )
            self.clusters[cid] = target_cluster
            self.wallet_to_cluster[wallet_a] = cid
            self.wallet_to_cluster[wallet_b] = cid

        # Update metrics
        target_cluster.total_co_trades += 1
        target_cluster.avg_entry_delta_seconds = round(
            0.7 * target_cluster.avg_entry_delta_seconds + 0.3 * delta_t, 3
        )
        target_cluster.jaccard_token_overlap = round(max(target_cluster.jaccard_token_overlap, jaccard), 3)
        target_cluster.updated_at = time.time()

        # Update Bayesian coordination probability
        base_prob = 0.50
        co_boost = min(0.35, target_cluster.total_co_trades * 0.05)
        sync_boost = 0.15 if target_cluster.avg_entry_delta_seconds <= 1.0 else (
            0.08 if target_cluster.avg_entry_delta_seconds <= 2.0 else 0.0
        )
        jaccard_boost = min(0.15, target_cluster.jaccard_token_overlap * 0.25)
        dev_penalty = 0.20 if (dev_wallet and (wallet_a == dev_wallet or wallet_b == dev_wallet)) else 0.0

        prob = min(0.99, base_prob + co_boost + sync_boost + jaccard_boost + dev_penalty)
        target_cluster.coordination_probability = round(prob, 3)

        # Determine Archetype
        if dev_wallet and (wallet_a == dev_wallet or wallet_b == dev_wallet):
            target_cluster.archetype = ClusterArchetype.DEPLOYER_SYBIL
        elif target_cluster.total_co_trades >= 3 and target_cluster.avg_entry_delta_seconds <= 1.5:
            target_cluster.archetype = ClusterArchetype.INSIDER_CABAL
        elif target_cluster.coordination_probability >= 0.70:
            target_cluster.archetype = ClusterArchetype.INSIDER_CABAL
        elif target_cluster.jaccard_token_overlap > 0.50:
            target_cluster.archetype = ClusterArchetype.COPY_RETAIL
        else:
            target_cluster.archetype = ClusterArchetype.UNKNOWN

        # Persist to SQLite
        if self.db:
            try:
                self.db.upsert_wallet_cluster(target_cluster)
            except Exception as e:
                logger.warning(f"Failed to persist cluster: {e}")

    def check_identity_drift(self, address: str) -> Tuple[bool, float, str]:
        """
        Calculates Kullback-Leibler divergence D_KL between rolling recent window
        and historical baseline behavior to detect operational regime shifts.
        Returns: (is_drifting, d_kl_score, explanation)
        """
        # Check if already suppressed
        now = time.time()
        if address in self.drift_suppressed_wallets:
            if now < self.drift_suppressed_wallets[address]:
                return True, 2.0, "Active identity drift suppression in effect"
            else:
                del self.drift_suppressed_wallets[address]

        history = self.wallet_trade_history.get(address, [])
        if len(history) < 8:
            return False, 0.0, "Insufficient trade sample for drift analysis"

        # Split into historical baseline (first 70%) and recent window (last 30%, min 3)
        split_idx = max(5, int(len(history) * 0.70))
        baseline = history[:split_idx]
        recent = history[split_idx:]

        # Discretize entry curve progress into 3 bins: Early (<25%), Mid (25-50%), Late (>50%)
        def get_hist(trades: List[Dict[str, float]]) -> List[float]:
            counts = [0.001, 0.001, 0.001]  # Laplace smoothing
            for t in trades:
                cp = t.get("curve_pct", 25.0)
                if cp < 25.0:
                    counts[0] += 1.0
                elif cp <= 50.0:
                    counts[1] += 1.0
                else:
                    counts[2] += 1.0
            total = sum(counts)
            return [c / total for c in counts]

        p = get_hist(baseline)  # Historical
        q = get_hist(recent)    # Recent

        # Compute D_KL(Q || P) = sum q_i * ln(q_i / p_i)
        d_kl = sum(q[i] * math.log(q[i] / p[i]) for i in range(3))
        d_kl = round(max(0.0, d_kl), 3)

        if d_kl >= 1.25:
            # Shift detected: suppress wallet reputation for 30 minutes
            self.drift_suppressed_wallets[address] = now + 1800.0
            msg = f"Behavioral regime drift detected (D_KL = {d_kl:.2f}). Early/Mid/Late entry pattern shifted significantly."
            logger.info(f"🚨 [IDENTITY DRIFT] Wallet {address[:6]}... {msg}")
            return True, d_kl, msg

        return False, d_kl, "Consistent operational pattern"

    def get_cluster(self, wallet_address: str) -> Optional[ClusterHypothesis]:
        cid = self.wallet_to_cluster.get(wallet_address)
        if cid:
            return self.clusters.get(cid)
        return None

    def get_cluster_summary(self) -> Dict[str, Any]:
        return {
            "total_clusters_discovered": len(self.clusters),
            "cabal_clusters_count": sum(1 for c in self.clusters.values() if c.archetype == ClusterArchetype.INSIDER_CABAL),
            "deployer_clusters_count": sum(1 for c in self.clusters.values() if c.archetype == ClusterArchetype.DEPLOYER_SYBIL),
            "drift_suppressed_wallets": len(self.drift_suppressed_wallets),
        }

    def reset(self):
        self.recent_mint_buys.clear()
        self.wallet_tokens.clear()
        self.wallet_trade_history.clear()
        self.clusters.clear()
        self.wallet_to_cluster.clear()
        self.drift_suppressed_wallets.clear()
