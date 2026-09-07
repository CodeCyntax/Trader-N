"""
SQLite database management with WAL mode for fast concurrent persistence.
Stores wallets, trades, paper positions, portfolio balance, and episodic learnings.
"""
import sqlite3
import json
import time
from contextlib import contextmanager
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from core.constants import DB_PATH
from core.models import (
    WalletProfile, PaperPosition, StrategyParameters, EpisodicLog, PositionStatus,
    ClusterHypothesis, CounterfactualRecord, DiscoveredHypothesis
)


class DatabaseManager:
    """Handles thread-safe, persistent SQLite operations for Trader-N."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        """Creates tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Account & Portfolio Balance
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                sol_balance REAL NOT NULL,
                total_deposited REAL NOT NULL,
                total_withdrawn REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            # Default initial balance: 10.0 SOL if table is empty
            cursor.execute("""
            INSERT OR IGNORE INTO portfolio (id, sol_balance, total_deposited, total_withdrawn, updated_at)
            VALUES (1, 10.0, 10.0, 0.0, ?);
            """, (time.time(),))

            # Smart Wallets Registry
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                address TEXT PRIMARY KEY,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                total_trades INTEGER NOT NULL DEFAULT 0,
                closed_trades INTEGER NOT NULL DEFAULT 0,
                profitable_trades INTEGER NOT NULL DEFAULT 0,
                total_volume_sol REAL NOT NULL DEFAULT 0.0,
                realized_pnl_sol REAL NOT NULL DEFAULT 0.0,
                tokens_traded_count INTEGER NOT NULL DEFAULT 0,
                persistence_score REAL NOT NULL DEFAULT 0.0,
                is_burner INTEGER NOT NULL DEFAULT 0
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_score ON wallets (persistence_score DESC);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_trades ON wallets (total_trades DESC);")

            # Wallet to Token mapping (for sybil/multi-token validation)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_tokens (
                wallet_address TEXT NOT NULL,
                mint TEXT NOT NULL,
                first_traded REAL NOT NULL,
                PRIMARY KEY (wallet_address, mint)
            );
            """)

            # Paper Trading Positions
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                position_id TEXT PRIMARY KEY,
                mint TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entry_timestamp REAL NOT NULL,
                entry_sol_cost REAL NOT NULL,
                tokens_held INTEGER NOT NULL,
                entry_price_sol REAL NOT NULL,
                highest_price_sol REAL NOT NULL,
                current_price_sol REAL NOT NULL,
                current_value_sol REAL NOT NULL,
                unrealized_pnl_sol REAL NOT NULL DEFAULT 0.0,
                unrealized_pnl_pct REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL,
                exit_timestamp REAL,
                exit_sol_received REAL,
                exit_reason TEXT,
                trigger_wallet TEXT,
                confidence_score REAL NOT NULL
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_position_status ON paper_positions (status);")

            # Episodic Memory & Learning Logs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodic_learnings (
                log_id TEXT PRIMARY KEY,
                position_id TEXT NOT NULL,
                mint TEXT NOT NULL,
                entry_time REAL NOT NULL,
                exit_time REAL NOT NULL,
                net_pnl_sol REAL NOT NULL,
                net_pnl_pct REAL NOT NULL,
                trigger_wallet TEXT,
                trigger_reason TEXT NOT NULL,
                exit_reason TEXT NOT NULL,
                curve_pct_at_entry REAL NOT NULL,
                curve_pct_at_exit REAL NOT NULL,
                outcome_category TEXT NOT NULL,
                lesson_learned TEXT NOT NULL,
                tuning_json TEXT NOT NULL
            );
            """)

            # Strategy Parameters State
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                params_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            # Online ML Model State
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_model_state (
                model_name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                weights_json TEXT NOT NULL,
                bias REAL NOT NULL,
                grad_accum_json TEXT NOT NULL,
                rolling_brier REAL NOT NULL,
                total_samples INTEGER NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            default_params = StrategyParameters().model_dump_json()
            cursor.execute("""
            INSERT OR IGNORE INTO strategy_state (id, version, params_json, updated_at)
            VALUES (1, 1, ?, ?);
            """, (default_params, time.time()))

            # Wallet Clusters (Probabilistic Sybil / Cabal Graph)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_clusters (
                cluster_id TEXT PRIMARY KEY,
                archetype TEXT NOT NULL,
                coordination_probability REAL NOT NULL,
                member_addresses_json TEXT NOT NULL,
                common_ancestor TEXT,
                total_co_trades INTEGER NOT NULL DEFAULT 0,
                avg_entry_delta_seconds REAL NOT NULL DEFAULT 0.0,
                jaccard_token_overlap REAL NOT NULL DEFAULT 0.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_prob ON wallet_clusters (coordination_probability DESC);")

            # Token Lifecycle & Thesis Memory (Anti-Re-entry Death Loops)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_lifecycle_memory (
                mint TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                trade_count INTEGER NOT NULL DEFAULT 0,
                last_entry_thesis TEXT,
                last_invalidation_reason TEXT,
                failure_signatures_json TEXT NOT NULL DEFAULT '[]',
                cooldown_until REAL NOT NULL DEFAULT 0.0,
                updated_at REAL NOT NULL
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_state ON token_lifecycle_memory (lifecycle_state);")

            # Counterfactual Shadow Ledger (60m Outcome Tracking for Non-Trades)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS counterfactual_ledger (
                cf_id TEXT PRIMARY KEY,
                mint TEXT NOT NULL,
                symbol TEXT NOT NULL,
                evaluation_time REAL NOT NULL,
                decision TEXT NOT NULL,
                dominant_reason TEXT NOT NULL,
                expected_edge REAL NOT NULL,
                initial_price_sol REAL NOT NULL,
                initial_curve_pct REAL NOT NULL,
                peak_price_sol REAL NOT NULL DEFAULT 0.0,
                final_price_sol REAL NOT NULL DEFAULT 0.0,
                peak_multiplier REAL NOT NULL DEFAULT 1.0,
                final_return_pct REAL NOT NULL DEFAULT 0.0,
                counterfactual_outcome TEXT NOT NULL DEFAULT 'PENDING',
                status TEXT NOT NULL DEFAULT 'TRACKING',
                last_updated REAL NOT NULL,
                brain_scores_json TEXT NOT NULL DEFAULT '{}'
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cf_status ON counterfactual_ledger (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cf_mint ON counterfactual_ledger (mint);")

            # Discovered Hypotheses (Autonomous Offline Pattern Discovery)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS discovered_hypotheses (
                hypothesis_id TEXT PRIMARY KEY,
                statement TEXT NOT NULL,
                predicates_json TEXT NOT NULL,
                target_outcome TEXT NOT NULL,
                lift REAL NOT NULL DEFAULT 1.0,
                confidence REAL NOT NULL DEFAULT 0.5,
                sample_size INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'HYPOTHESIZED',
                p_value REAL NOT NULL DEFAULT 1.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hypo_status ON discovered_hypotheses (status);")

            # Dynamic migrations for wallets table
            wallet_cols = [r[1] for r in cursor.execute("PRAGMA table_info(wallets);").fetchall()]
            if "bot_copied_trades" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN bot_copied_trades INTEGER DEFAULT 0;")
            if "bot_copied_wins" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN bot_copied_wins INTEGER DEFAULT 0;")
            if "bot_copied_pnl_sol" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN bot_copied_pnl_sol REAL DEFAULT 0.0;")
            if "consecutive_copy_losses" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN consecutive_copy_losses INTEGER DEFAULT 0;")
            if "is_blacklisted_for_copying" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN is_blacklisted_for_copying INTEGER DEFAULT 0;")
            if "bayesian_reliability_score" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN bayesian_reliability_score REAL DEFAULT 0.5;")
            if "total_holding_duration_seconds" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN total_holding_duration_seconds REAL DEFAULT 0.0;")
            if "classified_style" not in wallet_cols:
                cursor.execute("ALTER TABLE wallets ADD COLUMN classified_style TEXT DEFAULT 'UNVERIFIED';")

            # Dynamic migrations for paper_positions table
            pos_cols = [r[1] for r in cursor.execute("PRAGMA table_info(paper_positions);").fetchall()]
            if "initial_tokens_held" not in pos_cols:
                cursor.execute("ALTER TABLE paper_positions ADD COLUMN initial_tokens_held INTEGER DEFAULT 0;")
            if "realized_sol_harvested" not in pos_cols:
                cursor.execute("ALTER TABLE paper_positions ADD COLUMN realized_sol_harvested REAL DEFAULT 0.0;")
            if "is_moonbag" not in pos_cols:
                cursor.execute("ALTER TABLE paper_positions ADD COLUMN is_moonbag INTEGER DEFAULT 0;")
            if "moonbag_milestones_json" not in pos_cols:
                cursor.execute("ALTER TABLE paper_positions ADD COLUMN moonbag_milestones_json TEXT DEFAULT '[]';")

            conn.commit()

    # --- Portfolio Balance & Capital Operations ---

    def get_balance(self) -> float:
        with self.get_connection() as conn:
            row = conn.execute("SELECT sol_balance FROM portfolio WHERE id = 1").fetchone()
            return float(row["sol_balance"]) if row else 10.0

    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE portfolio
            SET sol_balance = sol_balance + ?,
                total_deposited = total_deposited + ?,
                updated_at = ?
            WHERE id = 1
            """, (amount, amount, time.time()))
            conn.commit()
            return self.get_balance()

    def withdraw(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Withdraw amount must be positive")
        current_bal = self.get_balance()
        if amount > current_bal:
            raise ValueError(f"Insufficient funds: available {current_bal:.4f} SOL, requested {amount:.4f} SOL")
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE portfolio
            SET sol_balance = sol_balance - ?,
                total_withdrawn = total_withdrawn + ?,
                updated_at = ?
            WHERE id = 1
            """, (amount, amount, time.time()))
            conn.commit()
            return self.get_balance()

    def adjust_balance_for_trade(self, delta_sol: float):
        """Adds (positive) or deducts (negative) SOL from available paper balance."""
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE portfolio
            SET sol_balance = sol_balance + ?,
                updated_at = ?
            WHERE id = 1
            """, (delta_sol, time.time()))
            conn.commit()

    def reset_portfolio_balance(self, new_balance: float = 10.0) -> float:
        """Sets portfolio balance directly, preserving deposit/withdrawal history."""
        if new_balance < 0:
            raise ValueError("Balance cannot be negative")
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE portfolio
            SET sol_balance = ?,
                updated_at = ?
            WHERE id = 1
            """, (new_balance, time.time()))
            conn.commit()
            return new_balance

    def hard_reset_all_data(self, default_balance: float = 10.0) -> float:
        """
        Complete database factory reset:
        Wipes all positions, wallets, tokens, episodic learnings, and online ML model states.
        Resets portfolio to default_balance and strategy_state back to version 1 with default parameters.
        """
        if default_balance < 0:
            default_balance = 10.0
        now = time.time()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM paper_positions;")
            cursor.execute("DELETE FROM wallets;")
            cursor.execute("DELETE FROM wallet_tokens;")
            cursor.execute("DELETE FROM episodic_learnings;")
            cursor.execute("DELETE FROM wallet_clusters;")
            cursor.execute("DELETE FROM token_lifecycle_memory;")
            cursor.execute("DELETE FROM counterfactual_ledger;")
            cursor.execute("DELETE FROM discovered_hypotheses;")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_model_state (
                model_name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                weights_json TEXT NOT NULL,
                bias REAL NOT NULL,
                grad_accum_json TEXT NOT NULL,
                rolling_brier REAL NOT NULL,
                total_samples INTEGER NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            cursor.execute("DELETE FROM online_model_state;")
            cursor.execute("""
            UPDATE portfolio
            SET sol_balance = ?, total_deposited = ?, total_withdrawn = 0.0, updated_at = ?
            WHERE id = 1;
            """, (default_balance, default_balance, now))
            default_params = StrategyParameters().model_dump_json()
            cursor.execute("""
            UPDATE strategy_state
            SET version = 1, params_json = ?, updated_at = ?
            WHERE id = 1;
            """, (default_params, now))
            conn.commit()
            return default_balance

    # --- Smart Wallet Profiling Persistence ---

    def upsert_wallet(self, profile: WalletProfile):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            tokens_count = len(profile.tokens_traded)
            cursor.execute("""
            INSERT INTO wallets (
                address, first_seen, last_seen, total_trades, closed_trades, profitable_trades,
                total_volume_sol, realized_pnl_sol, tokens_traded_count, persistence_score, is_burner,
                bot_copied_trades, bot_copied_wins, bot_copied_pnl_sol, consecutive_copy_losses,
                is_blacklisted_for_copying, bayesian_reliability_score, total_holding_duration_seconds,
                classified_style
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                last_seen = excluded.last_seen,
                total_trades = excluded.total_trades,
                closed_trades = excluded.closed_trades,
                profitable_trades = excluded.profitable_trades,
                total_volume_sol = excluded.total_volume_sol,
                realized_pnl_sol = excluded.realized_pnl_sol,
                tokens_traded_count = excluded.tokens_traded_count,
                persistence_score = excluded.persistence_score,
                is_burner = excluded.is_burner,
                bot_copied_trades = excluded.bot_copied_trades,
                bot_copied_wins = excluded.bot_copied_wins,
                bot_copied_pnl_sol = excluded.bot_copied_pnl_sol,
                consecutive_copy_losses = excluded.consecutive_copy_losses,
                is_blacklisted_for_copying = excluded.is_blacklisted_for_copying,
                bayesian_reliability_score = excluded.bayesian_reliability_score,
                total_holding_duration_seconds = excluded.total_holding_duration_seconds,
                classified_style = excluded.classified_style;
            """, (
                profile.address,
                profile.first_seen,
                profile.last_seen,
                profile.total_trades,
                profile.closed_trades,
                profile.profitable_trades,
                profile.total_volume_sol,
                profile.realized_pnl_sol,
                tokens_count,
                profile.persistence_score,
                1 if profile.is_burner else 0,
                profile.bot_copied_trades,
                profile.bot_copied_wins,
                profile.bot_copied_pnl_sol,
                profile.consecutive_copy_losses,
                1 if profile.is_blacklisted_for_copying else 0,
                profile.bayesian_reliability_score,
                profile.total_holding_duration_seconds,
                profile.classified_style
            ))

            for mint in profile.tokens_traded:
                cursor.execute("""
                INSERT OR IGNORE INTO wallet_tokens (wallet_address, mint, first_traded)
                VALUES (?, ?, ?);
                """, (profile.address, mint, profile.last_seen))

            conn.commit()

    def get_wallet(self, address: str) -> Optional[WalletProfile]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM wallets WHERE address = ?", (address,)).fetchone()
            if not row:
                return None
            tokens_rows = conn.execute("SELECT mint FROM wallet_tokens WHERE wallet_address = ?", (address,)).fetchall()
            tokens = {r["mint"] for r in tokens_rows}
            return WalletProfile(
                address=row["address"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                total_trades=row["total_trades"],
                closed_trades=row["closed_trades"] if "closed_trades" in row.keys() else 0,
                profitable_trades=row["profitable_trades"],
                total_volume_sol=row["total_volume_sol"],
                realized_pnl_sol=row["realized_pnl_sol"],
                tokens_traded=tokens,
                persistence_score=row["persistence_score"],
                is_burner=bool(row["is_burner"]),
                total_holding_duration_seconds=row["total_holding_duration_seconds"] if "total_holding_duration_seconds" in row.keys() else 0.0,
                classified_style=row["classified_style"] if "classified_style" in row.keys() else "UNVERIFIED",
                bot_copied_trades=row["bot_copied_trades"] if "bot_copied_trades" in row.keys() else 0,
                bot_copied_wins=row["bot_copied_wins"] if "bot_copied_wins" in row.keys() else 0,
                bot_copied_pnl_sol=row["bot_copied_pnl_sol"] if "bot_copied_pnl_sol" in row.keys() else 0.0,
                consecutive_copy_losses=row["consecutive_copy_losses"] if "consecutive_copy_losses" in row.keys() else 0,
                is_blacklisted_for_copying=bool(row["is_blacklisted_for_copying"]) if "is_blacklisted_for_copying" in row.keys() else False,
                bayesian_reliability_score=row["bayesian_reliability_score"] if "bayesian_reliability_score" in row.keys() else 0.5
            )

    def get_top_persistent_wallets(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("""
            SELECT address, total_trades, closed_trades, profitable_trades, realized_pnl_sol,
                   tokens_traded_count, persistence_score, is_burner,
                   bot_copied_trades, bot_copied_wins, bot_copied_pnl_sol, is_blacklisted_for_copying,
                   (last_seen - first_seen) / 3600.0 as active_hours
            FROM wallets
            WHERE is_burner = 0 AND closed_trades >= 3 AND profitable_trades > 0
            ORDER BY persistence_score DESC, (CAST(profitable_trades AS FLOAT) / MAX(1, closed_trades)) DESC, realized_pnl_sol DESC
            LIMIT ?;
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Paper Positions ---

    def save_position(self, pos: PaperPosition):
        with self.get_connection() as conn:
            milestones_json = json.dumps(pos.moonbag_milestones_hit)
            conn.execute("""
            INSERT OR REPLACE INTO paper_positions (
                position_id, mint, symbol, entry_timestamp, entry_sol_cost,
                tokens_held, initial_tokens_held, realized_sol_harvested, is_moonbag,
                moonbag_milestones_json, entry_price_sol, highest_price_sol, current_price_sol,
                current_value_sol, unrealized_pnl_sol, unrealized_pnl_pct, status,
                exit_timestamp, exit_sol_received, exit_reason, trigger_wallet, confidence_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                pos.position_id, pos.mint, pos.symbol, pos.entry_timestamp, pos.entry_sol_cost,
                pos.tokens_held, pos.initial_tokens_held, pos.realized_sol_harvested, 1 if pos.is_moonbag else 0,
                milestones_json, pos.entry_price_sol, pos.highest_price_sol, pos.current_price_sol,
                pos.current_value_sol, pos.unrealized_pnl_sol, pos.unrealized_pnl_pct, pos.status.value,
                pos.exit_timestamp, pos.exit_sol_received, pos.exit_reason, pos.trigger_wallet, pos.confidence_score
            ))
            conn.commit()

    def get_open_positions(self) -> List[PaperPosition]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM paper_positions WHERE status = 'open';")
            positions = []
            for r in cursor.fetchall():
                milestones = json.loads(r["moonbag_milestones_json"]) if "moonbag_milestones_json" in r.keys() and r["moonbag_milestones_json"] else []
                positions.append(PaperPosition(
                    position_id=r["position_id"],
                    mint=r["mint"],
                    symbol=r["symbol"],
                    entry_timestamp=r["entry_timestamp"],
                    entry_sol_cost=r["entry_sol_cost"],
                    tokens_held=r["tokens_held"],
                    initial_tokens_held=r["initial_tokens_held"] if "initial_tokens_held" in r.keys() else r["tokens_held"],
                    realized_sol_harvested=r["realized_sol_harvested"] if "realized_sol_harvested" in r.keys() else 0.0,
                    is_moonbag=bool(r["is_moonbag"]) if "is_moonbag" in r.keys() else False,
                    moonbag_milestones_hit=milestones,
                    entry_price_sol=r["entry_price_sol"],
                    highest_price_sol=r["highest_price_sol"],
                    current_price_sol=r["current_price_sol"],
                    current_value_sol=r["current_value_sol"],
                    unrealized_pnl_sol=r["unrealized_pnl_sol"],
                    unrealized_pnl_pct=r["unrealized_pnl_pct"],
                    status=PositionStatus(r["status"]),
                    exit_timestamp=r["exit_timestamp"],
                    exit_sol_received=r["exit_sol_received"],
                    exit_reason=r["exit_reason"],
                    trigger_wallet=r["trigger_wallet"],
                    confidence_score=r["confidence_score"]
                ))
            return positions

    def get_closed_positions(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("""
            SELECT * FROM paper_positions
            WHERE status = 'closed'
            ORDER BY exit_timestamp DESC
            LIMIT ?;
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # --- Episodic Learnings ---

    def save_episodic_log(self, log: EpisodicLog):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO episodic_learnings (
                log_id, position_id, mint, entry_time, exit_time, net_pnl_sol,
                net_pnl_pct, trigger_wallet, trigger_reason, exit_reason,
                curve_pct_at_entry, curve_pct_at_exit, outcome_category,
                lesson_learned, tuning_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                log.log_id, log.position_id, log.mint, log.entry_time, log.exit_time,
                log.net_pnl_sol, log.net_pnl_pct, log.trigger_wallet, log.trigger_reason,
                log.exit_reason, log.curve_pct_at_entry, log.curve_pct_at_exit,
                log.outcome_category, log.lesson_learned, json.dumps(log.recommended_tuning)
            ))
            conn.commit()

    def get_recent_learnings(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("""
            SELECT * FROM episodic_learnings
            ORDER BY exit_time DESC
            LIMIT ?;
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # --- Strategy Parameters ---

    def get_strategy_params(self) -> StrategyParameters:
        with self.get_connection() as conn:
            row = conn.execute("SELECT params_json FROM strategy_state WHERE id = 1;").fetchone()
            if row:
                return StrategyParameters.model_validate_json(row["params_json"])
            return StrategyParameters()

    def save_strategy_params(self, params: StrategyParameters):
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE strategy_state
            SET version = ?,
                params_json = ?,
                updated_at = ?
            WHERE id = 1;
            """, (params.version, params.model_dump_json(), time.time()))
            conn.commit()

    def get_agent_deep_dive_metrics(self) -> Dict[str, Any]:
        """
        Compiles a comprehensive analytical deep dive of the agent's trading history,
        quantified learning evolution, mistakes breakdown, Hall of Fame, and return distribution.
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT position_id, mint, symbol, entry_timestamp, entry_sol_cost,
                       tokens_held, entry_price_sol, highest_price_sol, current_price_sol,
                       current_value_sol, unrealized_pnl_sol, unrealized_pnl_pct,
                       status, exit_timestamp, exit_sol_received, exit_reason,
                       trigger_wallet, confidence_score
                FROM paper_positions
                WHERE status = 'closed'
                ORDER BY exit_timestamp DESC;
            """)
            closed = [dict(r) for r in cursor.fetchall()]

            cursor = conn.execute("""
                SELECT log_id, position_id, mint, entry_time, exit_time, net_pnl_sol,
                       net_pnl_pct, trigger_wallet, trigger_reason, exit_reason,
                       curve_pct_at_entry, curve_pct_at_exit, outcome_category,
                       lesson_learned, tuning_json
                FROM episodic_learnings
                ORDER BY exit_time DESC;
            """)
            learnings = [dict(r) for r in cursor.fetchall()]

            state_row = conn.execute("SELECT version, params_json FROM strategy_state WHERE id = 1;").fetchone()
            current_version = state_row["version"] if state_row else 1

            total_trades = len(closed)
            wins = [p for p in closed if p["unrealized_pnl_sol"] > 0]
            losses = [p for p in closed if p["unrealized_pnl_sol"] <= 0]

            gross_profit = sum(p["unrealized_pnl_sol"] for p in wins)
            gross_loss = abs(sum(p["unrealized_pnl_sol"] for p in losses))
            net_profit = gross_profit - gross_loss
            win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

            avg_win_pct = (sum(p["unrealized_pnl_pct"] for p in wins) / len(wins)) if wins else 0.0
            avg_loss_pct = (sum(p["unrealized_pnl_pct"] for p in losses) / len(losses)) if losses else 0.0
            max_win_pct = max([p["unrealized_pnl_pct"] for p in closed], default=0.0)
            max_loss_pct = min([p["unrealized_pnl_pct"] for p in closed], default=0.0)

            top_trades = sorted(wins, key=lambda x: (x["unrealized_pnl_pct"], x["unrealized_pnl_sol"]), reverse=True)[:8]
            mistakes_logs = [l for l in learnings if l["net_pnl_sol"] < 0][:10]

            category_counts = {}
            for l in learnings:
                cat = l["outcome_category"]
                category_counts[cat] = category_counts.get(cat, 0) + 1

            distribution = {
                "moonshots_100x_plus": sum(1 for p in closed if p["unrealized_pnl_pct"] >= 100.0),
                "runners_25_to_100": sum(1 for p in closed if 25.0 <= p["unrealized_pnl_pct"] < 100.0),
                "scalp_wins_5_to_25": sum(1 for p in closed if 5.0 <= p["unrealized_pnl_pct"] < 25.0),
                "scratch_wins_0_to_5": sum(1 for p in closed if 0.0 <= p["unrealized_pnl_pct"] < 5.0),
                "controlled_losses": sum(1 for p in closed if p["unrealized_pnl_pct"] < 0.0),
            }

            knowledge_score = min(100.0, round(len(learnings) * 3.5 + (current_version - 1) * 6.0, 1))
            adaptation_velocity = round((current_version / max(1.0, total_trades / 10.0)), 2)

            return {
                "total_closed_trades": total_trades,
                "wins_count": len(wins),
                "losses_count": len(losses),
                "win_rate_pct": round(win_rate, 1),
                "profit_factor": round(profit_factor, 2),
                "gross_profit_sol": round(gross_profit, 4),
                "gross_loss_sol": round(gross_loss, 4),
                "net_profit_sol": round(net_profit, 4),
                "avg_win_pct": round(avg_win_pct, 1),
                "avg_loss_pct": round(avg_loss_pct, 1),
                "max_win_pct": round(max_win_pct, 1),
                "max_loss_pct": round(max_loss_pct, 1),
                "top_trades": top_trades,
                "mistakes": mistakes_logs,
                "category_counts": category_counts,
                "distribution": distribution,
                "cognitive_evolution": {
                    "policy_version": current_version,
                    "total_autopsies_conducted": len(learnings),
                    "knowledge_score": knowledge_score,
                    "adaptation_velocity": adaptation_velocity,
                    "dev_rugs_mitigated": category_counts.get("DEV_RUG", 0),
                    "trailing_stops_locked": category_counts.get("TRAILING_STOP_PROFIT", 0),
                    "loss_cutoffs_enforced": category_counts.get("TRAILING_STOP_LOSS", 0),
                }
            }

    # =========================================================================
    # Cognitive Architecture Persistence Methods
    # =========================================================================

    # --- Probabilistic Wallet Clusters ---

    def upsert_wallet_cluster(self, cluster: ClusterHypothesis):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO wallet_clusters (
                cluster_id, archetype, coordination_probability, member_addresses_json,
                common_ancestor, total_co_trades, avg_entry_delta_seconds,
                jaccard_token_overlap, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                cluster.cluster_id,
                cluster.archetype.value if hasattr(cluster.archetype, 'value') else str(cluster.archetype),
                cluster.coordination_probability,
                json.dumps(cluster.member_addresses),
                cluster.common_ancestor,
                cluster.total_co_trades,
                cluster.avg_entry_delta_seconds,
                cluster.jaccard_token_overlap,
                cluster.created_at,
                cluster.updated_at,
            ))
            conn.commit()

    def get_wallet_cluster(self, cluster_id: str) -> Optional[ClusterHypothesis]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM wallet_clusters WHERE cluster_id = ?;", (cluster_id,)).fetchone()
            if not row:
                return None
            return ClusterHypothesis(
                cluster_id=row["cluster_id"],
                archetype=row["archetype"],
                coordination_probability=float(row["coordination_probability"]),
                member_addresses=json.loads(row["member_addresses_json"]),
                common_ancestor=row["common_ancestor"],
                total_co_trades=int(row["total_co_trades"]),
                avg_entry_delta_seconds=float(row["avg_entry_delta_seconds"]),
                jaccard_token_overlap=float(row["jaccard_token_overlap"]),
                created_at=float(row["created_at"]),
                updated_at=float(row["updated_at"]),
            )

    def get_all_clusters(self, limit: int = 50) -> List[ClusterHypothesis]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM wallet_clusters ORDER BY coordination_probability DESC, total_co_trades DESC LIMIT ?;",
                (limit,)
            ).fetchall()
            clusters = []
            for row in rows:
                clusters.append(ClusterHypothesis(
                    cluster_id=row["cluster_id"],
                    archetype=row["archetype"],
                    coordination_probability=float(row["coordination_probability"]),
                    member_addresses=json.loads(row["member_addresses_json"]),
                    common_ancestor=row["common_ancestor"],
                    total_co_trades=int(row["total_co_trades"]),
                    avg_entry_delta_seconds=float(row["avg_entry_delta_seconds"]),
                    jaccard_token_overlap=float(row["jaccard_token_overlap"]),
                    created_at=float(row["created_at"]),
                    updated_at=float(row["updated_at"]),
                ))
            return clusters

    def find_cluster_for_wallet(self, address: str) -> Optional[ClusterHypothesis]:
        """Scans clusters to see if a wallet address is a member of any known cluster."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM wallet_clusters WHERE member_addresses_json LIKE ?;", (f"%{address}%",)).fetchall()
            for row in rows:
                members = json.loads(row["member_addresses_json"])
                if address in members:
                    return ClusterHypothesis(
                        cluster_id=row["cluster_id"],
                        archetype=row["archetype"],
                        coordination_probability=float(row["coordination_probability"]),
                        member_addresses=members,
                        common_ancestor=row["common_ancestor"],
                        total_co_trades=int(row["total_co_trades"]),
                        avg_entry_delta_seconds=float(row["avg_entry_delta_seconds"]),
                        jaccard_token_overlap=float(row["jaccard_token_overlap"]),
                        created_at=float(row["created_at"]),
                        updated_at=float(row["updated_at"]),
                    )
            return None

    # --- Token Lifecycle & Thesis State Persistence ---

    def upsert_token_lifecycle(
        self,
        mint: str,
        symbol: str,
        state: str,
        trade_count: int,
        last_entry_thesis: Optional[str] = None,
        last_invalidation_reason: Optional[str] = None,
        failure_signatures: Optional[List[str]] = None,
        cooldown_until: float = 0.0,
    ):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO token_lifecycle_memory (
                mint, symbol, lifecycle_state, trade_count, last_entry_thesis,
                last_invalidation_reason, failure_signatures_json, cooldown_until, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                mint, symbol, state, trade_count, last_entry_thesis,
                last_invalidation_reason, json.dumps(failure_signatures or []),
                cooldown_until, time.time()
            ))
            conn.commit()

    def get_token_lifecycle(self, mint: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM token_lifecycle_memory WHERE mint = ?;", (mint,)).fetchone()
            if not row:
                return None
            return {
                "mint": row["mint"],
                "symbol": row["symbol"],
                "lifecycle_state": row["lifecycle_state"],
                "trade_count": int(row["trade_count"]),
                "last_entry_thesis": row["last_entry_thesis"],
                "last_invalidation_reason": row["last_invalidation_reason"],
                "failure_signatures": json.loads(row["failure_signatures_json"]),
                "cooldown_until": float(row["cooldown_until"]),
                "updated_at": float(row["updated_at"]),
            }

    # --- Counterfactual Shadow Ledger ---

    def record_counterfactual(self, cf: CounterfactualRecord):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO counterfactual_ledger (
                cf_id, mint, symbol, evaluation_time, decision, dominant_reason,
                expected_edge, initial_price_sol, initial_curve_pct, peak_price_sol,
                final_price_sol, peak_multiplier, final_return_pct, counterfactual_outcome,
                status, last_updated, brain_scores_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                cf.cf_id, cf.mint, cf.symbol, cf.evaluation_time, cf.decision,
                cf.dominant_reason, cf.expected_edge, cf.initial_price_sol,
                cf.initial_curve_pct, cf.peak_price_sol, cf.final_price_sol,
                cf.peak_multiplier, cf.final_return_pct, cf.counterfactual_outcome,
                cf.status, cf.last_updated, cf.brain_scores_json,
            ))
            conn.commit()

    def update_counterfactual_price(
        self,
        mint: str,
        current_price_sol: float,
        current_time: Optional[float] = None,
    ):
        now = current_time or time.time()
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM counterfactual_ledger WHERE mint = ? AND status = 'TRACKING';", (mint,)).fetchall()
            for r in rows:
                init_p = float(r["initial_price_sol"])
                cur_peak = max(float(r["peak_price_sol"]), current_price_sol)
                peak_mult = (cur_peak / init_p) if init_p > 0 else 1.0
                ret_pct = ((current_price_sol - init_p) / init_p * 100.0) if init_p > 0 else 0.0

                conn.execute("""
                UPDATE counterfactual_ledger
                SET peak_price_sol = ?, final_price_sol = ?, peak_multiplier = ?,
                    final_return_pct = ?, last_updated = ?
                WHERE cf_id = ?;
                """, (cur_peak, current_price_sol, round(peak_mult, 2), round(ret_pct, 2), now, r["cf_id"]))
            conn.commit()

    def get_active_counterfactuals(self) -> List[CounterfactualRecord]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM counterfactual_ledger WHERE status = 'TRACKING' ORDER BY evaluation_time DESC;").fetchall()
            records = []
            for r in rows:
                records.append(CounterfactualRecord(
                    cf_id=r["cf_id"],
                    mint=r["mint"],
                    symbol=r["symbol"],
                    evaluation_time=float(r["evaluation_time"]),
                    decision=r["decision"],
                    dominant_reason=r["dominant_reason"],
                    expected_edge=float(r["expected_edge"]),
                    initial_price_sol=float(r["initial_price_sol"]),
                    initial_curve_pct=float(r["initial_curve_pct"]),
                    peak_price_sol=float(r["peak_price_sol"]),
                    final_price_sol=float(r["final_price_sol"]),
                    peak_multiplier=float(r["peak_multiplier"]),
                    final_return_pct=float(r["final_return_pct"]),
                    counterfactual_outcome=r["counterfactual_outcome"],
                    status=r["status"],
                    last_updated=float(r["last_updated"]),
                    brain_scores_json=r["brain_scores_json"],
                ))
            return records

    def resolve_counterfactuals(self, horizon_seconds: float = 3600.0, current_time: Optional[float] = None) -> int:
        now = current_time or time.time()
        resolved_count = 0
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM counterfactual_ledger WHERE status = 'TRACKING' AND (? - evaluation_time) >= ?;",
                (now, horizon_seconds)
            ).fetchall()
            for r in rows:
                peak_m = float(r["peak_multiplier"])
                ret_p = float(r["final_return_pct"])

                if peak_m >= 10.0:
                    outcome = "FALSE_NEGATIVE_10X_RUNNER"
                elif peak_m >= 3.0:
                    outcome = "FALSE_NEGATIVE_3X_GAIN"
                elif ret_p <= -50.0:
                    outcome = "CONFIRMED_RUG_DODGE"
                else:
                    outcome = "CONFIRMED_CHOP_DODGE"

                conn.execute("""
                UPDATE counterfactual_ledger
                SET status = 'RESOLVED', counterfactual_outcome = ?, last_updated = ?
                WHERE cf_id = ?;
                """, (outcome, now, r["cf_id"]))
                resolved_count += 1
            conn.commit()
        return resolved_count

    def get_counterfactual_summary(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM counterfactual_ledger;").fetchone()[0]
            tracking = conn.execute("SELECT COUNT(*) FROM counterfactual_ledger WHERE status = 'TRACKING';").fetchone()[0]
            rug_dodges = conn.execute("SELECT COUNT(*) FROM counterfactual_ledger WHERE counterfactual_outcome = 'CONFIRMED_RUG_DODGE';").fetchone()[0]
            chop_dodges = conn.execute("SELECT COUNT(*) FROM counterfactual_ledger WHERE counterfactual_outcome = 'CONFIRMED_CHOP_DODGE';").fetchone()[0]
            missed_runners = conn.execute("SELECT COUNT(*) FROM counterfactual_ledger WHERE counterfactual_outcome LIKE 'FALSE_NEGATIVE%';").fetchone()[0]
            
            # Estimate capital preserved: each avoided rug saved base_trade_sol
            params = self.get_strategy_params()
            saved_sol = round((rug_dodges + chop_dodges) * params.base_trade_sol, 4)

            return {
                "total_counterfactuals_tracked": total,
                "currently_tracking": tracking,
                "confirmed_rug_dodges": rug_dodges,
                "confirmed_chop_dodges": chop_dodges,
                "missed_runners_count": missed_runners,
                "estimated_capital_preserved_sol": saved_sol,
            }

    def get_recent_counterfactuals(self, limit: int = 15) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT cf_id, mint, symbol, evaluation_time, decision, dominant_reason,
                       expected_edge, peak_multiplier, final_return_pct, counterfactual_outcome,
                       status, brain_scores_json
                FROM counterfactual_ledger
                ORDER BY evaluation_time DESC
                LIMIT ?;
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- Discovered Hypotheses Operations ---

    def upsert_hypothesis(self, hypo: DiscoveredHypothesis):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO discovered_hypotheses (
                hypothesis_id, statement, predicates_json, target_outcome, lift,
                confidence, sample_size, status, p_value, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                hypo.hypothesis_id, hypo.statement, hypo.predicates_json,
                hypo.target_outcome, hypo.lift, hypo.confidence,
                hypo.sample_size, hypo.status, hypo.p_value,
                hypo.created_at, hypo.updated_at,
            ))
            conn.commit()

    def get_hypotheses(self, status: Optional[str] = None, limit: int = 30) -> List[DiscoveredHypothesis]:
        with self.get_connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM discovered_hypotheses WHERE status = ? ORDER BY lift DESC, sample_size DESC LIMIT ?;",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM discovered_hypotheses ORDER BY lift DESC, sample_size DESC LIMIT ?;",
                    (limit,)
                ).fetchall()
            hypotheses = []
            for r in rows:
                hypotheses.append(DiscoveredHypothesis(
                    hypothesis_id=r["hypothesis_id"],
                    statement=r["statement"],
                    predicates_json=r["predicates_json"],
                    target_outcome=r["target_outcome"],
                    lift=float(r["lift"]),
                    confidence=float(r["confidence"]),
                    sample_size=int(r["sample_size"]),
                    status=r["status"],
                    p_value=float(r["p_value"]),
                    created_at=float(r["created_at"]),
                    updated_at=float(r["updated_at"]),
                ))
            return hypotheses

    def get_experience_counts(self) -> Dict[str, int]:
        """Returns the high-level cognitive experience metrics across all memory tiers."""
        with self.get_connection() as conn:
            wallets = conn.execute("SELECT COUNT(*) FROM wallets;").fetchone()[0]
            tokens_observed = conn.execute("SELECT COUNT(DISTINCT mint) FROM wallet_tokens;").fetchone()[0]
            clusters = conn.execute("SELECT COUNT(*) FROM wallet_clusters;").fetchone()[0]
            lifecycles = conn.execute("SELECT COUNT(*) FROM token_lifecycle_memory;").fetchone()[0]
            autopsies = conn.execute("SELECT COUNT(*) FROM episodic_learnings;").fetchone()[0]
            cf_tracked = conn.execute("SELECT COUNT(*) FROM counterfactual_ledger;").fetchone()[0]
            hypotheses_total = conn.execute("SELECT COUNT(*) FROM discovered_hypotheses;").fetchone()[0]
            hypotheses_active = conn.execute("SELECT COUNT(*) FROM discovered_hypotheses WHERE status = 'ACTIVE';").fetchone()[0]
            hypotheses_confirmed = conn.execute("SELECT COUNT(*) FROM discovered_hypotheses WHERE status = 'CONFIRMED';").fetchone()[0]

            return {
                "total_wallets_profiled": wallets,
                "total_tokens_seen": max(tokens_observed, lifecycles),
                "total_clusters_mapped": clusters,
                "total_autopsies_conducted": autopsies,
                "total_counterfactuals_tracked": cf_tracked,
                "hypotheses_discovered": hypotheses_total,
                "hypotheses_confirmed": hypotheses_confirmed,
                "hypotheses_active_edge": hypotheses_active,
            }

    # --- Analytics, Equity Curve & Data Exporter Operations ---

    def get_equity_curve_history(self, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Generates a chronological time-series of portfolio equity and cumulative realized PnL
        across all closed trades.
        """
        with self.get_connection() as conn:
            port = conn.execute("SELECT sol_balance, total_deposited FROM portfolio WHERE id = 1;").fetchone()
            init_deposit = float(port["total_deposited"]) if port else 10.0

            rows = conn.execute("""
                SELECT position_id, mint, symbol, entry_timestamp, exit_timestamp,
                       entry_sol_cost, exit_sol_received, unrealized_pnl_sol, unrealized_pnl_pct,
                       exit_reason, trigger_wallet
                FROM paper_positions
                WHERE LOWER(status) = 'closed'
                ORDER BY exit_timestamp ASC
                LIMIT ?;
            """, (limit,)).fetchall()

            if not rows:
                return [{
                    "trade_num": 0,
                    "timestamp": time.time(),
                    "symbol": "START",
                    "pnl_sol": 0.0,
                    "cum_pnl_sol": 0.0,
                    "equity_sol": init_deposit,
                }]

            points = []
            cum_pnl = 0.0
            
            # Anchor point at beginning
            first_ts = float(rows[0]["entry_timestamp"] or rows[0]["exit_timestamp"] or time.time())
            points.append({
                "trade_num": 0,
                "timestamp": first_ts - 60.0,
                "symbol": "START",
                "pnl_sol": 0.0,
                "cum_pnl_sol": 0.0,
                "equity_sol": round(init_deposit, 4),
            })

            for idx, r in enumerate(rows, start=1):
                pnl = float(r["unrealized_pnl_sol"] or 0.0)
                cum_pnl += pnl
                eq = init_deposit + cum_pnl
                points.append({
                    "trade_num": idx,
                    "timestamp": float(r["exit_timestamp"] or time.time()),
                    "symbol": r["symbol"] or "TOKEN",
                    "mint": r["mint"],
                    "pnl_sol": round(pnl, 4),
                    "cum_pnl_sol": round(cum_pnl, 4),
                    "equity_sol": round(eq, 4),
                    "exit_reason": r["exit_reason"] or "CLOSED",
                })

            return points

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Computes quantitative metrics: win rate, profit factor, average win/loss,
        max drawdown, and regime-based breakdown.
        """
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT position_id, mint, symbol, entry_sol_cost, exit_sol_received,
                       unrealized_pnl_sol, unrealized_pnl_pct, exit_reason,
                       entry_timestamp, exit_timestamp
                FROM paper_positions
                WHERE LOWER(status) = 'closed'
                ORDER BY exit_timestamp ASC;
            """).fetchall()

            total_trades = len(rows)
            if total_trades == 0:
                return {
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate_pct": 0.0,
                    "profit_factor": 1.0,
                    "net_pnl_sol": 0.0,
                    "gross_profit_sol": 0.0,
                    "gross_loss_sol": 0.0,
                    "avg_win_sol": 0.0,
                    "avg_loss_sol": 0.0,
                    "avg_win_pct": 0.0,
                    "avg_loss_pct": 0.0,
                    "max_win_pct": 0.0,
                    "max_loss_pct": 0.0,
                    "max_drawdown_sol": 0.0,
                    "max_drawdown_pct": 0.0,
                    "regimes": {},
                    "exit_reasons": {},
                }

            wins = [r for r in rows if (r["unrealized_pnl_sol"] or 0.0) > 0]
            losses = [r for r in rows if (r["unrealized_pnl_sol"] or 0.0) <= 0]

            gross_profit = sum(float(r["unrealized_pnl_sol"]) for r in wins)
            gross_loss = abs(sum(float(r["unrealized_pnl_sol"]) for r in losses))
            net_pnl = gross_profit - gross_loss

            profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)
            win_rate = round((len(wins) / total_trades) * 100.0, 1)

            avg_win_sol = round(gross_profit / len(wins), 4) if wins else 0.0
            avg_loss_sol = round(gross_loss / len(losses), 4) if losses else 0.0
            avg_win_pct = round(sum(float(r["unrealized_pnl_pct"] or 0.0) for r in wins) / len(wins), 1) if wins else 0.0
            avg_loss_pct = round(sum(float(r["unrealized_pnl_pct"] or 0.0) for r in losses) / len(losses), 1) if losses else 0.0

            max_win_pct = max([float(r["unrealized_pnl_pct"] or 0.0) for r in rows], default=0.0)
            max_loss_pct = min([float(r["unrealized_pnl_pct"] or 0.0) for r in rows], default=0.0)

            # Max Drawdown calculation
            peak = 0.0
            cum = 0.0
            max_dd_sol = 0.0
            max_dd_pct = 0.0
            for r in rows:
                cum += float(r["unrealized_pnl_sol"] or 0.0)
                if cum > peak:
                    peak = cum
                dd_sol = peak - cum
                if dd_sol > max_dd_sol:
                    max_dd_sol = dd_sol
                if peak > 0:
                    dd_pct = (dd_sol / (10.0 + peak)) * 100.0
                    if dd_pct > max_dd_pct:
                        max_dd_pct = dd_pct

            # Exit reasons breakdown
            exit_reasons = {}
            for r in rows:
                reason = r["exit_reason"] or "UNKNOWN"
                if reason not in exit_reasons:
                    exit_reasons[reason] = {"count": 0, "net_pnl_sol": 0.0}
                exit_reasons[reason]["count"] += 1
                exit_reasons[reason]["net_pnl_sol"] = round(exit_reasons[reason]["net_pnl_sol"] + float(r["unrealized_pnl_sol"] or 0.0), 4)

            return {
                "total_trades": total_trades,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": win_rate,
                "profit_factor": profit_factor,
                "net_pnl_sol": round(net_pnl, 4),
                "gross_profit_sol": round(gross_profit, 4),
                "gross_loss_sol": round(gross_loss, 4),
                "avg_win_sol": avg_win_sol,
                "avg_loss_sol": avg_loss_sol,
                "avg_win_pct": avg_win_pct,
                "avg_loss_pct": avg_loss_pct,
                "max_win_pct": round(max_win_pct, 1),
                "max_loss_pct": round(max_loss_pct, 1),
                "max_drawdown_sol": round(max_dd_sol, 4),
                "max_drawdown_pct": round(max_dd_pct, 1),
                "exit_reasons": exit_reasons,
            }

    def export_all_trades_rows(self) -> List[Dict[str, Any]]:
        """Returns every closed and active trade formatted for CSV/JSON export."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT position_id, mint, symbol, status, entry_timestamp, exit_timestamp,
                       entry_sol_cost, exit_sol_received, entry_price_sol, current_price_sol,
                       unrealized_pnl_sol, unrealized_pnl_pct, exit_reason, trigger_wallet,
                       confidence_score
                FROM paper_positions
                ORDER BY entry_timestamp DESC;
            """).fetchall()

            trades = []
            for r in rows:
                entry_ts = float(r["entry_timestamp"] or 0.0)
                exit_ts = float(r["exit_timestamp"] or 0.0) if r["exit_timestamp"] else None
                hold_sec = round(exit_ts - entry_ts, 1) if exit_ts else round(time.time() - entry_ts, 1)

                trades.append({
                    "position_id": r["position_id"],
                    "symbol": r["symbol"],
                    "mint": r["mint"],
                    "status": r["status"],
                    "entry_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry_ts)) if entry_ts else "",
                    "exit_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exit_ts)) if exit_ts else "",
                    "hold_duration_seconds": hold_sec,
                    "entry_sol_cost": round(float(r["entry_sol_cost"] or 0.0), 4),
                    "exit_sol_received": round(float(r["exit_sol_received"] or 0.0), 4) if r["exit_sol_received"] is not None else "",
                    "entry_price_sol": f"{float(r['entry_price_sol'] or 0.0):.9f}",
                    "exit_or_current_price_sol": f"{float(r['current_price_sol'] or 0.0):.9f}",
                    "pnl_sol": round(float(r["unrealized_pnl_sol"] or 0.0), 4),
                    "pnl_pct": round(float(r["unrealized_pnl_pct"] or 0.0), 2),
                    "exit_reason": r["exit_reason"] or "",
                    "trigger_wallet": r["trigger_wallet"] or "",
                    "confidence_score": round(float(r["confidence_score"] or 0.0), 2),
                })
            return trades

    def export_all_learnings_records(self) -> Dict[str, Any]:
        """Exports full episodic memory, autopsies, counterfactuals, and hypotheses."""
        with self.get_connection() as conn:
            learnings = [dict(r) for r in conn.execute("SELECT * FROM episodic_learnings ORDER BY entry_time DESC;").fetchall()]
            shadows = [dict(r) for r in conn.execute("SELECT * FROM counterfactual_ledger ORDER BY evaluation_time DESC;").fetchall()]
            hypotheses = [dict(r) for r in conn.execute("SELECT * FROM discovered_hypotheses ORDER BY lift DESC;").fetchall()]
            clusters = [dict(r) for r in conn.execute("SELECT * FROM wallet_clusters ORDER BY coordination_probability DESC;").fetchall()]

            return {
                "exported_at": time.time(),
                "exported_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "total_autopsies": len(learnings),
                "total_counterfactual_shadows": len(shadows),
                "total_discovered_hypotheses": len(hypotheses),
                "total_clusters": len(clusters),
                "episodic_learnings": learnings,
                "counterfactual_ledger": shadows,
                "discovered_hypotheses": hypotheses,
                "wallet_clusters": clusters,
            }

