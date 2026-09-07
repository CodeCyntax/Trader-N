"""
Smart Wallet Tracker & Persistence Profiler.
Distinguishes real, consistently profitable traders from one-off dev burners and sniper sybils.
"""
import time
import math
from typing import Dict, Optional, Tuple, Set
from collections import defaultdict
from core.models import WalletProfile, TradeEvent, TradeType
from core.constants import (
    MIN_WALLET_TRADES_FOR_EVAL,
    MIN_DISTINCT_TOKENS_TRADED,
    MIN_WALLET_ACTIVE_HOURS,
    MIN_WIN_RATE_THRESHOLD,
    MIN_PERSISTENCE_SCORE,
)
from memory.database import DatabaseManager


class WalletTracker:
    """
    Maintains real-time profiles of on-chain wallets, calculating PnL,
    trading consistency, and persistence scores.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        # In-memory fast cache of active wallets: address -> WalletProfile
        self.wallets: Dict[str, WalletProfile] = {}
        # Track active holdings per wallet for PnL and duration: (address, mint) -> {"tokens": float, "sol_spent": float, "first_buy_time": float}
        self.wallet_holdings: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
            lambda: {"tokens": 0.0, "sol_spent": 0.0, "first_buy_time": 0.0}
        )
        # Track dev addresses to flag insider clustering
        self.known_devs: Set[str] = set()

    def register_dev(self, dev_wallet: str):
        """Records a token creator to screen against dev-linked insider wallets."""
        if dev_wallet:
            self.known_devs.add(dev_wallet)

    def process_trade(self, trade: TradeEvent) -> Optional[WalletProfile]:
        """
        Processes a live trade event, updates the wallet's track record,
        evaluates persistence, and saves to database.
        """
        addr = trade.trader_public_key
        now = trade.timestamp or time.time()

        # Load existing profile from memory or DB
        if addr not in self.wallets:
            existing = self.db.get_wallet(addr)
            if existing:
                self.wallets[addr] = existing
            else:
                self.wallets[addr] = WalletProfile(
                    address=addr,
                    first_seen=now,
                    last_seen=now,
                    tokens_traded=set()
                )

        profile = self.wallets[addr]
        profile.last_seen = now
        profile.total_trades += 1
        profile.total_volume_sol += trade.sol_amount
        profile.tokens_traded.add(trade.mint)

        holding_key = (addr, trade.mint)
        holding = self.wallet_holdings[holding_key]

        if trade.tx_type == TradeType.BUY:
            # Record first buy time for holding duration calculation
            if holding["tokens"] <= 0.0:
                holding["first_buy_time"] = now
            holding["tokens"] += trade.token_amount
            holding["sol_spent"] += trade.sol_amount
        elif trade.tx_type == TradeType.SELL:
            profile.closed_trades += 1
            sol_received = trade.sol_amount
            tokens_sold = trade.token_amount

            if holding["tokens"] > 0 and holding["sol_spent"] > 0:
                # Accumulate holding duration
                if holding["first_buy_time"] > 0:
                    hold_duration = max(0.0, now - holding["first_buy_time"])
                    profile.total_holding_duration_seconds += hold_duration

                # Fraction of position sold
                sell_ratio = min(1.0, tokens_sold / holding["tokens"]) if holding["tokens"] > 0 else 1.0
                cost_basis = holding["sol_spent"] * sell_ratio
                trade_pnl = sol_received - cost_basis

                profile.realized_pnl_sol += trade_pnl
                if trade_pnl > 0.005:  # meaningful net profit after fees
                    profile.profitable_trades += 1

                # Update remaining holding
                holding["tokens"] = max(0.0, holding["tokens"] - tokens_sold)
                holding["sol_spent"] = max(0.0, holding["sol_spent"] - cost_basis)
            else:
                # Sold without recorded prior buy in our session (pre-mined dev or untracked buy)
                # Strictly record as untracked liquidation without inflating profitable_trades or fake PnL
                pass

        # Calculate updated Persistence & Sybil scores
        self._evaluate_wallet_persistence(profile)

        # Persist periodically or when reaching evaluation milestone
        if profile.total_trades % 2 == 0 or profile.persistence_score > 0.3:
            self.db.upsert_wallet(profile)

        return profile

    def _evaluate_wallet_persistence(self, profile: WalletProfile):
        """
        Computes persistence score (0.0 to 1.0) and flags one-off burners.
        Penalizes:
        - Wallets with only 1 token (dev throwaway or lucky sniper)
        - Wallets active for less than minimum hours
        - Wallets with negative PnL or low win-rate
        - Known dev addresses
        - Ultra-fast scalpers (avg hold < 20s)
        """
        tokens_count = len(profile.tokens_traded)
        active_hours = profile.active_hours
        total_trades = profile.total_trades
        win_rate = profile.win_rate
        pnl = profile.realized_pnl_sol
        avg_hold = profile.avg_holding_duration_seconds

        # Check if it is a known dev or single-token throwaway
        if profile.address in self.known_devs:
            profile.is_burner = True
            profile.persistence_score = 0.0
            profile.classified_style = "KNOWN_DEV_DISQUALIFIED"
            return

        # Throwaway detector: High trades but only on 1 token, or 1 lucky trade and vanished
        if tokens_count < 2 and total_trades >= 3:
            profile.is_burner = True
            profile.persistence_score = 0.02
            profile.classified_style = "SINGLE_TOKEN_BURNER"
            return

        # MEV / High-Frequency Bot filter:
        # Genuine 10x/100x alpha hunters do not trade > 60 times per hour or execute 80+ trades in < 1 hour
        trades_per_hour = total_trades / max(0.05, active_hours)
        if trades_per_hour > 60 or (total_trades > 80 and active_hours < 1.5):
            profile.is_burner = True
            profile.persistence_score = 0.01
            profile.classified_style = "MEV_BOT_DISQUALIFIED"
            return

        # Ultra-Fast Scalper Filter (Holding time < 20s across multiple closed trades)
        if profile.closed_trades >= 3 and avg_hold > 0 and avg_hold < 20.0:
            profile.is_burner = True
            profile.persistence_score = 0.05
            profile.classified_style = "SCALPER_DISQUALIFIED"
            return

        # Minimum sample size: Must have at least 3 completed closed roundtrips
        if profile.closed_trades < 3 or total_trades < 4:
            profile.persistence_score = 0.12
            profile.is_burner = False
            profile.classified_style = "EVALUATING"
            return

        if win_rate < 0.45 or pnl <= 0.0:
            profile.persistence_score = 0.0
            profile.is_burner = False
            profile.classified_style = "UNPROFITABLE"
            return

        # Advanced Quantitative Scoring: Prioritizing Win Rate, Realized PnL, Breadth & Holding Style
        # 1. Win Rate Factor (35% weight): High accuracy (65% - 100%)
        w_factor = max(0.0, (win_rate - 0.40) / 0.60) ** 1.3

        # 2. Profit & Hunter Factor (35% weight): Real SOL captured
        p_factor = math.tanh(max(0.0, pnl) / 2.5)

        # 3. Consistency & Breadth Factor (20% weight): Multi-token breadth and closed roundtrips
        c_factor = min(1.0, profile.closed_trades / 4.0) * min(1.0, tokens_count / 3.0)

        # 4. Holding Style Factor (10% weight): Rewards alpha swing hunters (avg holding > 60s)
        h_factor = min(1.0, max(0.2, avg_hold / 300.0))

        composite_score = (0.35 * w_factor) + (0.35 * p_factor) + (0.20 * c_factor) + (0.10 * h_factor)
        profile.persistence_score = round(min(1.0, max(0.0, composite_score)), 4)
        profile.is_burner = False
        profile.classified_style = "ALPHA_SWING_HUNTER" if avg_hold >= 60.0 else "QUALIFIED_HUNTER"

    def is_smart_wallet(self, address: str) -> Tuple[bool, float]:
        """
        Returns (is_smart, score).
        True if the wallet has proven consistency, high win rate, non-dust volume,
        and passes anti-burner filters.
        """
        profile = self.wallets.get(address)
        if not profile:
            profile = self.db.get_wallet(address)
            if profile:
                self.wallets[address] = profile

        if not profile or profile.is_burner or profile.is_blacklisted_for_copying:
            return False, 0.0

        is_smart = (
            profile.persistence_score >= MIN_PERSISTENCE_SCORE
            and profile.closed_trades >= 3
            and profile.win_rate >= MIN_WIN_RATE_THRESHOLD
            and profile.realized_pnl_sol > 0.15
            and len(profile.tokens_traded) >= 2
            and profile.total_volume_sol >= 0.50
            and (profile.closed_trades < 3 or profile.avg_holding_duration_seconds >= 20.0)
            and profile.bayesian_reliability_score >= 0.20
        )
        return is_smart, profile.persistence_score

    def record_copy_trade_outcome(self, address: str, pnl_sol: float):
        """
        Follower Experience Feedback Loop:
        Records whether copying this wallet produced a profit or a loss for OUR bot.
        Updates Beta(2, 6) Bayesian reliability score.
        Blacklists toxic leader wallets that cause repeat losses.
        """
        if not address:
            return

        profile = self.wallets.get(address)
        if not profile:
            profile = self.db.get_wallet(address)
            if profile:
                self.wallets[address] = profile

        if not profile:
            return

        profile.bot_copied_trades += 1
        profile.bot_copied_pnl_sol += pnl_sol

        if pnl_sol > 0.0:
            profile.bot_copied_wins += 1
            profile.consecutive_copy_losses = 0
        else:
            profile.consecutive_copy_losses += 1

        # Skeptical Empirical Bayes Prior Beta(2, 6)
        profile.bayesian_reliability_score = (2.0 + profile.bot_copied_wins) / (8.0 + profile.bot_copied_trades)

        # Dynamic Blacklist for toxic wallets: 2 consecutive losses or negative copy PnL
        if profile.consecutive_copy_losses >= 2 or profile.bot_copied_pnl_sol < -0.05:
            profile.is_blacklisted_for_copying = True

        self.db.upsert_wallet(profile)

    def reset(self):
        """Clears all in-memory wallet caches and active holdings."""
        self.wallets.clear()
        self.wallet_holdings.clear()
        self.known_devs.clear()

