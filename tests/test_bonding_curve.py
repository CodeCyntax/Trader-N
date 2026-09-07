"""
Unit tests verifying exact mathematical formulas of the Pump.fun bonding curve.
"""
import unittest
from core.bonding_curve import PumpBondingCurve
from core.constants import (
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    BONDING_CURVE_REAL_TOKEN_RESERVES,
    LAMPORTS_PER_SOL,
    TOKEN_DECIMALS,
)


class TestPumpBondingCurve(unittest.TestCase):

    def setUp(self):
        self.curve = PumpBondingCurve()

    def test_initial_invariant(self):
        """Verify initial K invariant matches virtual reserves product."""
        expected_k = INITIAL_VIRTUAL_SOL_LAMPORTS * INITIAL_VIRTUAL_TOKEN_RESERVES
        self.assertEqual(self.curve.k, expected_k)

    def test_initial_spot_price(self):
        """Verify initial spot price calculation."""
        spot_price = self.curve.get_spot_price_sol()
        # 30 SOL / 1,073,000,000 tokens ≈ 2.7959e-8 SOL/token
        self.assertAlmostEqual(spot_price, 30.0 / 1_073_000_000.0, places=12)

    def test_initial_progress_zero(self):
        """Verify initial progress is 0.0%."""
        self.assertEqual(self.curve.get_progress_pct(), 0.0)

    def test_buy_tokens_out_math(self):
        """Verify exact token output and 1% fee deduction for 1 SOL buy."""
        sol_in = 1 * LAMPORTS_PER_SOL
        tokens_out, fee_lamports, sol_consumed, price_impact = self.curve.calculate_buy_tokens_out(sol_in)
        self.assertEqual(sol_consumed, sol_in)

        # 1% fee on 1 SOL = 0.01 SOL (10,000,000 lamports)
        self.assertEqual(fee_lamports, 10_000_000)
        net_sol = sol_in - fee_lamports

        # Exact Pump.fun Rust Anchor formula: (vTokens * net_sol) // (vSol + net_sol)
        new_v_sol = self.curve.virtual_sol + net_sol
        expected_tokens_out = (self.curve.virtual_tokens * net_sol) // new_v_sol

        self.assertEqual(tokens_out, expected_tokens_out)
        self.assertGreater(tokens_out, 0)
        self.assertGreater(price_impact, 0.0)

    def test_buy_and_sell_roundtrip_with_fees(self):
        """
        Verify that buying and then immediately selling tokens
        returns less SOL due strictly to the 1% entry and 1% exit platform fees.
        """
        initial_sol = 2 * LAMPORTS_PER_SOL
        tokens_bought, buy_fee, _ = self.curve.apply_buy(initial_sol)

        self.assertGreater(tokens_bought, 0)
        self.assertEqual(buy_fee, int(initial_sol * 0.01))

        # Now sell all tokens bought back to the curve
        sol_returned, sell_fee = self.curve.apply_sell(tokens_bought)

        # With 1% fee both ways, sol_returned should be approximately ~98% of initial_sol
        self.assertLess(sol_returned, initial_sol)
        self.assertGreater(sol_returned, int(initial_sol * 0.97))


if __name__ == "__main__":
    unittest.main()
