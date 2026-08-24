import unittest
from types import SimpleNamespace

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId, PositionId

from swing_bot.config import StrategySettings
from swing_bot.signals import Bar, Signal, SignalEvaluation
from swing_bot.strategy import (
    build_entry_plan,
    build_flatten_plan,
    dashboard_position,
    dashboard_trade,
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

    def test_flatten_plan_uses_one_percent_execution_collar(self) -> None:
        long_plan = build_flatten_plan(is_long=True, mark_price=100)
        short_plan = build_flatten_plan(is_long=False, mark_price=100)
        self.assertEqual(long_plan.order_side, OrderSide.SELL)
        self.assertEqual(long_plan.limit_price, 99)
        self.assertEqual(short_plan.order_side, OrderSide.BUY)
        self.assertEqual(short_plan.limit_price, 101)

    def test_flatten_order_tag_is_distinct_from_entry(self) -> None:
        flatten = type("Order", (), {"tags": ["DASHBOARD_FLATTEN"]})()
        self.assertTrue(is_flatten_order(flatten))
        self.assertFalse(is_entry_order(flatten))

    def test_dashboard_position_serializes_nautilus_identifiers(self) -> None:
        position = SimpleNamespace(
            id=PositionId("P-1"),
            instrument_id=InstrumentId.from_str("NBIS.NASDAQ"),
            quantity=SimpleNamespace(as_double=lambda: 10.0),
            is_long=True,
            entry=OrderSide.BUY,
            avg_px_open=100.0,
            avg_px_close=105.0,
            peak_qty=SimpleNamespace(as_double=lambda: 10.0),
            realized_pnl=SimpleNamespace(as_double=lambda: 50.0),
            ts_opened=1_000_000_000,
            ts_closed=2_000_000_000,
        )

        open_result = dashboard_position(position, 105.0)
        unmarked_result = dashboard_position(position, None)
        closed_result = dashboard_trade(position)

        self.assertEqual(open_result["position_id"], "P-1")
        self.assertEqual(open_result["instrument_id"], "NBIS.NASDAQ")
        self.assertEqual(open_result["unrealized_pnl"], 50.0)
        self.assertEqual(unmarked_result["mark_price"], 100.0)
        self.assertEqual(unmarked_result["unrealized_pnl"], 0.0)
        self.assertEqual(closed_result["position_id"], "P-1")
        self.assertEqual(closed_result["instrument_id"], "NBIS.NASDAQ")


if __name__ == "__main__":
    unittest.main()