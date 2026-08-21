from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nautilus_trader.adapters.interactive_brokers.common import IBOrderTags
from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce, TrailingOffsetType
from nautilus_trader.model.events import OrderFilled, PositionClosed
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from swing_bot.config import RiskSettings, StrategySettings
from swing_bot.dashboard_bridge import DashboardBridge, DashboardCommand
from swing_bot.risk import (
    EquityReferences,
    PortfolioSnapshot,
    calculate_position_size,
    evaluate_entry_risk,
)
from swing_bot.signals import Bar, Signal, SignalEvaluation, evaluate_latest
from swing_bot.telegram import telegram_notifier, trade_closed_message, trade_entered_message

HOUR_NS = 3_600_000_000_000
DASHBOARD_TIMER = "dashboard-state"
FLATTEN_LIMIT_OFFSET = 0.05


@dataclass(frozen=True)
class EntryPlan:
    signal: Signal
    entry_price: float
    initial_stop_price: float


@dataclass(frozen=True)
class FlattenPlan:
    order_side: OrderSide
    limit_price: float


def build_entry_plan(
    bars: Sequence[Bar], evaluation: SignalEvaluation, settings: StrategySettings
) -> EntryPlan | None:
    if evaluation.signal is Signal.NONE:
        return None
    entry = bars[-1].close
    if evaluation.signal is Signal.LONG:
        stop = entry * (1.0 - settings.trailing_stop_fraction)
    else:
        stop = entry * (1.0 + settings.trailing_stop_fraction)
    return EntryPlan(evaluation.signal, entry, stop)


def is_entry_order(order: Any) -> bool:
    return "ENTRY" in (order.tags or [])


def is_flatten_order(order: Any) -> bool:
    return "DASHBOARD_FLATTEN" in (order.tags or [])


def build_flatten_plan(*, is_long: bool, mark_price: float) -> FlattenPlan:
    if mark_price <= 0:
        raise ValueError("mark_price must be positive")
    if is_long:
        return FlattenPlan(OrderSide.SELL, mark_price * (1.0 - FLATTEN_LIMIT_OFFSET))
    return FlattenPlan(OrderSide.BUY, mark_price * (1.0 + FLATTEN_LIMIT_OFFSET))


def dashboard_position(position: Any, mark_price: float) -> dict[str, Any]:
    quantity = position.quantity.as_double()
    direction = 1.0 if position.is_long else -1.0
    return {
        "position_id": position.id.to_str(),
        "instrument_id": position.instrument_id.to_str(),
        "side": "LONG" if position.is_long else "SHORT",
        "quantity": quantity,
        "avg_px_open": position.avg_px_open,
        "mark_price": mark_price,
        "unrealized_pnl": (mark_price - position.avg_px_open) * quantity * direction,
        "opened_at": datetime.fromtimestamp(
            position.ts_opened / 1_000_000_000, tz=UTC
        ).isoformat(),
    }


def dashboard_trade(position: Any) -> dict[str, Any]:
    realized_pnl = position.realized_pnl
    return {
        "position_id": position.id.to_str(),
        "instrument_id": position.instrument_id.to_str(),
        "side": "LONG" if position.entry is OrderSide.BUY else "SHORT",
        "quantity": position.peak_qty.as_double(),
        "avg_px_open": position.avg_px_open,
        "avg_px_close": position.avg_px_close,
        "realized_pnl": realized_pnl.as_double() if realized_pnl is not None else 0.0,
        "opened_at": datetime.fromtimestamp(
            position.ts_opened / 1_000_000_000, tz=UTC
        ).isoformat(),
        "closed_at": datetime.fromtimestamp(
            position.ts_closed / 1_000_000_000, tz=UTC
        ).isoformat(),
    }


class SwingReversalConfig(StrategyConfig, frozen=True):
    instrument_ids: tuple[str, ...]
    signal_bar_types: tuple[str, ...]
    starting_equity: float = 0.0
    warmup_days: int = 60
    request_warmup: bool = True
    use_broker_equity: bool = False
    aggregate_hourly_from_minutes: bool = False
    dashboard_runtime_path: str | None = None
    trade_start_ns: int = 0
    strategy_settings: dict[str, Any] | None = None
    risk_settings: dict[str, Any] | None = None


class SwingReversalStrategy(Strategy):
    def __init__(self, config: SwingReversalConfig) -> None:
        super().__init__(config)
        self._config = config
        self._strategy_settings = StrategySettings(**(config.strategy_settings or {}))
        self._risk_settings = RiskSettings(**(config.risk_settings or {}))
        self._bars: dict[InstrumentId, list[Bar]] = defaultdict(list)
        self._last_bar_timestamp: dict[InstrumentId, int] = {}
        self._hourly_accumulators: dict[InstrumentId, tuple[int, Bar]] = {}
        self._signal_bar_types = tuple(
            BarType.from_str(value) for value in config.signal_bar_types
        )
        self._equity_references: EquityReferences | None = None
        self._dashboard = (
            DashboardBridge(config.dashboard_runtime_path)
            if config.dashboard_runtime_path
            else None
        )
        self._paused = self._dashboard.paused if self._dashboard else False

    def on_start(self) -> None:
        if self._dashboard:
            self.clock.set_timer(
                name=DASHBOARD_TIMER,
                interval=timedelta(seconds=5),
                callback=self._on_dashboard_timer,
            )
            self._publish_dashboard("running")
        for bar_type in self._signal_bar_types:
            if self._config.request_warmup:
                self.request_bars(
                    bar_type,
                    start=self.clock.utc_now() - timedelta(days=self._config.warmup_days),
                    callback=lambda _, selected=bar_type: self.subscribe_bars(selected),
                )
            else:
                self.subscribe_bars(bar_type)

    def on_historical_data(self, data: Any) -> None:
        if isinstance(data, NautilusBar):
            self._consume_bar(data)

    def on_bar(self, bar: NautilusBar) -> None:
        if bar.bar_type not in self._signal_bar_types:
            return
        consumed = self._consume_bar(bar)
        if consumed is None:
            return
        instrument_id, timestamp_ns = consumed
        if timestamp_ns < self._config.trade_start_ns:
            return
        if not self._update_equity_references(timestamp_ns):
            return
        if self._paused:
            return
        open_positions = self.cache.positions_open(instrument_id=instrument_id, strategy_id=self.id)
        if open_positions:
            return
        if self.cache.orders_open(instrument_id=instrument_id, strategy_id=self.id):
            return

        bars = self._bars[instrument_id]
        evaluation = evaluate_latest(bars, self._strategy_settings)
        plan = build_entry_plan(bars, evaluation, self._strategy_settings)
        if plan is None:
            return
        self._submit_plan(instrument_id, plan, timestamp_ns)

    def on_stop(self) -> None:
        if self._dashboard:
            self.clock.cancel_timer(DASHBOARD_TIMER)
            self._publish_dashboard("stopped")
        for order in self.cache.orders_open(strategy_id=self.id):
            if is_entry_order(order):
                self.cancel_order(order)

    def _consume_bar(self, bar: NautilusBar) -> tuple[InstrumentId, int] | None:
        instrument_id = bar.bar_type.instrument_id
        if self._last_bar_timestamp.get(instrument_id) == bar.ts_init:
            return None
        self._last_bar_timestamp[instrument_id] = bar.ts_init
        converted = Bar(
            open=bar.open.as_double(),
            high=bar.high.as_double(),
            low=bar.low.as_double(),
            close=bar.close.as_double(),
            volume=bar.volume.as_double(),
        )
        if not self._config.aggregate_hourly_from_minutes:
            self._bars[instrument_id].append(converted)
            return instrument_id, bar.ts_event

        bucket_end_ns = ((bar.ts_init - 1) // HOUR_NS + 1) * HOUR_NS
        existing = self._hourly_accumulators.get(instrument_id)
        if existing is None or existing[0] != bucket_end_ns:
            aggregate = converted
        else:
            previous = existing[1]
            aggregate = Bar(
                open=previous.open,
                high=max(previous.high, converted.high),
                low=min(previous.low, converted.low),
                close=converted.close,
                volume=previous.volume + converted.volume,
            )
        if bar.ts_init != bucket_end_ns:
            self._hourly_accumulators[instrument_id] = (bucket_end_ns, aggregate)
            return None
        self._hourly_accumulators.pop(instrument_id, None)
        self._bars[instrument_id].append(aggregate)
        return instrument_id, bucket_end_ns

    def _submit_plan(
        self, instrument_id: InstrumentId, plan: EntryPlan, timestamp_ns: int
    ) -> None:
        if self._paused:
            return
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
        side = OrderSide.BUY if plan.signal is Signal.LONG else OrderSide.SELL
        outside_rth_tag = IBOrderTags(outsideRth=True).value
        order = self.order_factory.limit(
            instrument_id=instrument_id,
            order_side=side,
            quantity=instrument.make_qty(size.shares),
            price=instrument.make_price(plan.entry_price),
            time_in_force=TimeInForce.GTC,
            tags=["ENTRY", outside_rth_tag],
        )
        self.submit_order(order)

    def on_order_filled(self, event: OrderFilled) -> None:
        entry_order = self.cache.order(event.client_order_id)
        if entry_order is None or not is_entry_order(entry_order):
            return
        if event.position_id is None:
            self.log.error(f"Entry fill has no position ID: {event.client_order_id}")
            return
        outside_rth_tag = IBOrderTags(outsideRth=True).value
        trailing_offset = Decimal(str(self._strategy_settings.trailing_stop_fraction)) * Decimal(
            10_000
        )
        stop = self.order_factory.trailing_stop_market(
            instrument_id=event.instrument_id,
            order_side=(OrderSide.SELL if event.order_side is OrderSide.BUY else OrderSide.BUY),
            quantity=event.last_qty,
            trailing_offset=trailing_offset,
            trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
            tags=["TRAILING_STOP", outside_rth_tag],
        )
        self.submit_order(stop, position_id=event.position_id)
        notifier = telegram_notifier()
        if notifier:
            quantity = event.last_qty.as_double()
            price = event.last_px.as_double()
            notifier.send(
                trade_entered_message(
                    ticker=str(event.instrument_id).split(".", 1)[0],
                    quantity=quantity,
                    price=price,
                    equity=self._notification_equity(event.ts_event),
                )
            )

    def on_position_closed(self, event: PositionClosed) -> None:
        position = self.cache.position(event.position_id)
        if position is not None and self._dashboard:
            self._dashboard.record_trade(dashboard_trade(position))
        if self._dashboard:
            self._publish_dashboard("running")
        notifier = telegram_notifier()
        if position is not None and notifier:
            realized_pnl = position.realized_pnl
            notifier.send(
                trade_closed_message(
                    ticker=str(position.instrument_id).split(".", 1)[0],
                    quantity=position.peak_qty.as_double(),
                    price=position.avg_px_close,
                    entry_price=position.avg_px_open,
                    profit=realized_pnl.as_double() if realized_pnl is not None else 0.0,
                    equity=self._notification_equity(event.ts_event),
                )
            )

    def _on_dashboard_timer(self, _: Any) -> None:
        if not self._dashboard:
            return
        for command in self._dashboard.read_commands():
            result = self._process_dashboard_command(command)
            self._dashboard.acknowledge(command, result)
        self._publish_dashboard("running")

    def _process_dashboard_command(self, command: DashboardCommand) -> str:
        if command.action == "set_paused" and isinstance(command.payload.get("paused"), bool):
            self._paused = command.payload["paused"]
            assert self._dashboard is not None
            self._dashboard.paused = self._paused
            return "entries paused" if self._paused else "entries resumed"
        if command.action == "flatten":
            self._paused = True
            assert self._dashboard is not None
            self._dashboard.paused = True
            submitted = self._submit_flatten_orders()
            return f"submitted {submitted} flatten limit order(s)"
        return "rejected unknown or invalid command"

    def _submit_flatten_orders(self) -> int:
        open_orders = self.cache.orders_open(strategy_id=self.id)
        flatten_instruments = {
            order.instrument_id for order in open_orders if is_flatten_order(order)
        }
        for order in open_orders:
            if is_entry_order(order):
                self.cancel_order(order)

        submitted = 0
        outside_rth_tag = IBOrderTags(outsideRth=True).value
        for position in self.cache.positions_open(strategy_id=self.id):
            if position.instrument_id in flatten_instruments:
                continue
            marks = self._bars.get(position.instrument_id)
            instrument = self.cache.instrument(position.instrument_id)
            if not marks or instrument is None:
                self.log.error(f"Cannot flatten {position.instrument_id}: mark unavailable")
                continue
            plan = build_flatten_plan(is_long=position.is_long, mark_price=marks[-1].close)
            for order in open_orders:
                if order.instrument_id == position.instrument_id and not is_entry_order(order):
                    self.cancel_order(order)
            order = self.order_factory.limit(
                instrument_id=position.instrument_id,
                order_side=plan.order_side,
                quantity=position.quantity,
                price=instrument.make_price(plan.limit_price),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
                tags=["DASHBOARD_FLATTEN", outside_rth_tag],
            )
            self.submit_order(order, position_id=position.id)
            submitted += 1
        return submitted

    def _publish_dashboard(self, status: str) -> None:
        if not self._dashboard:
            return
        timestamp_ns = self.clock.timestamp_ns()
        equity = None
        if self._update_equity_references(timestamp_ns) and self._equity_references:
            equity = self._equity_references.equity
        positions: list[dict[str, Any]] = []
        for position in self.cache.positions_open(strategy_id=self.id):
            marks = self._bars.get(position.instrument_id)
            if marks:
                positions.append(dashboard_position(position, marks[-1].close))
        self._dashboard.publish(
            timestamp_ns=timestamp_ns,
            equity=equity,
            positions=positions,
            status=status,
        )

    def _portfolio_snapshot(self, timestamp_ns: int) -> PortfolioSnapshot | None:
        if not self._update_equity_references(timestamp_ns):
            return None
        references = self._equity_references
        if references is None:
            return None
        equity = references.equity

        gross_notional = 0.0
        short_notional = 0.0
        positions = self.cache.positions_open(strategy_id=self.id)
        for position in positions:
            marks = self._bars.get(position.instrument_id)
            if not marks:
                return None
            notional = position.quantity.as_double() * marks[-1].close
            gross_notional += notional
            if position.is_short:
                short_notional += notional
        return PortfolioSnapshot(
            equity=references.equity,
            day_start_equity=references.day_start_equity,
            week_start_equity=references.week_start_equity,
            high_water_equity=references.high_water_equity,
            gross_exposure=gross_notional / equity,
            short_exposure=short_notional / equity,
            open_positions=len(positions),
        )

    def _update_equity_references(self, timestamp_ns: int) -> bool:
        currency = Currency.from_str("USD")
        if self._config.use_broker_equity:
            accounts = self.cache.accounts()
            if len(accounts) != 1:
                self.log.error(
                    f"Expected one reconciled broker account, found {len(accounts)}"
                )
                return False
            balance = accounts[0].balance_total(currency)
            if balance is None:
                self.log.error("Broker NetLiquidation balance unavailable for USD")
                return False
            equity = balance.as_double()
        else:
            pnls = self.portfolio.total_pnls(target_currency=currency)
            equity = self._config.starting_equity + sum(
                value.as_double() for value in pnls.values() if value is not None
            )
        timestamp = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC)
        if self._equity_references is None:
            self._equity_references = EquityReferences.initialize(equity, timestamp)
        else:
            self._equity_references.update(
                equity,
                timestamp,
                track_high_water=not self.cache.positions_open(strategy_id=self.id),
            )
        return True

    def _notification_equity(self, timestamp_ns: int) -> float | None:
        if not self._update_equity_references(timestamp_ns):
            return None
        return self._equity_references.equity if self._equity_references else None
