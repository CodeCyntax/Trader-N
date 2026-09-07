"""
Exact mathematical implementation of Pump.fun constant product bonding curve.
Eliminates simulated approximations: calculates exact tokens, SOL, fees, and slippage.
"""
from typing import Tuple, Dict, Any
from core.constants import (
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    INITIAL_INVARIANT_K,
    BONDING_CURVE_REAL_TOKEN_RESERVES,
    MIGRATION_SOL_LAMPORTS,
    PUMP_FEE_BPS,
    LAMPORTS_PER_SOL,
    TOKEN_DECIMALS,
)


class PumpBondingCurve:
    """
    Simulates and computes the exact on-chain state of a Pump.fun bonding curve.
    Formula: VirtualSol * VirtualTokens = K
    """

    def __init__(
        self,
        virtual_sol: int = INITIAL_VIRTUAL_SOL_LAMPORTS,
        virtual_tokens: int = INITIAL_VIRTUAL_TOKEN_RESERVES,
        real_tokens_remaining: int = BONDING_CURVE_REAL_TOKEN_RESERVES,
    ):
        self.virtual_sol = int(virtual_sol)
        self.virtual_tokens = int(virtual_tokens)
        self.real_tokens_remaining = int(real_tokens_remaining)
        self.k = self.virtual_sol * self.virtual_tokens

    @classmethod
    def from_curve_reserves(cls, virtual_sol: int, virtual_tokens: int) -> "PumpBondingCurve":
        """Instantiate directly from on-chain or stream reserves."""
        curve = cls(virtual_sol=virtual_sol, virtual_tokens=virtual_tokens)
        # Real tokens remaining are the difference from initial virtual reserve to migration boundary
        curve.real_tokens_remaining = max(0, virtual_tokens - (INITIAL_VIRTUAL_TOKEN_RESERVES - BONDING_CURVE_REAL_TOKEN_RESERVES))
        return curve

    def update_reserves(self, virtual_sol: int, virtual_tokens: int):
        """Updates curve reserves while keeping invariant K precisely synchronized."""
        self.virtual_sol = int(virtual_sol)
        self.virtual_tokens = int(virtual_tokens)
        self.k = self.virtual_sol * self.virtual_tokens
        self.real_tokens_remaining = max(0, self.virtual_tokens - (INITIAL_VIRTUAL_TOKEN_RESERVES - BONDING_CURVE_REAL_TOKEN_RESERVES))

    def get_spot_price_sol(self) -> float:
        """
        Returns spot price: SOL per 1 whole Token.
        1 whole token = 10^6 atomic token units.
        1 whole SOL = 10^9 lamports.
        """
        if self.virtual_tokens == 0:
            return 0.0
        # price = (virtual_sol / 1e9) / (virtual_tokens / 1e6)
        return (self.virtual_sol / 1e9) / (self.virtual_tokens / (10 ** TOKEN_DECIMALS))

    def get_spot_price(self) -> float:
        """Alias for get_spot_price_sol."""
        return self.get_spot_price_sol()

    def get_market_cap_sol(self) -> float:
        """
        Returns the market cap in SOL based on total initial supply (1,000,000,000 tokens).
        """
        total_supply = 1_000_000_000.0
        return self.get_spot_price_sol() * total_supply

    def get_progress_pct(self) -> float:
        """
        Calculates the completion progress of the bonding curve (0.0% to 100.0%).
        Progress is determined by the real SOL deposited relative to the migration threshold (~85 SOL).
        """
        real_sol_lamports = max(0, self.virtual_sol - INITIAL_VIRTUAL_SOL_LAMPORTS)
        progress = (real_sol_lamports / MIGRATION_SOL_LAMPORTS) * 100.0
        return min(100.0, max(0.0, progress))

    def get_bonding_curve_progress_pct(self) -> float:
        """Alias for get_progress_pct."""
        return self.get_progress_pct()

    @property
    def is_migrated(self) -> bool:
        """True if the bonding curve has filled (real tokens remaining = 0 or progress >= 100%)."""
        return self.real_tokens_remaining <= 0 or self.get_progress_pct() >= 100.0

    def calculate_buy_tokens_out(self, sol_in_lamports: int) -> Tuple[int, int, int, float]:
        """
        Calculates exact tokens received for a given SOL input using Pump.fun integer arithmetic.
        Returns:
            (tokens_out, fee_lamports, sol_consumed_lamports, price_impact_pct)
        """
        if sol_in_lamports <= 0 or self.is_migrated:
            return 0, 0, 0, 0.0

        fee_lamports = (sol_in_lamports * PUMP_FEE_BPS) // 10_000
        net_sol_lamports = sol_in_lamports - fee_lamports

        # Exact integer formula: tokens_out = (vTokens * net_sol) // (vSol + net_sol)
        tokens_out = (self.virtual_tokens * net_sol_lamports) // (self.virtual_sol + net_sol_lamports)
        sol_consumed = sol_in_lamports

        # Cap at remaining real tokens on curve (Raydium migration boundary)
        if tokens_out > self.real_tokens_remaining:
            tokens_out = self.real_tokens_remaining
            # Net SOL required: ceil division to protect pool
            net_sol_required = ((self.virtual_sol * tokens_out) + (self.virtual_tokens - tokens_out - 1)) // (self.virtual_tokens - tokens_out)
            fee_lamports = (net_sol_required * PUMP_FEE_BPS) // 10_000
            sol_consumed = net_sol_required + fee_lamports

        # Calculate price impact
        spot_price_before = self.get_spot_price_sol()
        effective_price = ((sol_consumed - fee_lamports) / LAMPORTS_PER_SOL) / (tokens_out / (10 ** TOKEN_DECIMALS)) if tokens_out > 0 else 0
        price_impact_pct = ((effective_price - spot_price_before) / spot_price_before * 100.0) if spot_price_before > 0 else 0.0

        return tokens_out, fee_lamports, sol_consumed, price_impact_pct

    def apply_buy(self, sol_in_lamports: int) -> Tuple[int, int, int]:
        """
        Mutates internal curve state by executing a buy.
        Caps at migration boundary and preserves exact constant product invariant.
        Returns: (tokens_out, fee_lamports, sol_consumed_lamports)
        """
        tokens_out, fee_lamports, sol_consumed, _ = self.calculate_buy_tokens_out(sol_in_lamports)
        if tokens_out <= 0:
            return 0, 0, 0

        net_sol = sol_consumed - fee_lamports
        self.virtual_sol += net_sol
        self.virtual_tokens = max(1, self.virtual_tokens - tokens_out)
        self.real_tokens_remaining = max(0, self.real_tokens_remaining - tokens_out)
        return tokens_out, fee_lamports, sol_consumed

    def calculate_sell_sol_out(self, tokens_in: int) -> Tuple[int, int, float]:
        """
        Calculates exact SOL received for a given Token input.
        Returns:
            (net_sol_lamports, fee_lamports, price_impact_pct)
        """
        if tokens_in <= 0:
            return 0, 0, 0.0

        # Exact integer formula: gross_sol = (vSol * tokens_in) // (vTokens + tokens_in)
        gross_sol_lamports = (self.virtual_sol * tokens_in) // (self.virtual_tokens + tokens_in)

        fee_lamports = (gross_sol_lamports * PUMP_FEE_BPS) // 10_000
        net_sol_lamports = max(0, gross_sol_lamports - fee_lamports)

        # Price impact
        spot_price_before = self.get_spot_price_sol()
        effective_price = (gross_sol_lamports / LAMPORTS_PER_SOL) / (tokens_in / (10 ** TOKEN_DECIMALS)) if tokens_in > 0 else 0
        price_impact_pct = ((spot_price_before - effective_price) / spot_price_before * 100.0) if spot_price_before > 0 else 0.0

        return net_sol_lamports, fee_lamports, price_impact_pct

    def apply_sell(self, tokens_in: int) -> Tuple[int, int]:
        """
        Mutates internal curve state by executing a sell.
        Returns: (net_sol_lamports, fee_lamports)
        """
        net_sol_lamports, fee_lamports, _ = self.calculate_sell_sol_out(tokens_in)
        gross_sol_lamports = net_sol_lamports + fee_lamports
        if gross_sol_lamports <= 0:
            return 0, 0

        self.virtual_tokens += tokens_in
        self.virtual_sol = max(1, self.virtual_sol - gross_sol_lamports)
        self.real_tokens_remaining = min(BONDING_CURVE_REAL_TOKEN_RESERVES, self.real_tokens_remaining + tokens_in)
        return net_sol_lamports, fee_lamports

    def to_dict(self) -> Dict[str, Any]:
        """Serializes current curve state."""
        return {
            "virtual_sol_lamports": self.virtual_sol,
            "virtual_sol": self.virtual_sol / LAMPORTS_PER_SOL,
            "virtual_tokens": self.virtual_tokens / (10 ** TOKEN_DECIMALS),
            "real_tokens_remaining": self.real_tokens_remaining / (10 ** TOKEN_DECIMALS),
            "spot_price_sol": self.get_spot_price_sol(),
            "market_cap_sol": self.get_market_cap_sol(),
            "progress_pct": self.get_progress_pct(),
        }
