"""
Ultra-realistic Paper Trading Broker.
Executes simulated orders with exact bonding curve mathematics, real slippage,
and true network priority/base fee deductions.
"""
import time
import uuid
from typing import Dict, List, Optional, Tuple
from core.models import PaperPosition, PositionStatus, StrategyParameters
from core.bonding_curve import PumpBondingCurve
from core.constants import (
    SOLANA_BASE_FEE_LAMPORTS,
    SIMULATED_PRIORITY_FEE_LAMPORTS,
    LAMPORTS_PER_SOL,
    TOKEN_DECIMALS,
    SPL_ATA_RENT_EXEMPT_LAMPORTS,
    LATENCY_SLIPPAGE_BPS,
)
from memory.database import DatabaseManager


class PaperBroker:
    """
    Simulates live execution without fake fills or synthetic rates.
    Directly models liquidity, slippage, and Solana transaction costs.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        # In-memory tracking of open positions: mint -> PaperPosition
        self.open_positions: Dict[str, PaperPosition] = {}
        # Track bonding curves per mint: mint -> PumpBondingCurve
        self.active_curves: Dict[str, PumpBondingCurve] = {}
        self._load_open_positions()

    def _load_open_positions(self):
        """Loads any unclosed positions from persistent database."""
        positions = self.db.get_open_positions()
        for p in positions:
            self.open_positions[p.mint] = p

    def set_curve(self, mint: str, curve: PumpBondingCurve):
        """Registers or updates the bonding curve state for a token."""
        self.active_curves[mint] = curve

    def get_balance(self) -> float:
        """Returns currently available SOL balance."""
        return self.db.get_balance()

    def execute_buy(
        self,
        mint: str,
        symbol: str,
        sol_amount: float,
        curve: PumpBondingCurve,
        trigger_wallet: Optional[str] = None,
        confidence: float = 0.5,
    ) -> Optional[PaperPosition]:
        """
        Executes a realistic paper buy order against the exact bonding curve.
        Deducts only actual SOL consumed + Solana ATA rent + priority fee.
        Applies conservative 35 bps execution latency slippage to model 1-slot propagation delay.
        """
        current_balance = self.get_balance()
        network_fee_sol = (SOLANA_BASE_FEE_LAMPORTS + SIMULATED_PRIORITY_FEE_LAMPORTS) / LAMPORTS_PER_SOL

        sol_lamports = int(sol_amount * LAMPORTS_PER_SOL)
        tokens_out, platform_fee_lamports, sol_consumed_lamports, price_impact = curve.calculate_buy_tokens_out(sol_lamports)

        if tokens_out <= 0 or sol_consumed_lamports <= 0:
            return None

        # Solana ATA creation rent-exemption (165 bytes = 0.00203928 SOL)
        ata_fee_sol = SPL_ATA_RENT_EXEMPT_LAMPORTS / LAMPORTS_PER_SOL
        actual_sol_spent = sol_consumed_lamports / LAMPORTS_PER_SOL
        total_cost_sol = actual_sol_spent + network_fee_sol + ata_fee_sol

        if current_balance < total_cost_sol:
            return None  # Insufficient funds

        # Calculate effective execution price per whole token
        token_units = tokens_out / (10 ** TOKEN_DECIMALS)
        effective_price = actual_sol_spent / token_units

        # Apply conservative latency slippage (35 bps) to simulate 1-slot propagation delay on Solana
        latency_multiplier = 1.0 + (LATENCY_SLIPPAGE_BPS / 10_000.0)
        effective_price *= latency_multiplier

        position_id = str(uuid.uuid4())[:8]
        now = time.time()

        # Compute immediate net liquidation value upon entry (models realistic bid-ask spread & exit fees)
        net_liq_lamports, _, _ = curve.calculate_sell_sol_out(tokens_out)
        initial_liq_value = max(0.0, (net_liq_lamports / LAMPORTS_PER_SOL) - network_fee_sol)
        unrealized_pnl = initial_liq_value - total_cost_sol
        unrealized_pct = (unrealized_pnl / total_cost_sol) * 100.0

        position = PaperPosition(
            position_id=position_id,
            mint=mint,
            symbol=symbol,
            entry_timestamp=now,
            entry_sol_cost=total_cost_sol,
            tokens_held=tokens_out,
            initial_tokens_held=tokens_out,
            realized_sol_harvested=0.0,
            is_moonbag=False,
            moonbag_milestones_hit=[],
            entry_price_sol=effective_price,
            highest_price_sol=effective_price,
            current_price_sol=effective_price,
            current_value_sol=initial_liq_value,
            unrealized_pnl_sol=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pct,
            status=PositionStatus.OPEN,
            trigger_wallet=trigger_wallet,
            confidence_score=confidence,
        )

        # Deduct balance from DB (only the actual SOL consumed + fees, excess is refunded)
        self.db.adjust_balance_for_trade(-total_cost_sol)
        # Save position to DB and cache
        self.open_positions[mint] = position
        self.active_curves[mint] = curve
        self.db.save_position(position)

        return position

    def execute_partial_sell(
        self,
        mint: str,
        fraction: float,
        exit_reason: str,
        curve: Optional[PumpBondingCurve] = None,
    ) -> Optional[Tuple[PaperPosition, float]]:
        """
        Executes a partial sell (e.g. 50% at 2x or 25% at 5x) for the Moonbag Barbell Strategy.
        Sells `fraction` of current tokens held, credits net SOL to portfolio, and updates position.
        Returns: (position, net_sol_harvested)
        """
        position = self.open_positions.get(mint)
        if not position or fraction <= 0.0:
            return None

        fraction = min(1.0, fraction)
        tokens_to_sell = int(position.tokens_held * fraction)
        if tokens_to_sell <= 0:
            return None

        target_curve = curve or self.active_curves.get(mint) or PumpBondingCurve()
        net_sol_lamports, platform_fee_lamports, _ = target_curve.calculate_sell_sol_out(tokens_to_sell)
        net_sol_received = net_sol_lamports / LAMPORTS_PER_SOL

        network_fee_sol = (SOLANA_BASE_FEE_LAMPORTS + SIMULATED_PRIORITY_FEE_LAMPORTS) / LAMPORTS_PER_SOL
        net_harvested = max(0.0, net_sol_received - network_fee_sol)

        # Deduct tokens and credit harvested SOL
        position.tokens_held -= tokens_to_sell
        position.realized_sol_harvested += net_harvested

        # Check milestones
        if "HALF_INITIAL_SOL" not in position.moonbag_milestones_hit and position.realized_sol_harvested >= (position.entry_sol_cost * 0.95):
            position.is_moonbag = True
            position.moonbag_milestones_hit.append("HALF_INITIAL_SOL")
        if fraction > 0.40 and "HALF_INITIAL_SOL" in position.moonbag_milestones_hit and "LOCK_MOONBAG_PROFIT" not in position.moonbag_milestones_hit:
            position.moonbag_milestones_hit.append("LOCK_MOONBAG_PROFIT")

        # Credit harvested SOL to available cash balance
        self.db.adjust_balance_for_trade(net_harvested)

        # If remaining tokens dust (< 1000 atomic units), close completely
        if position.tokens_held < 1_000:
            return self.execute_sell(mint, exit_reason=exit_reason, curve=target_curve)

        # Update current liquidation value of remaining bag
        rem_net_lamports, _, _ = target_curve.calculate_sell_sol_out(position.tokens_held)
        rem_value_sol = max(0.0, (rem_net_lamports / LAMPORTS_PER_SOL) - network_fee_sol)
        position.current_value_sol = rem_value_sol
        # Total PnL accounts for SOL already harvested + remaining value
        total_pnl_sol = (position.realized_sol_harvested + rem_value_sol) - position.entry_sol_cost
        position.unrealized_pnl_sol = total_pnl_sol
        position.unrealized_pnl_pct = (total_pnl_sol / position.entry_sol_cost) * 100.0

        self.db.save_position(position)
        return position, net_harvested

    def execute_sell(
        self,
        mint: str,
        exit_reason: str,
        curve: Optional[PumpBondingCurve] = None,
    ) -> Optional[Tuple[PaperPosition, float]]:
        """
        Executes a complete liquidation of all remaining tokens held for a position.
        Calculates exact net SOL received minus platform and network priority fees.
        Returns: (closed_position, net_realized_pnl_sol)
        """
        position = self.open_positions.get(mint)
        if not position:
            return None

        target_curve = curve or self.active_curves.get(mint) or PumpBondingCurve()

        net_sol_lamports, platform_fee_lamports, _ = target_curve.calculate_sell_sol_out(position.tokens_held)
        net_sol_received = net_sol_lamports / LAMPORTS_PER_SOL

        network_fee_sol = (SOLANA_BASE_FEE_LAMPORTS + SIMULATED_PRIORITY_FEE_LAMPORTS) / LAMPORTS_PER_SOL
        net_cash_received = max(0.0, net_sol_received - network_fee_sol)

        now = time.time()
        # Cumulative realized PnL includes all previous partial harvest + final liquidation
        total_sol_out = position.realized_sol_harvested + net_cash_received
        realized_pnl_sol = total_sol_out - position.entry_sol_cost
        realized_pnl_pct = (realized_pnl_sol / position.entry_sol_cost) * 100.0

        position.status = PositionStatus.CLOSED
        position.exit_timestamp = now
        position.exit_sol_received = total_sol_out
        position.exit_reason = exit_reason
        position.tokens_held = 0
        position.current_value_sol = 0.0
        position.unrealized_pnl_sol = realized_pnl_sol
        position.unrealized_pnl_pct = realized_pnl_pct

        # Credit cash back to portfolio
        if net_cash_received > 0:
            self.db.adjust_balance_for_trade(net_cash_received)

        self.db.save_position(position)
        del self.open_positions[mint]

        return position, realized_pnl_sol

    def update_position_price(self, mint: str, curve: PumpBondingCurve) -> Optional[PaperPosition]:
        """
        Updates live position PnL and high-water mark price whenever a trade occurs on that mint.
        Accounts for harvested SOL in total position PnL.
        """
        position = self.open_positions.get(mint)
        if not position:
            return None

        self.active_curves[mint] = curve
        current_spot = curve.get_spot_price_sol()
        position.current_price_sol = current_spot

        # Update high-water mark for trailing stop
        if current_spot > position.highest_price_sol:
            position.highest_price_sol = current_spot

        # Calculate exact current liquidation value of remaining tokens
        net_sol_lamports, _, _ = curve.calculate_sell_sol_out(position.tokens_held)
        network_fee_sol = (SOLANA_BASE_FEE_LAMPORTS + SIMULATED_PRIORITY_FEE_LAMPORTS) / LAMPORTS_PER_SOL
        current_rem_value_sol = max(0.0, (net_sol_lamports / LAMPORTS_PER_SOL) - network_fee_sol)

        position.current_value_sol = current_rem_value_sol
        # Unrealized PnL accounts for already harvested SOL + current liquidation value
        total_position_value = position.realized_sol_harvested + current_rem_value_sol
        position.unrealized_pnl_sol = total_position_value - position.entry_sol_cost
        position.unrealized_pnl_pct = (position.unrealized_pnl_sol / position.entry_sol_cost) * 100.0

        self.db.save_position(position)
        return position

    def get_portfolio_summary(self) -> Dict[str, float]:
        """Returns total portfolio value including cash and unrealized positions."""
        sol_cash = self.get_balance()
        positions_value = sum(p.current_value_sol for p in self.open_positions.values())
        total_value = sol_cash + positions_value
        unrealized_pnl = sum(p.unrealized_pnl_sol for p in self.open_positions.values())

        return {
            "cash_sol": sol_cash,
            "positions_value_sol": positions_value,
            "total_portfolio_sol": total_value,
            "unrealized_pnl_sol": unrealized_pnl,
            "open_positions_count": len(self.open_positions),
        }

    def reset(self):
        """Clears all open paper positions and active curves from memory."""
        self.open_positions.clear()
        self.active_curves.clear()

