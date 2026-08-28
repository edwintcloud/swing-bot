import unittest
from datetime import UTC, datetime

from swing_bot.acceleration_strategy import (
    ACCELERATION_ENTRY_TAG,
    ACCELERATION_FLATLINE_EXIT_TAG,
    build_acceleration_entry_plan,
    is_flatline_exit_order,
    is_regular_session,
)
from swing_bot.config import PriceAccelerationSettings
from swing_bot.signals import Signal
from swing_bot.strategy import is_entry_order


class AccelerationEntryPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = PriceAccelerationSettings(trailing_stop_fraction=0.0015)

    def test_long_uses_trailing_distance_for_initial_risk(self) -> None:
        plan = build_acceleration_entry_plan(Signal.LONG, 100.0, self.settings)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertAlmostEqual(plan.initial_stop_price, 99.85)

    def test_short_uses_trailing_distance_for_initial_risk(self) -> None:
        plan = build_acceleration_entry_plan(Signal.SHORT, 100.0, self.settings)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertAlmostEqual(plan.initial_stop_price, 100.15)

    def test_no_signal_has_no_entry_plan(self) -> None:
        self.assertIsNone(
            build_acceleration_entry_plan(Signal.NONE, 100.0, self.settings)
        )

    def test_flatline_exit_tag_is_detected(self) -> None:
        tagged = type("Order", (), {"tags": [ACCELERATION_FLATLINE_EXIT_TAG]})()
        untagged = type("Order", (), {"tags": []})()
        self.assertTrue(is_flatline_exit_order(tagged))
        self.assertFalse(is_flatline_exit_order(untagged))

    def test_acceleration_entry_retains_generic_lifecycle_tag(self) -> None:
        order = type("Order", (), {"tags": ["ENTRY", ACCELERATION_ENTRY_TAG]})()
        self.assertTrue(is_entry_order(order))

    def test_regular_session_uses_new_york_time(self) -> None:
        def timestamp(value: str) -> int:
            parsed = datetime.fromisoformat(value).astimezone(UTC)
            return int(parsed.timestamp() * 1_000_000_000)

        self.assertTrue(is_regular_session(timestamp("2026-08-28T09:30:00-04:00")))
        self.assertTrue(is_regular_session(timestamp("2026-08-28T15:59:59-04:00")))
        self.assertFalse(is_regular_session(timestamp("2026-08-28T09:29:59-04:00")))
        self.assertFalse(is_regular_session(timestamp("2026-08-28T16:00:00-04:00")))
        self.assertFalse(is_regular_session(timestamp("2026-08-29T12:00:00-04:00")))


if __name__ == "__main__":
    unittest.main()