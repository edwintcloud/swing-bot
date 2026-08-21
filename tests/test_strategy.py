import unittest

from nautilus_trader.model.enums import OrderSide

from swing_bot.config import StrategySettings
from swing_bot.signals import Bar, Signal, SignalEvaluation
from swing_bot.strategy import (
    build_entry_plan,
    build_flatten_plan,
    is_entry_order,
    is_flatten_order,
)


class EntryPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = StrategySettings(trailing_stop_fraction=0.05)
        self.bars = [Bar(100, 101, 99, 100)]

    def test_long_plan_uses_fixed_five_percent_initial_stop(self) -> None:
        plan = build_entry_plan(self.bars, SignalEvaluation(Signal.LONG), self.settings)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.entry_price, 100)
        self.assertEqual(plan.initial_stop_price, 95)

    def test_short_plan_uses_fixed_five_percent_initial_stop(self) -> None:
        plan = build_entry_plan(self.bars, SignalEvaluation(Signal.SHORT), self.settings)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.entry_price, 100)
        self.assertEqual(plan.initial_stop_price, 105)

    def test_no_signal_has_no_entry_plan(self) -> None:
        self.assertIsNone(
            build_entry_plan(self.bars, SignalEvaluation(Signal.NONE), self.settings)
        )

    def test_only_entry_orders_are_canceled_on_shutdown(self) -> None:
        entry = type("Order", (), {"tags": ["ENTRY"]})()
        stop = type("Order", (), {"tags": ["TRAILING_STOP"]})()
        self.assertTrue(is_entry_order(entry))
        self.assertFalse(is_entry_order(stop))

    def test_flatten_plan_is_marketable_and_directional(self) -> None:
        long_plan = build_flatten_plan(is_long=True, mark_price=100)
        short_plan = build_flatten_plan(is_long=False, mark_price=100)
        self.assertEqual(long_plan.order_side, OrderSide.SELL)
        self.assertEqual(long_plan.limit_price, 95)
        self.assertEqual(short_plan.order_side, OrderSide.BUY)
        self.assertEqual(short_plan.limit_price, 105)

    def test_flatten_order_tag_is_distinct_from_entry(self) -> None:
        flatten = type("Order", (), {"tags": ["DASHBOARD_FLATTEN"]})()
        self.assertTrue(is_flatten_order(flatten))
        self.assertFalse(is_entry_order(flatten))


if __name__ == "__main__":
    unittest.main()