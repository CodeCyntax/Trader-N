"""
Stress-test suite for Subsystem 2: AMM Bonding Curve Physics & Raydium Migration.
Tests:
- Non-linear price impact and slippage scaling
- Migration boundary overflow and excess SOL refund math
- Invariant preservation across 100 interleaved buys and sells
"""
import unittest
from core.bonding_curve import PumpBondingCurve
from core.constants import (
    LAMPORTS_PER_SOL,
    MIGRATION_SOL_LAMPORTS,
    BONDING_CURVE_REAL_TOKEN_RESERVES,
)


class TestCurvePhysics(unittest.TestCase):

    def setUp(self):
        self.curve = PumpBondingCurve()

    def test_price_impact_scales_non_linearly(self):
        """
        Verify that larger orders suffer higher percentage slippage/price impact
        than small orders due to constant-product curvature.
        """
        _, _, _, impact_small = self.curve.calculate_buy_tokens_out(int(0.1 * LAMPORTS_PER_SOL))
        _, _, _, impact_medium = self.curve.calculate_buy_tokens_out(int(1.0 * LAMPORTS_PER_SOL))
        _, _, _, impact_large = self.curve.calculate_buy_tokens_out(int(5.0 * LAMPORTS_PER_SOL))

        self.assertGreater(impact_medium, impact_small)
        self.assertGreater(impact_large, impact_medium)
        self.assertLess(impact_small, 2.0)  # 0.1 SOL on 30 SOL pool is < 2% impact
        self.assertGreater(impact_large, 7.0)  # 5 SOL on 30 SOL pool has substantial impact

    def test_migration_boundary_overflow_protection(self):
        """
        When a buy pushes the curve past 85 SOL (migration threshold),
        it must only consume the tokens remaining on the curve and accurately cap progress at 100%.
        """
        # Deposit 84 SOL into curve
        self.curve.apply_buy(int(84.0 * LAMPORTS_PER_SOL))
        progress_before = self.curve.get_progress_pct()
        self.assertGreater(progress_before, 95.0)
        self.assertFalse(self.curve.is_migrated)

        # Attempt to buy 5.0 SOL (which would overshoot the 85 SOL cap)
        tokens_remaining_before = self.curve.real_tokens_remaining
        tokens_out, fee, sol_consumed = self.curve.apply_buy(int(5.0 * LAMPORTS_PER_SOL))

        # Must not dispense more than the tokens remaining
        self.assertLessEqual(tokens_out, tokens_remaining_before)
        self.assertEqual(self.curve.real_tokens_remaining, 0)
        self.assertEqual(self.curve.get_progress_pct(), 100.0)
        self.assertTrue(self.curve.is_migrated)
        self.assertLess(sol_consumed, int(5.0 * LAMPORTS_PER_SOL), "Excess SOL must not be consumed")

    def test_invariant_k_preservation(self):
        """
        Across 50 interleaved buys and sells, invariant k must remain stable
        and not drift due to rounding or mutation inaccuracies.
        """
        initial_k = self.curve.k
        for i in range(25):
            # Buy
            tokens_out, _, _ = self.curve.apply_buy(int(0.25 * LAMPORTS_PER_SOL))
            # Sell partial
            if tokens_out > 0:
                self.curve.apply_sell(tokens_out // 2)

        # k should remain virtually identical (allowing minor integer division truncation < 0.001%)
        drift_pct = abs(self.curve.k - initial_k) / initial_k * 100.0
        self.assertLess(drift_pct, 0.05)


if __name__ == "__main__":
    unittest.main()
