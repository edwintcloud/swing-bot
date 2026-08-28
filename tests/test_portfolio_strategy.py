import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from nautilus_trader.model.identifiers import InstrumentId

from swing_bot.dashboard_bridge import DashboardCommand
from swing_bot.portfolio_strategy import (
    PortfolioMomentumConfig,
    PortfolioMomentumStrategy,
)
from swing_bot.signals import Bar


def timestamp_ns(year: int, month: int, day: int, hour: int) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1_000_000_000)


class PortfolioMomentumStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instrument_id = InstrumentId.from_str("AAA.NYSE")
        self.strategy = PortfolioMomentumStrategy(
            PortfolioMomentumConfig(
                instrument_ids=("AAA.NYSE",),
                signal_bar_types=("AAA.NYSE-1-MINUTE-LAST-EXTERNAL",),
                sectors={"AAA": "Test"},
                starting_equity=100_000,
            )
        )

    def test_daily_observations_exclude_non_regular_hours(self) -> None:
        result = self.strategy._consume_regular_hour(
            self.instrument_id,
            Bar(100, 101, 99, 100, 10),
            timestamp_ns(2026, 8, 3, 14),
        )

        self.assertIsNone(result)
        self.assertNotIn(self.instrument_id, self.strategy._daily_accumulators)

    def test_completed_day_is_lagged_until_next_session(self) -> None:
        self.strategy._consume_regular_hour(
            self.instrument_id,
            Bar(100, 101, 99, 100, 10),
            timestamp_ns(2026, 8, 3, 15),
        )
        self.strategy._consume_regular_hour(
            self.instrument_id,
            Bar(100, 102, 99, 101, 20),
            timestamp_ns(2026, 8, 3, 20),
        )

        self.assertEqual(self.strategy._daily_observations[self.instrument_id], [])

        self.strategy._consume_regular_hour(
            self.instrument_id,
            Bar(102, 103, 101, 102, 30),
            timestamp_ns(2026, 8, 4, 15),
        )

        observations = self.strategy._daily_observations[self.instrument_id]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].close, 101)
        self.assertEqual(observations[0].dollar_volume, 3_020)

    def test_weekly_rebalance_waits_for_the_complete_universe(self) -> None:
        strategy = PortfolioMomentumStrategy(
            PortfolioMomentumConfig(
                instrument_ids=("AAA.NYSE", "BBB.NYSE"),
                signal_bar_types=(
                    "AAA.NYSE-1-MINUTE-LAST-EXTERNAL",
                    "BBB.NYSE-1-MINUTE-LAST-EXTERNAL",
                ),
                sectors={"AAA": "Test", "BBB": "Test"},
                starting_equity=100_000,
            )
        )
        first = InstrumentId.from_str("AAA.NYSE")
        second = InstrumentId.from_str("BBB.NYSE")
        local_time = datetime(2026, 8, 3, 11, tzinfo=UTC)
        bars = [SimpleNamespace(bar_type=bar_type) for bar_type in strategy._signal_bar_types]

        with (
            patch.object(
                strategy,
                "_consume_bar",
                side_effect=(
                    (first, Bar(1, 1, 1, 1, 1), 1),
                    (second, Bar(1, 1, 1, 1, 1), 2),
                    (first, Bar(1, 1, 1, 1, 1), 3),
                ),
            ),
            patch.object(strategy, "_consume_regular_hour", return_value=local_time),
            patch.object(strategy, "_rebalance") as rebalance,
        ):
            strategy.on_bar(bars[0])
            rebalance.assert_not_called()
            strategy.on_bar(bars[1])
            strategy.on_bar(bars[0])

        rebalance.assert_called_once_with()

    def test_dashboard_pause_blocks_rebalances(self) -> None:
        dashboard = SimpleNamespace(paused=False)
        self.strategy._dashboard = dashboard

        result = self.strategy._process_dashboard_command(
            DashboardCommand("command-1", "set_paused", {"paused": True})
        )

        self.assertEqual(result, "entries paused")
        self.assertTrue(self.strategy._paused)
        self.assertTrue(dashboard.paused)

    def test_dashboard_rejects_invalid_flatten_target(self) -> None:
        self.strategy._dashboard = SimpleNamespace(paused=False)

        result = self.strategy._process_dashboard_command(
            DashboardCommand("command-1", "flatten", {"instrument_id": 123})
        )

        self.assertEqual(result, "rejected invalid instrument")

    def test_live_equity_uses_reconciled_broker_balance(self) -> None:
        strategy = PortfolioMomentumStrategy(
            PortfolioMomentumConfig(
                instrument_ids=("AAA.NYSE",),
                signal_bar_types=("AAA.NYSE-1-HOUR-LAST-EXTERNAL",),
                sectors={"AAA": "Test"},
                starting_equity=0,
                use_broker_equity=True,
            )
        )
        account = SimpleNamespace(
            balance_total=lambda _: SimpleNamespace(as_double=lambda: 123_456.78)
        )
        cache = SimpleNamespace(accounts=lambda: (account,))

        with patch.object(
            PortfolioMomentumStrategy,
            "cache",
            new_callable=PropertyMock,
            return_value=cache,
        ):
            equity = strategy._equity()

        self.assertEqual(equity, 123_456.78)


if __name__ == "__main__":
    unittest.main()