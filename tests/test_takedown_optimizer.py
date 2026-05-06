"""Deterministic NPV math for the takedown optimizer.

The LLM produces structures; Python computes NPV. If the math drifts,
every Optimizer-mode run reports wrong revenue projections — these
tests guard the arithmetic.
"""
from __future__ import annotations

import unittest

from services.takedown_optimizer.optimizer import _compute_npv
from services.takedown_optimizer.schemas import TakedownStructure


def _structure(
    base: float,
    escalator_pct: float = 0.0,
    velocity: float = 10.0,
    basis: str = "quarterly",
    option_fee: float | None = None,
) -> TakedownStructure:
    return TakedownStructure(
        label="test",
        base_lot_price=base,
        escalator_pct=escalator_pct,
        escalator_basis=basis,  # type: ignore[arg-type]
        option_fee=option_fee,
        velocity_per_qtr=velocity,
        cadence="test",
        minimum_takedown_per_qtr=None,
        default_triggers="test",
        rationale="test",
        risk_notes="test",
    )


class TakedownNPVTest(unittest.TestCase):
    def test_zero_velocity_returns_zero(self) -> None:
        s = _structure(base=100_000, velocity=0.0)
        out = _compute_npv(structure=s, lot_count=120, discount_rate=0.12)
        self.assertEqual(out.total_revenue, 0.0)
        self.assertEqual(out.npv, 0.0)
        self.assertEqual(out.quarters, 0)

    def test_no_escalator_no_discount(self) -> None:
        s = _structure(base=100_000, escalator_pct=0.0, velocity=12.0)
        out = _compute_npv(structure=s, lot_count=120, discount_rate=0.0)
        self.assertEqual(out.quarters, 10)
        self.assertEqual(out.total_revenue, 12_000_000.0)
        self.assertEqual(out.npv, 12_000_000.0)

    def test_lot_count_caps_total_lots(self) -> None:
        s = _structure(base=50_000, velocity=20.0)
        out = _compute_npv(structure=s, lot_count=50, discount_rate=0.0)
        self.assertEqual(out.total_lots, 50.0)
        self.assertEqual(out.quarters, 3)
        self.assertEqual(out.total_revenue, 50 * 50_000)

    def test_quarterly_escalator_compounds(self) -> None:
        s = _structure(base=100_000, escalator_pct=0.05, velocity=10.0, basis="quarterly")
        out = _compute_npv(structure=s, lot_count=20, discount_rate=0.0)
        expected = 10 * 100_000 + 10 * 100_000 * 1.05
        self.assertAlmostEqual(out.total_revenue, expected, places=2)

    def test_annual_escalator_uses_quartic_root(self) -> None:
        s = _structure(base=100_000, escalator_pct=0.04, velocity=10.0, basis="annual")
        out = _compute_npv(structure=s, lot_count=20, discount_rate=0.0)
        per_q = 1.04 ** 0.25
        expected = 10 * 100_000 + 10 * 100_000 * per_q
        self.assertAlmostEqual(out.total_revenue, expected, places=2)

    def test_discount_reduces_npv_below_revenue(self) -> None:
        s = _structure(base=100_000, escalator_pct=0.0, velocity=12.0)
        out = _compute_npv(structure=s, lot_count=120, discount_rate=0.12)
        self.assertEqual(out.total_revenue, 12_000_000.0)
        self.assertLess(out.npv, out.total_revenue)
        self.assertGreater(out.npv, 0.0)

    def test_option_fee_adds_to_revenue_and_npv(self) -> None:
        s = _structure(base=100_000, velocity=10.0, option_fee=250_000)
        out = _compute_npv(structure=s, lot_count=10, discount_rate=0.0)
        self.assertEqual(out.total_revenue, 1_250_000.0)
        self.assertEqual(out.npv, 1_250_000.0)


if __name__ == "__main__":
    unittest.main()
