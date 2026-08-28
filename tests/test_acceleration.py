import unittest

from swing_bot.acceleration import NS_PER_SECOND, AccelerationTracker
from swing_bot.config import PriceAccelerationSettings
from swing_bot.signals import Signal


class AccelerationTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = PriceAccelerationSettings(
            acceleration_threshold=0.02,
            deceleration_threshold=0.01,
            flatline_threshold=0.002,
            flatline_bars=3,
            trailing_stop_fraction=0.01,
            setup_expiry_seconds=10,
            cooldown_seconds=5,
        )
        self.tracker = AccelerationTracker(self.settings)
        self.close = 100.0
        self.second = 0

    def update_returns(self, returns: list[float]):
        if self.tracker.previous_close is None:
            result = self.tracker.update(self.close, self.second * NS_PER_SECOND)
        else:
            result = None
        for value in returns:
            self.second += 1
            self.close *= 1.0 + value
            result = self.tracker.update(self.close, self.second * NS_PER_SECOND)
        assert result is not None
        return result

    def test_long_arms_then_enters_on_peak_deceleration(self) -> None:
        result = self.update_returns([0.0, 0.02, 0.03])
        self.assertEqual(result.signal, Signal.LONG)
        self.assertAlmostEqual(result.velocity or 0, 0.03)
        self.assertAlmostEqual(result.acceleration or 0, 0.01)

    def test_short_is_symmetric(self) -> None:
        result = self.update_returns([0.0, -0.02, -0.03])
        self.assertEqual(result.signal, Signal.SHORT)

    def test_deceleration_does_not_enter_after_velocity_reverses(self) -> None:
        result = self.update_returns([0.0, 0.02, -0.01])
        self.assertEqual(result.signal, Signal.NONE)

    def test_setup_expires_at_boundary(self) -> None:
        self.update_returns([0.0, 0.02])
        close = self.tracker.previous_close or 100.0
        result = self.tracker.update(close * 1.01, 12 * NS_PER_SECOND)
        self.assertEqual(result.signal, Signal.NONE)
        self.assertEqual(self.tracker.armed_signal, Signal.NONE)

    def test_bar_gap_resets_velocity_and_armed_setup(self) -> None:
        self.update_returns([0.0, 0.02])
        close = self.tracker.previous_close or 100.0
        result = self.tracker.update(close * 1.20, 20 * NS_PER_SECOND)
        self.assertEqual(result.reason, "velocity warmup")
        self.assertEqual(self.tracker.armed_signal, Signal.NONE)

    def test_five_second_bars_are_normalized_to_per_second_rates(self) -> None:
        tracker = AccelerationTracker(PriceAccelerationSettings())
        tracker.update(100.0, 0)
        warmup = tracker.update(101.0, 5 * NS_PER_SECOND)
        evaluation = tracker.update(102.01, 10 * NS_PER_SECOND)
        self.assertAlmostEqual(warmup.velocity or 0, 0.002)
        self.assertAlmostEqual(evaluation.velocity or 0, 0.002)
        self.assertAlmostEqual(evaluation.acceleration or 0, 0.0)

    def test_flatline_requires_consecutive_bars(self) -> None:
        self.update_returns([0.0, 0.01])
        self.tracker.position_opened(Signal.LONG)
        first = self.update_returns([0.01])
        second = self.update_returns([0.01])
        third = self.update_returns([0.01])
        self.assertFalse(first.should_exit)
        self.assertFalse(second.should_exit)
        self.assertTrue(third.should_exit)

    def test_nonflat_acceleration_resets_flatline_count(self) -> None:
        self.update_returns([0.0, 0.01])
        self.tracker.position_opened(Signal.LONG)
        self.update_returns([0.01, 0.01])
        self.update_returns([0.02])
        result = self.update_returns([0.02, 0.02])
        self.assertFalse(result.should_exit)
        self.assertEqual(self.tracker.flatline_count, 2)

    def test_cooldown_blocks_rearming_until_boundary(self) -> None:
        self.tracker.position_opened(Signal.LONG)
        self.tracker.position_closed(10 * NS_PER_SECOND)
        self.second = 10
        self.update_returns([0.0, 0.02])
        self.assertEqual(self.tracker.armed_signal, Signal.NONE)
        result = self.update_returns([0.0, 0.0, 0.0, 0.02])
        self.assertEqual(result.reason, "LONG setup armed")


if __name__ == "__main__":
    unittest.main()