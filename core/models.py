"""
Pydantic data models for tokens, trades, wallets, positions, and learning logs.
"""
from enum import Enum
from typing import Optional, Set, Dict, Any, List, Tuple
from pydantic import BaseModel, Field
import time


class TradeType(str, Enum):
    BUY = "buy"
    SELL = "sell"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TokenMetadata(BaseModel):
    mint: str
    name: str
    symbol: str
    uri: Optional[str] = None
    dev_wallet: str
    created_at: float = Field(default_factory=time.time)
    initial_buy_sol: float = 0.0
    initial_buy_tokens: float = 0.0


class TokenActivity(BaseModel):
    mint: str
    first_seen: float = Field(default_factory=time.time)
    created_at: Optional[float] = None
    total_trades: int = 0
    dev_wallet: Optional[str] = None
    dev_dumped: bool = False
    # Rolling 5m window: List of (timestamp, sol_amount, trader_wallet)
    recent_buys: List[Tuple[float, float, str]] = Field(default_factory=list)
    recent_sells: List[Tuple[float, float, str]] = Field(default_factory=list)

    def prune_old_trades(self, window_seconds: float = 300.0, current_time: Optional[float] = None):
        now = current_time or time.time()
        cutoff = now - window_seconds
        self.recent_buys = [b for b in self.recent_buys if b[0] >= cutoff]
        self.recent_sells = [s for s in self.recent_sells if s[0] >= cutoff]

    @property
    def buy_volume_5m_sol(self) -> float:
        return sum(b[1] for b in self.recent_buys)

    @property
    def sell_volume_5m_sol(self) -> float:
        return sum(s[1] for s in self.recent_sells)

    @property
    def total_volume_5m_sol(self) -> float:
        return self.buy_volume_5m_sol + self.sell_volume_5m_sol

    @property
    def distinct_buyers_5m(self) -> int:
        return len(set(b[2] for b in self.recent_buys))

    @property
    def age_seconds(self) -> float:
        t0 = self.created_at or self.first_seen
        return max(0.0, time.time() - t0)


class TradeEvent(BaseModel):
    signature: Optional[str] = None
    mint: str
    tx_type: TradeType
    sol_amount: float
    token_amount: float
    trader_public_key: str
    timestamp: float = Field(default_factory=time.time)
    virtual_sol_reserves: Optional[int] = None
    virtual_token_reserves: Optional[int] = None
    market_cap_sol: Optional[float] = None
    bonding_curve_pct: Optional[float] = None


class WalletProfile(BaseModel):
    address: str
    first_seen: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)
    total_trades: int = 0
    closed_trades: int = 0
    profitable_trades: int = 0
    total_volume_sol: float = 0.0
    realized_pnl_sol: float = 0.0
    tokens_traded: Set[str] = Field(default_factory=set)
    persistence_score: float = 0.0
    is_burner: bool = False
    total_holding_duration_seconds: float = 0.0
    classified_style: str = "UNVERIFIED"
    # Follower Experience Tracking (Measures how profitable this wallet is when copied by OUR bot)
    bot_copied_trades: int = 0
    bot_copied_wins: int = 0
    bot_copied_pnl_sol: float = 0.0
    consecutive_copy_losses: int = 0
    is_blacklisted_for_copying: bool = False
    bayesian_reliability_score: float = 0.5

    @property
    def win_rate(self) -> float:
        if self.closed_trades == 0:
            return 0.0
        return self.profitable_trades / self.closed_trades

    @property
    def active_hours(self) -> float:
        return (self.last_seen - self.first_seen) / 3600.0

    @property
    def avg_holding_duration_seconds(self) -> float:
        if self.closed_trades == 0:
            return 0.0
        return self.total_holding_duration_seconds / self.closed_trades

    @property
    def bayesian_copy_win_rate(self) -> float:
        """Beta(2, 2) posterior probability of winning when copying this wallet."""
        return (2.0 + self.bot_copied_wins) / (4.0 + self.bot_copied_trades)


class PaperPosition(BaseModel):
    position_id: str
    mint: str
    symbol: str
    entry_timestamp: float = Field(default_factory=time.time)
    entry_sol_cost: float
    tokens_held: int  # remaining atomic token units (decimals=6)
    initial_tokens_held: int = 0  # original tokens bought at entry
    realized_sol_harvested: float = 0.0  # cumulative SOL taken off the table from partial sells
    is_moonbag: bool = False  # True once initial capital (100% SOL) is fully de-risked and paid back
    moonbag_milestones_hit: List[str] = Field(default_factory=list)  # ["HALF_INITIAL_SOL", "LOCK_MOONBAG_PROFIT"]
    entry_price_sol: float
    highest_price_sol: float
    current_price_sol: float
    current_value_sol: float
    unrealized_pnl_sol: float = 0.0
    unrealized_pnl_pct: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    exit_timestamp: Optional[float] = None
    exit_sol_received: Optional[float] = None
    exit_reason: Optional[str] = None
    trigger_wallet: Optional[str] = None
    confidence_score: float = 0.5


class StrategyParameters(BaseModel):
    version: int = 1
    min_wallet_persistence_score: float = 0.40
    base_trade_sol: float = 0.10
    max_trade_sol: float = 0.40
    min_curve_pct: float = 5.0
    max_curve_pct: float = 75.0
    trailing_stop_pct: float = 0.18
    take_profit_pct: float = 0.50
    max_dev_holding_pct: float = 0.10
    confidence_scaling_enabled: bool = True
    # Autonomous Runner & Holding Horizon (Self-Tuned by Agent)
    runner_leash_pct: float = 0.28  # Trailing leash given to runners up > 40% (allows 10x/100x without choking)
    breakeven_lock_threshold_pct: float = 0.35  # Gain % where stop moves to breakeven + profit guarantee
    max_holding_seconds: int = 3600  # Dynamic holding horizon (extends automatically when momentum is healthy)
    migration_hold_enabled: bool = True  # Hold through Raydium migration when curve progress > 40%
    smart_money_decoupling_pct: float = 0.60  # Hold through smart money profit taking if volume is strong
    market_regime: str = "RUNNER_ALPHA"  # RUNNER_ALPHA, BALANCED_MOMENTUM, DEFENSIVE_SCALP
    total_policy_adaptations: int = 0
    adaptation_history: List[Dict[str, Any]] = Field(default_factory=list)
    # Anti-Dead Coin & Revival/CTO Verification
    min_volume_5m_sol: float = 0.40  # Minimum 5m volume to enter any token
    min_distinct_buyers_5m: int = 2  # Minimum distinct buyers (prevents lonely copy-trading)
    revival_age_threshold_seconds: float = 1800.0  # 30m
    revival_min_volume_5m_sol: float = 1.50  # Older/revival tokens must prove strong volume surge
    revival_min_distinct_buyers: int = 3  # Older/revival tokens must have broad community buying
    reject_dev_dumped_tokens: bool = True  # Strict immunity against tokens where dev dumped


class EpisodicLog(BaseModel):
    log_id: str
    position_id: str
    mint: str
    entry_time: float
    exit_time: float
    net_pnl_sol: float
    net_pnl_pct: float
    trigger_wallet: Optional[str] = None
    trigger_reason: str
    exit_reason: str
    curve_pct_at_entry: float
    curve_pct_at_exit: float
    outcome_category: str  # WIN, DEV_RUG, TRAILING_STOP_OUT, MOMENTUM_STALL
    lesson_learned: str
    recommended_tuning: Dict[str, Any] = Field(default_factory=dict)


# =====================================================================
# Cognitive Architecture Models (Autonomous Market Research Organism)
# =====================================================================

class TokenLifecycleState(str, Enum):
    VIRGIN_SURGE = "VIRGIN_SURGE"                  # New token or first-time expansion
    IN_POSITION = "IN_POSITION"                    # Currently held paper/live position
    THESIS_INVALIDATED = "THESIS_INVALIDATED"      # Stopped out or failed prior thesis
    DISTRIBUTION_CHURN = "DISTRIBUTION_CHURN"      # High churn/dumping, smart money exiting
    TERMINAL_RUG = "TERMINAL_RUG"                  # Dev dumped or liquidity drained
    CTO_REVIVAL = "CTO_REVIVAL"                    # Community takeover verified under new regime


class ClusterArchetype(str, Enum):
    ORGANIC_SMART = "ORGANIC_SMART"                # Decentralized alpha cluster
    INSIDER_CABAL = "INSIDER_CABAL"                # Coordinated bundle / sybil pump & dump
    MEV_SCALPER = "MEV_SCALPER"                    # Ultra-fast sub-second arbitrage / scalpers
    DEPLOYER_SYBIL = "DEPLOYER_SYBIL"              # Funder / deployer stealth proxy wallets
    COPY_RETAIL = "COPY_RETAIL"                    # Retail copy-bots and late followers
    UNKNOWN = "UNKNOWN"                            # Insufficient edge evidence


class ClusterHypothesis(BaseModel):
    cluster_id: str
    archetype: ClusterArchetype = ClusterArchetype.UNKNOWN
    coordination_probability: float = 0.50          # P(Coordinated C | Evidence E)
    member_addresses: List[str] = Field(default_factory=list)
    common_ancestor: Optional[str] = None           # Shared funding wallet if detected
    total_co_trades: int = 0
    avg_entry_delta_seconds: float = 0.0            # Inter-trade entry synchrony
    jaccard_token_overlap: float = 0.0             # Token co-occurrence similarity
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class BrainVote(BaseModel):
    brain_name: str                                # GraphBrain, FlowBrain, RunnerBrain, etc.
    score: float                                   # [0.0, 1.0] conviction score
    confidence: float                              # [0.0, 1.0] statistical certainty
    key_evidence: str                              # Human-readable causal evidence summary
    veto: bool = False                             # Non-linear hard veto flag (e.g. AdversaryBrain)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class MetaDecision(BaseModel):
    mint: str
    symbol: str = "TOKEN"
    decision: str                                  # "EXECUTE" or "PASS"
    expected_edge: float                           # E[Edge] after frictions and uncertainty
    hurdle_rate: float                             # Dynamic hurdle threshold for current regime
    regime: str                                    # ORGANIC_MOMENTUM, CABAL_PREDATORY, etc.
    brain_votes: Dict[str, BrainVote] = Field(default_factory=dict)
    veto_active: bool = False
    veto_source: Optional[str] = None
    dominant_reason: str = ""
    suggested_size_sol: float = 0.0
    thesis: str = ""
    timestamp: float = Field(default_factory=time.time)


class CounterfactualRecord(BaseModel):
    cf_id: str
    mint: str
    symbol: str
    evaluation_time: float = Field(default_factory=time.time)
    decision: str                                  # PASS, VETO, BUY_ATTEMPT
    dominant_reason: str
    expected_edge: float
    initial_price_sol: float
    initial_curve_pct: float
    peak_price_sol: float = 0.0
    final_price_sol: float = 0.0
    peak_multiplier: float = 1.0
    final_return_pct: float = 0.0
    counterfactual_outcome: str = "PENDING"        # CONFIRMED_RUG_DODGE, FALSE_NEGATIVE_RUNNER, etc.
    status: str = "TRACKING"                       # TRACKING, RESOLVED
    last_updated: float = Field(default_factory=time.time)
    brain_scores_json: str = "{}"


class DiscoveredHypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    predicates_json: str                           # Serialized conditions (e.g. buyer_entropy > 0.8)
    target_outcome: str                            # e.g. "RUNNER_GE_20X" or "AVOID_RUG"
    lift: float = 1.0
    confidence: float = 0.5
    sample_size: int = 0
    status: str = "HYPOTHESIZED"                   # HYPOTHESIZED, VALIDATING, CONFIRMED, REJECTED, ACTIVE
    p_value: float = 1.0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

