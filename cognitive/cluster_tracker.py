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
        # Pairwise multi-token co-entry tracker: (wallet_a, wallet_b) -> set of mints co-traded <= 2.5s
        self.pairwise_co_mints: Dict[Tuple[str, str], Set[str]] = {}
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
            persisted = self.db.get_all_clusters(limit=200)
            for c in persisted:
                # Discard legacy corrupted giant percolation clusters (> 8 members)
                if len(c.member_addresses) > 8:
                    continue
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

        # Detect temporal co-entry with other wallets within 2.5 seconds
        for prev_ts, prev_buyer, prev_size in self.recent_mint_buys[mint]:
            if prev_buyer == buyer:
                continue

            delta_t = abs(ts - prev_ts)
            if delta_t <= 2.5:  # Coordinated entry within 2.5s
                pair_key = tuple(sorted([buyer, prev_buyer]))
                if pair_key not in self.pairwise_co_mints:
                    self.pairwise_co_mints[pair_key] = set()
                self.pairwise_co_mints[pair_key].add(mint)

                # Gating condition to prevent percolation snowball:
                # Wallets are ONLY clustered if:
                # 1. Directly linked to the dev_wallet (deployer sybil), OR
                # 2. They have co-entered within 2.5s across at least 2 distinct tokens, OR
                # 3. They have high Jaccard token overlap (>= 0.35) with at least 2 common tokens
                is_dev_link = dev_wallet and (buyer == dev_wallet or prev_buyer == dev_wallet)
                tokens_a = self.wallet_tokens.get(buyer, set())
                tokens_b = self.wallet_tokens.get(prev_buyer, set())
                shared_tokens = len(tokens_a.intersection(tokens_b))
                is_repeat_synchrony = len(self.pairwise_co_mints[pair_key]) >= 2
                is_high_jaccard = (shared_tokens >= 2) and (shared_tokens / max(1, len(tokens_a.union(tokens_b))) >= 0.35)

                if is_dev_link or is_repeat_synchrony or is_high_jaccard:
                    self._record_coordination(buyer, prev_buyer, delta_t, dev_wallet)

        self.recent_mint_buys[mint].append((ts, buyer, trade.sol_amount))

    def _record_coordination(
        self,
        wallet_a: str,
        wallet_b: str,
        delta_t: float,
        dev_wallet: Optional[str] = None
    ):
        """Merges or creates a cluster between wallet_a and wallet_b with percolation safeguards."""
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
                # Cap cluster size at 8 wallets to reflect real Jito bundle limits and prevent percolation
                if len(target_cluster.member_addresses) < 8:
                    target_cluster.member_addresses.append(wallet_b)
                    self.wallet_to_cluster[wallet_b] = cluster_id_a
        elif cluster_id_b and cluster_id_b in self.clusters:
            target_cluster = self.clusters[cluster_id_b]
            if wallet_a not in target_cluster.member_addresses:
                if len(target_cluster.member_addresses) < 8:
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

        if not target_cluster:
            return

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

        # Determine Archetype: Real insider cabals are small syndicates (<= 8 wallets)
        if dev_wallet and (wallet_a == dev_wallet or wallet_b == dev_wallet):
            target_cluster.archetype = ClusterArchetype.DEPLOYER_SYBIL
        elif len(target_cluster.member_addresses) <= 8 and (
            (target_cluster.total_co_trades >= 3 and target_cluster.avg_entry_delta_seconds <= 1.5)
            or target_cluster.coordination_probability >= 0.70
        ):
            target_cluster.archetype = ClusterArchetype.INSIDER_CABAL
        elif len(target_cluster.member_addresses) > 8:
            target_cluster.archetype = ClusterArchetype.COPY_RETAIL
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
        cabal_count = sum(
            1 for c in self.clusters.values()
            if c.archetype == ClusterArchetype.INSIDER_CABAL and len(c.member_addresses) <= 8
        )
        return {
            "total_clusters_discovered": len(self.clusters),
            "cabal_clusters_count": cabal_count,
            "deployer_clusters_count": sum(1 for c in self.clusters.values() if c.archetype == ClusterArchetype.DEPLOYER_SYBIL),
            "drift_suppressed_wallets": len(self.drift_suppressed_wallets),
        }

    def prune_memory_caches(self, max_wallets: int = 400, max_pairs: int = 600):
        """
        Prunes in-memory tracking caches to prevent unbounded RAM growth.
        Ensures cluster graph and wallet histories remain strictly bounded.
        """
        now = time.time()
        # 1. Prune expired drift suppressions
        expired_drifts = [w for w, exp in self.drift_suppressed_wallets.items() if now >= exp]
        for w in expired_drifts:
            self.drift_suppressed_wallets.pop(w, None)

        # 2. Prune recent_mint_buys older than 300s or empty
        cutoff = now - 300.0
        mints_to_delete = []
        for mint, buys in list(self.recent_mint_buys.items()):
            valid_buys = [b for b in buys if b[0] >= cutoff]
            if not valid_buys:
                mints_to_delete.append(mint)
            else:
                self.recent_mint_buys[mint] = valid_buys
        for m in mints_to_delete:
            self.recent_mint_buys.pop(m, None)

        if len(self.recent_mint_buys) > 150:
            sorted_mints = sorted(
                self.recent_mint_buys.items(),
                key=lambda x: max((b[0] for b in x[1]), default=0.0),
                reverse=True,
            )
            self.recent_mint_buys = dict(sorted_mints[:150])

        # 3. Prune wallet_trade_history
        if len(self.wallet_trade_history) > max_wallets:
            sorted_hist = sorted(
                self.wallet_trade_history.items(),
                key=lambda x: x[1][-1]["timestamp"] if x[1] else 0.0,
                reverse=True,
            )
            self.wallet_trade_history = dict(sorted_hist[:max_wallets])

        # 4. Prune wallet_tokens
        if len(self.wallet_tokens) > max_wallets:
            active_set = set(self.wallet_trade_history.keys())
            kept_tokens = {}
            for w in active_set:
                if w in self.wallet_tokens:
                    kept_tokens[w] = self.wallet_tokens[w]
            if len(kept_tokens) < max_wallets:
                remainder = [
                    (w, toks) for w, toks in self.wallet_tokens.items()
                    if w not in kept_tokens
                ]
                remainder.sort(key=lambda x: len(x[1]), reverse=True)
                for w, toks in remainder[: (max_wallets - len(kept_tokens))]:
                    kept_tokens[w] = toks
            self.wallet_tokens = kept_tokens

        # 5. Prune pairwise_co_mints
        if len(self.pairwise_co_mints) > max_pairs:
            sorted_pairs = sorted(
                self.pairwise_co_mints.items(),
                key=lambda x: len(x[1]),
                reverse=True,
            )
            self.pairwise_co_mints = dict(sorted_pairs[:max_pairs])

    def reset(self):
        self.recent_mint_buys.clear()
        self.wallet_tokens.clear()
        self.wallet_trade_history.clear()
        self.pairwise_co_mints.clear()
        self.clusters.clear()
        self.wallet_to_cluster.clear()
        self.drift_suppressed_wallets.clear()
