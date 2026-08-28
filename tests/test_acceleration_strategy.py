import unittest

from swing_bot.acceleration_strategy import (
    ACCELERATION_ENTRY_TAG,
    ACCELERATION_FLATLINE_EXIT_TAG,
    build_acceleration_entry_plan,
    is_flatline_exit_order,
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


if __name__ == "__main__":
    unittest.main()