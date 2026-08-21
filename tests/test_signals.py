import unittest

from swing_bot.config import StrategySettings
from swing_bot.signals import Bar, Signal, evaluate_at, evaluate_latest


def bars_from_closes(closes: list[float]) -> list[Bar]:
    return [
        Bar(
            open=closes[index - 1] if index else close,
            high=max(closes[index - 1] if index else close, close) + 0.1,
            low=min(closes[index - 1] if index else close, close) - 0.1,
            close=close,
            volume=1_000,
        )
        for index, close in enumerate(closes)
    ]


class SignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = StrategySettings(
            fast_sma_period=2,
            slow_sma_period=4,
            sma_separation_fraction=0.10,
            crossover_fraction=0.05,
            trailing_stop_fraction=0.05,
        )

    def test_warmup_requires_previous_and_current_smas(self) -> None:
        evaluation = evaluate_latest(bars_from_closes([100.0] * 4), self.settings)
        self.assertEqual(evaluation.signal, Signal.NONE)
        self.assertIn("warmup", evaluation.reason)

    def test_long_crosses_above_fast_sma_in_uptrend(self) -> None:
        evaluation = evaluate_latest(
            bars_from_closes([40.0, 40.0, 120.0, 100.0, 110.0]),
            self.settings,
        )
        self.assertEqual(evaluation.signal, Signal.LONG)
        self.assertAlmostEqual(evaluation.fast_sma or 0, 105.0)
        self.assertAlmostEqual(evaluation.slow_sma or 0, 92.5)

    def test_long_does_not_chase_move_more_than_five_percent_above_sma(self) -> None:
        evaluation = evaluate_latest(
            bars_from_closes([40.0, 40.0, 120.0, 100.0, 120.0]),
            self.settings,
        )
        self.assertEqual(evaluation.signal, Signal.NONE)

    def test_long_rejects_close_still_below_fast_sma(self) -> None:
        evaluation = evaluate_latest(
            bars_from_closes([40.0, 40.0, 120.0, 100.0, 100.0]),
            self.settings,
        )
        self.assertEqual(evaluation.signal, Signal.NONE)

    def test_long_rejects_fast_sma_less_than_ten_percent_above_slow_sma(self) -> None:
        evaluation = evaluate_latest(
            bars_from_closes([100.0, 100.0, 108.0, 100.0, 105.0]),
            self.settings,
        )
        self.assertEqual(evaluation.signal, Signal.NONE)

    def test_short_crosses_below_fast_sma_in_downtrend(self) -> None:
        evaluation = evaluate_latest(
            bars_from_closes([160.0, 160.0, 80.0, 100.0, 90.5]),
            self.settings,
        )
        self.assertEqual(evaluation.signal, Signal.SHORT)

    def test_evaluate_at_cannot_see_future_bar(self) -> None:
        bars = bars_from_closes([40.0, 40.0, 120.0, 100.0, 110.0, 200.0])
        self.assertEqual(
            evaluate_at(bars, 4, self.settings),
            evaluate_latest(bars[:5], self.settings),
        )

    def test_invalid_bar_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            Bar(open=10, high=9, low=8, close=10)


if __name__ == "__main__":
    unittest.main()