from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.adapters.interactive_brokers.common import IBOrderTags
from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.enums import OrderSide, TimeInForce, TrailingOffsetType
from nautilus_trader.model.events import OrderFilled, PositionClosed
from nautilus_trader.model.identifiers import InstrumentId

from swing_bot.acceleration import AccelerationTracker, SessionLossGuard
from swing_bot.config import PriceAccelerationSettings
from swing_bot.risk import calculate_position_size, evaluate_entry_risk
from swing_bot.signals import Signal
from swing_bot.strategy import SwingReversalConfig, SwingReversalStrategy, is_entry_order
from swing_bot.telegram import telegram_notifier, trade_entered_message

ACCELERATION_ENTRY_TAG = "ACCELERATION_ENTRY"
ACCELERATION_TRAILING_STOP_TAG = "ACCELERATION_TRAILING_STOP"
ACCELERATION_FLATLINE_EXIT_TAG = "ACCELERATION_FLATLINE_EXIT"
NEW_YORK = ZoneInfo("America/New_York")
REGULAR_SESSION_START = time(9, 30)
REGULAR_SESSION_END = time(16)


@dataclass(frozen=True)
class AccelerationEntryPlan:
    signal: Signal
    entry_price: float
    initial_stop_price: float


def build_acceleration_entry_plan(
    signal: Signal, entry_price: float, settings: PriceAccelerationSettings
) -> AccelerationEntryPlan | None:
    if signal is Signal.NONE:
        return None
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    entry_signal = Signal.SHORT if signal is Signal.LONG else Signal.LONG
    direction = -1.0 if entry_signal is Signal.LONG else 1.0
    stop = entry_price * (1.0 + direction * settings.trailing_stop_fraction)
    return AccelerationEntryPlan(entry_signal, entry_price, stop)


def is_flatline_exit_order(order: Any) -> bool:
    return ACCELERATION_FLATLINE_EXIT_TAG in (order.tags or [])


def is_regular_session(timestamp_ns: int) -> bool:
    local = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC).astimezone(
        NEW_YORK
    )
    return (
        local.weekday() < 5
        and REGULAR_SESSION_START <= local.time().replace(tzinfo=None) < REGULAR_SESSION_END
    )


def is_entry_session(timestamp_ns: int, market_open_delay_minutes: int) -> bool:
    if not is_regular_session(timestamp_ns):
        return False
    local = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC).astimezone(
        NEW_YORK
    )
    minute_of_day = local.hour * 60 + local.minute
    session_start_minute = (
        REGULAR_SESSION_START.hour * 60 + REGULAR_SESSION_START.minute
    )
    return minute_of_day >= session_start_minute + market_open_delay_minutes


class PriceAccelerationConfig(SwingReversalConfig, frozen=True):
    acceleration_settings: dict[str, Any] | None = None


class PriceAccelerationStrategy(SwingReversalStrategy):
    def __init__(self, config: PriceAccelerationConfig) -> None:
        super().__init__(config)
        self._acceleration_settings = PriceAccelerationSettings(
            **(config.acceleration_settings or {})
        )
        self._strategy_settings = self._acceleration_settings
        self._trackers: dict[InstrumentId, AccelerationTracker] = {}
        self._loss_guard = SessionLossGuard(
            self._acceleration_settings.max_consecutive_losses_per_instrument
        )

    def on_bar(self, bar: NautilusBar) -> None:
        if bar.bar_type not in self._signal_bar_types:
            return
        consumed = self._consume_bar(bar)
        if consumed is None:
            return
        instrument_id, timestamp_ns = consumed
        self._bars[instrument_id] = self._bars[instrument_id][-3:]
        tracker = self._trackers.setdefault(
            instrument_id, AccelerationTracker(self._acceleration_settings)
        )
        if not is_regular_session(timestamp_ns):
            tracker.reset_session()
            return
        positions = self.cache.positions_open(
            instrument_id=instrument_id, strategy_id=self.id
        )
        if not positions and not is_entry_session(
            timestamp_ns, self._acceleration_settings.market_open_delay_minutes
        ):
            tracker.reset_session()
            return
        session_date = datetime.fromtimestamp(
            timestamp_ns / 1_000_000_000, tz=UTC
        ).astimezone(NEW_YORK).date()
        if not positions and not self._loss_guard.entry_allowed(
            str(instrument_id), session_date
        ):
            tracker.reset_session()
            return
        if positions and tracker.position_signal is Signal.NONE:
            tracker.position_opened(Signal.LONG if positions[0].is_long else Signal.SHORT)
        evaluation = tracker.update(bar.close.as_double(), timestamp_ns)
        if positions:
            if evaluation.should_exit:
                self._submit_flatline_exit(instrument_id, positions[0])
            return
        if timestamp_ns < self._config.trade_start_ns or self._paused:
            return
        if self.cache.orders_open(instrument_id=instrument_id, strategy_id=self.id):
            return
        plan = build_acceleration_entry_plan(
            evaluation.signal, bar.close.as_double(), self._acceleration_settings
        )
        if plan is None or not self._update_equity_references(timestamp_ns):
            return
        self._submit_acceleration_entry(instrument_id, plan, timestamp_ns)

    def _submit_acceleration_entry(
        self,
        instrument_id: InstrumentId,
        plan: AccelerationEntryPlan,
        timestamp_ns: int,
    ) -> None:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            self.log.error(f"Instrument unavailable: {instrument_id}")
            return
        snapshot = self._portfolio_snapshot(timestamp_ns)
        if snapshot is None:
            self.log.error("Portfolio marks unavailable; entry rejected")
            return
        size = calculate_position_size(
            equity=snapshot.equity,
            entry_price=plan.entry_price,
            stop_price=plan.initial_stop_price,
            settings=self._risk_settings,
        )
        if size.shares < 1:
            self.log.warning(f"Position size below one share: {instrument_id}")
            return
        decision = evaluate_entry_risk(
            snapshot=snapshot,
            proposed_notional=size.notional,
            is_short=plan.signal is Signal.SHORT,
            settings=self._risk_settings,
        )
        if not decision.allowed:
            self.log.warning(f"Entry rejected for {instrument_id}: {decision.reason}")
            return
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY if plan.signal is Signal.LONG else OrderSide.SELL,
            quantity=instrument.make_qty(size.shares),
            time_in_force=TimeInForce.IOC,
            tags=["ENTRY", ACCELERATION_ENTRY_TAG],
        )
        self.submit_order(order)

    def on_order_filled(self, event: OrderFilled) -> None:
        entry_order = self.cache.order(event.client_order_id)
        if entry_order is None or not is_entry_order(entry_order):
            return
        if event.position_id is None:
            self.log.error(f"Entry fill has no position ID: {event.client_order_id}")
            return
        signal = Signal.LONG if event.order_side is OrderSide.BUY else Signal.SHORT
        tracker = self._trackers.setdefault(
            event.instrument_id, AccelerationTracker(self._acceleration_settings)
        )
        tracker.position_opened(signal)
        outside_rth_tag = IBOrderTags(outsideRth=True).value
        trailing_offset = Decimal(
            str(self._acceleration_settings.trailing_stop_fraction)
        ) * Decimal(10_000)
        stop = self.order_factory.trailing_stop_market(
            instrument_id=event.instrument_id,
            order_side=(
                OrderSide.SELL if event.order_side is OrderSide.BUY else OrderSide.BUY
            ),
            quantity=event.last_qty,
            trailing_offset=trailing_offset,
            trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
            tags=[ACCELERATION_TRAILING_STOP_TAG, outside_rth_tag],
        )
        self.submit_order(stop, position_id=event.position_id)
        notifier = telegram_notifier()
        if notifier:
            notifier.send(
                trade_entered_message(
                    ticker=str(event.instrument_id).split(".", 1)[0],
                    quantity=event.last_qty.as_double(),
                    price=event.last_px.as_double(),
                    equity=self._notification_equity(event.ts_event),
                )
            )

    def _submit_flatline_exit(self, instrument_id: InstrumentId, position: Any) -> None:
        open_orders = self.cache.orders_open(
            instrument_id=instrument_id, strategy_id=self.id
        )
        if any(is_flatline_exit_order(order) for order in open_orders):
            return
        for order in open_orders:
            self.cancel_order(order)
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=OrderSide.SELL if position.is_long else OrderSide.BUY,
            quantity=position.quantity,
            time_in_force=TimeInForce.IOC,
            reduce_only=True,
            tags=[ACCELERATION_FLATLINE_EXIT_TAG],
        )
        self.submit_order(order, position_id=position.id)

    def on_position_closed(self, event: PositionClosed) -> None:
        tracker = self._trackers.get(event.instrument_id)
        if tracker is not None:
            tracker.position_closed(event.ts_event)
        position = self.cache.position(event.position_id)
        if position is not None:
            realized_pnl = position.realized_pnl
            self._loss_guard.record_close(
                str(event.instrument_id),
                datetime.fromtimestamp(
                    event.ts_event / 1_000_000_000, tz=UTC
                ).astimezone(NEW_YORK).date(),
                realized_pnl.as_double() if realized_pnl is not None else 0.0,
            )
        super().on_position_closed(event)