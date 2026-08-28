from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.adapters.interactive_brokers.common import IBOrderTags
from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from swing_bot.dashboard_bridge import DashboardBridge, DashboardCommand
from swing_bot.portfolio import (
    CandidateSeries,
    PortfolioSettings,
    build_portfolio_targets,
    build_share_targets,
)
from swing_bot.signals import Bar
from swing_bot.strategy import (
    build_flatten_plan,
    dashboard_position,
    dashboard_trade,
    is_flatten_order,
)

HOUR_NS = 3_600_000_000_000
NEW_YORK = ZoneInfo("America/New_York")
FIRST_COMPLETE_REGULAR_HOUR = 11
LAST_REGULAR_HOUR = 16
REBALANCE_ORDER_TAG = "PORTFOLIO_REBALANCE"
DASHBOARD_TIMER = "dashboard-state"


@dataclass(frozen=True)
class DailyObservation:
    trading_date: date
    close: float
    dollar_volume: float


@dataclass
class DailyAccumulator:
    trading_date: date
    close: float
    dollar_volume: float


class PortfolioMomentumConfig(StrategyConfig, frozen=True):
    instrument_ids: tuple[str, ...]
    signal_bar_types: tuple[str, ...]
    sectors: dict[str, str]
    starting_equity: float
    request_warmup: bool = False
    use_broker_equity: bool = False
    warmup_days: int = 500
    aggregate_hourly_from_minutes: bool = False
    dashboard_runtime_path: str | None = None
    trade_start_ns: int = 0
    portfolio_settings: dict[str, Any] | None = None


class PortfolioMomentumStrategy(Strategy):
    def __init__(self, config: PortfolioMomentumConfig) -> None:
        super().__init__(config)
        self._config = config
        self._settings = PortfolioSettings(**(config.portfolio_settings or {}))
        self._instrument_ids = tuple(
            InstrumentId.from_str(value) for value in config.instrument_ids
        )
        self._signal_bar_types = tuple(
            BarType.from_str(value) for value in config.signal_bar_types
        )
        self._sectors = dict(config.sectors)
        self._last_bar_timestamp: dict[InstrumentId, int] = {}
        self._hourly_accumulators: dict[InstrumentId, tuple[int, Bar]] = {}
        self._latest_marks: dict[InstrumentId, float] = {}
        self._daily_accumulators: dict[InstrumentId, DailyAccumulator] = {}
        self._daily_observations: dict[InstrumentId, list[DailyObservation]] = defaultdict(list)
        self._week_seen: dict[tuple[int, int], set[InstrumentId]] = defaultdict(set)
        self._last_rebalance_week: tuple[int, int] | None = None
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
            consumed = self._consume_bar(data)
            if consumed is not None:
                self._consume_regular_hour(*consumed)

    def on_bar(self, bar: NautilusBar) -> None:
        if bar.bar_type not in self._signal_bar_types:
            return
        consumed = self._consume_bar(bar)
        if consumed is None:
            return
        instrument_id, completed_bar, timestamp_ns = consumed
        local_time = self._consume_regular_hour(instrument_id, completed_bar, timestamp_ns)
        if local_time is None or timestamp_ns < self._config.trade_start_ns:
            return
        if local_time.hour != FIRST_COMPLETE_REGULAR_HOUR:
            return
        iso = local_time.isocalendar()
        week = (iso.year, iso.week)
        if week == self._last_rebalance_week:
            return
        self._week_seen[week].add(instrument_id)
        if not set(self._instrument_ids).issubset(self._week_seen[week]):
            return
        if self._paused:
            return
        self._rebalance()
        self._last_rebalance_week = week
        self._week_seen = defaultdict(set, {week: self._week_seen[week]})

    def on_stop(self) -> None:
        if self._dashboard:
            self.clock.cancel_timer(DASHBOARD_TIMER)
            self._publish_dashboard("stopped")
        for instrument_id in self._instrument_ids:
            self.cancel_all_orders(instrument_id)

    def on_position_closed(self, event: PositionClosed) -> None:
        position = self.cache.position(event.position_id)
        if position is not None and self._dashboard:
            self._dashboard.record_trade(dashboard_trade(position))
            self._publish_dashboard("running")

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
            instrument_id = command.payload.get("instrument_id")
            if instrument_id is not None and (
                not isinstance(instrument_id, str) or not instrument_id
            ):
                return "rejected invalid instrument"
            self._paused = True
            assert self._dashboard is not None
            self._dashboard.paused = True
            submitted = self._submit_flatten_orders(instrument_id)
            return f"submitted {submitted} flatten limit order(s)"
        return "rejected unknown or invalid command"

    def _submit_flatten_orders(self, target_instrument_id: str | None = None) -> int:
        open_orders = self.cache.orders_open(strategy_id=self.id)
        flatten_instruments = {
            order.instrument_id for order in open_orders if is_flatten_order(order)
        }
        for order in open_orders:
            self.cancel_order(order)

        submitted = 0
        outside_rth_tag = IBOrderTags(outsideRth=True).value
        for position in self.cache.positions_open(strategy_id=self.id):
            if target_instrument_id is not None and str(position.instrument_id) != target_instrument_id:
                continue
            if position.instrument_id in flatten_instruments:
                continue
            instrument = self.cache.instrument(position.instrument_id)
            if instrument is None:
                self.log.error(f"Cannot flatten {position.instrument_id}: instrument unavailable")
                continue
            mark_price = self._latest_marks.get(position.instrument_id, position.avg_px_open)
            plan = build_flatten_plan(is_long=position.is_long, mark_price=mark_price)
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
        positions = [
            dashboard_position(position, self._latest_marks.get(position.instrument_id))
            for position in self.cache.positions_open(strategy_id=self.id)
        ]
        self._dashboard.publish(
            timestamp_ns=self.clock.timestamp_ns(),
            equity=self._equity(),
            positions=positions,
            status=status,
        )

    def _consume_bar(self, bar: NautilusBar) -> tuple[InstrumentId, Bar, int] | None:
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
            self._latest_marks[instrument_id] = converted.close
            return instrument_id, converted, bar.ts_event

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
        self._latest_marks[instrument_id] = aggregate.close
        return instrument_id, aggregate, bucket_end_ns

    def _consume_regular_hour(
        self, instrument_id: InstrumentId, bar: Bar, timestamp_ns: int
    ) -> datetime | None:
        local_time = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC).astimezone(
            NEW_YORK
        )
        if not FIRST_COMPLETE_REGULAR_HOUR <= local_time.hour <= LAST_REGULAR_HOUR:
            return None
        trading_date = local_time.date()
        existing = self._daily_accumulators.get(instrument_id)
        if existing is not None and existing.trading_date != trading_date:
            observations = self._daily_observations[instrument_id]
            observations.append(
                DailyObservation(
                    existing.trading_date,
                    existing.close,
                    existing.dollar_volume,
                )
            )
            maximum_history = max(
                self._settings.momentum_lookback + self._settings.momentum_skip + 1,
                self._settings.trend_lookback,
                self._settings.volatility_lookback + 1,
                self._settings.liquidity_lookback,
            )
            del observations[:-maximum_history]
            existing = None
        dollar_volume = bar.close * bar.volume
        if existing is None:
            self._daily_accumulators[instrument_id] = DailyAccumulator(
                trading_date,
                bar.close,
                dollar_volume,
            )
        else:
            existing.close = bar.close
            existing.dollar_volume += dollar_volume
        return local_time

    def _rebalance(self) -> None:
        candidates: list[CandidateSeries] = []
        for instrument_id in self._instrument_ids:
            observations = self._daily_observations[instrument_id]
            if not observations:
                continue
            symbol = str(instrument_id).split(".", 1)[0]
            sector = self._sectors.get(symbol)
            if sector is None:
                self.log.error(f"Sector unavailable: {symbol}")
                return
            liquidity = median(
                observation.dollar_volume
                for observation in observations[-self._settings.liquidity_lookback :]
            )
            candidates.append(
                CandidateSeries(
                    symbol=symbol,
                    sector=sector,
                    closes=tuple(observation.close for observation in observations),
                    median_dollar_volume=liquidity,
                )
            )
        targets = build_portfolio_targets(tuple(candidates), self._settings)
        equity = self._equity()
        if equity is None:
            return

        positions = self.cache.positions_open(strategy_id=self.id)
        positions_by_symbol: dict[str, Any] = {}
        current_shares: dict[str, int] = {}
        for position in positions:
            symbol = str(position.instrument_id).split(".", 1)[0]
            if symbol in positions_by_symbol:
                self.log.error(f"Multiple open positions for {symbol}; rebalance rejected")
                return
            positions_by_symbol[symbol] = position
            if not position.is_long:
                self.close_position(
                    position,
                    tags=[REBALANCE_ORDER_TAG],
                    time_in_force=TimeInForce.IOC,
                )
                continue
            current_shares[symbol] = int(position.quantity.as_double())

        prices = {
            str(instrument_id).split(".", 1)[0]: price
            for instrument_id, price in self._latest_marks.items()
        }
        try:
            share_targets = build_share_targets(
                targets,
                equity=equity,
                prices=prices,
                current_shares=current_shares,
            )
        except ValueError as exc:
            self.log.error(f"Rebalance rejected: {exc}")
            return

        instrument_by_symbol = {
            str(instrument_id).split(".", 1)[0]: instrument_id
            for instrument_id in self._instrument_ids
        }
        for instrument_id in self._instrument_ids:
            self.cancel_all_orders(instrument_id)
        for target in share_targets:
            instrument_id = instrument_by_symbol[target.symbol]
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"Instrument unavailable: {instrument_id}")
                continue
            order = self.order_factory.market(
                instrument_id=instrument_id,
                order_side=OrderSide.BUY if target.delta > 0 else OrderSide.SELL,
                quantity=instrument.make_qty(abs(target.delta)),
                time_in_force=TimeInForce.IOC,
                reduce_only=target.delta < 0,
                tags=[REBALANCE_ORDER_TAG],
            )
            position = positions_by_symbol.get(target.symbol)
            if position is None:
                self.submit_order(order)
            else:
                self.submit_order(order, position_id=position.id)

    def _equity(self) -> float | None:
        currency = Currency.from_str("USD")
        if self._config.use_broker_equity:
            accounts = self.cache.accounts()
            if len(accounts) != 1:
                self.log.error(f"Expected one reconciled broker account, found {len(accounts)}")
                return None
            balance = accounts[0].balance_total(currency)
            if balance is None:
                self.log.error("Broker NetLiquidation balance unavailable for USD")
                return None
            equity = balance.as_double()
        else:
            pnls = self.portfolio.total_pnls(target_currency=currency)
            equity = self._config.starting_equity + sum(
                value.as_double() for value in pnls.values() if value is not None
            )
        if equity <= 0:
            self.log.error("Portfolio equity is unavailable or non-positive")
            return None
        return equity