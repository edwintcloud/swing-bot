import unittest
from datetime import UTC, datetime

from swing_bot.config import RiskSettings
from swing_bot.risk import (
    EquityReferences,
    PortfolioSnapshot,
    calculate_position_size,
    evaluate_entry_risk,
)


def snapshot(**overrides: float) -> PortfolioSnapshot:
    values: dict[str, float | int] = {
        "equity": 100_000.0,
        "day_start_equity": 100_000.0,
        "week_start_equity": 100_000.0,
        "high_water_equity": 100_000.0,
        "gross_exposure": 0.0,
        "short_exposure": 0.0,
        "open_positions": 0,
    }
    values.update(overrides)
    return PortfolioSnapshot(**values)  # type: ignore[arg-type]


class PositionSizingTests(unittest.TestCase):
    def test_risk_budget_limits_shares(self) -> None:
        size = calculate_position_size(equity=100_000, entry_price=50, stop_price=45)
        self.assertEqual(size.shares, 100)
        self.assertEqual(size.risk_amount, 500)
        self.assertEqual(size.limiting_factor, "risk")

    def test_notional_budget_limits_shares(self) -> None:
        size = calculate_position_size(equity=100_000, entry_price=100, stop_price=99)
        self.assertEqual(size.shares, 100)
        self.assertEqual(size.notional, 10_000)
        self.assertEqual(size.limiting_factor, "notional")

    def test_zero_stop_distance_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must differ"):
            calculate_position_size(equity=100_000, entry_price=50, stop_price=50)


class EntryRiskTests(unittest.TestCase):
    def test_equity_references_roll_day_and_week(self) -> None:
        references = EquityReferences.initialize(100_000, datetime(2025, 1, 3, 21, tzinfo=UTC))
        references.update(101_000, datetime(2025, 1, 3, 22, tzinfo=UTC))
        self.assertEqual(references.high_water_equity, 101_000)
        references.update(99_000, datetime(2025, 1, 6, 21, tzinfo=UTC))
        self.assertEqual(references.day_start_equity, 99_000)
        self.assertEqual(references.week_start_equity, 99_000)
        self.assertEqual(references.high_water_equity, 101_000)

    def test_equity_references_can_ignore_open_position_peak(self) -> None:
        references = EquityReferences.initialize(100_000, datetime(2025, 1, 3, 21, tzinfo=UTC))
        references.update(
            110_000,
            datetime(2025, 1, 3, 22, tzinfo=UTC),
            track_high_water=False,
        )
        self.assertEqual(references.equity, 110_000)
        self.assertEqual(references.high_water_equity, 100_000)

    def test_equity_references_round_trip_for_restart(self) -> None:
        references = EquityReferences.initialize(
            100_000, datetime(2026, 8, 28, 14, tzinfo=UTC)
        )
        references.update(98_750, datetime(2026, 8, 28, 15, tzinfo=UTC))

        restored = EquityReferences.from_dict(references.to_dict())

        self.assertEqual(restored.day_start_equity, 100_000)
        self.assertEqual(restored.week_start_equity, 100_000)
        self.assertEqual(restored.high_water_equity, 100_000)
        self.assertEqual(restored.equity, 98_750)

    def test_entry_within_limits_is_allowed(self) -> None:
        decision = evaluate_entry_risk(
            snapshot=snapshot(gross_exposure=0.10), proposed_notional=10_000, is_short=False
        )
        self.assertTrue(decision.allowed)

    def test_daily_loss_trips_circuit_breaker(self) -> None:
        decision = evaluate_entry_risk(
            snapshot=snapshot(equity=98_500), proposed_notional=5_000, is_short=False
        )
        self.assertFalse(decision.allowed)
        self.assertIn("daily loss", decision.reason)

    def test_short_exposure_cap_is_enforced(self) -> None:
        decision = evaluate_entry_risk(
            snapshot=snapshot(gross_exposure=0.15, short_exposure=0.15),
            proposed_notional=6_000,
            is_short=True,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("short exposure", decision.reason)

    def test_position_cap_is_enforced(self) -> None:
        settings = RiskSettings(maximum_positions=3)
        decision = evaluate_entry_risk(
            snapshot=snapshot(open_positions=3),
            proposed_notional=5_000,
            is_short=False,
            settings=settings,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("positions", decision.reason)


if __name__ == "__main__":
    unittest.main()
