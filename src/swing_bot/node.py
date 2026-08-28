from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MethodType
from typing import Any

from nautilus_trader.adapters.interactive_brokers.common import IB
from nautilus_trader.adapters.interactive_brokers.config import (
    IBMarketDataTypeEnum,
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
)
from nautilus_trader.adapters.interactive_brokers.factories import (
    InteractiveBrokersLiveDataClientFactory,
    InteractiveBrokersLiveExecClientFactory,
)
from nautilus_trader.config import (
    LiveDataEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    RoutingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode

from swing_bot.backtest import (
    acceleration_strategy_import_config,
    portfolio_strategy_import_config,
    strategy_import_config,
)
from swing_bot.config import PriceAccelerationSettings, RiskSettings, StrategySettings
from swing_bot.contracts import ResolvedContract
from swing_bot.portfolio import PortfolioSettings
from swing_bot.telegram import (
    bot_disconnected_message,
    bot_reconnected_message,
    telegram_notifier,
)

LIVE_ACKNOWLEDGEMENT = "I_UNDERSTAND_LIVE_ORDERS_ARE_REAL"
IB_DIFFERENT_IP_RETRY_SECONDS = 60
IB_DIFFERENT_IP_RECOVERY_GRACE_SECONDS = 15
IB_CLIENT_ID_RELEASE_SECONDS = 2


async def _restart_ib_market_data(ib_client: Any, lock: asyncio.Lock) -> None:
    async with lock:
        await ib_client._stop_async()
        await asyncio.sleep(IB_CLIENT_ID_RELEASE_SECONDS)
        await ib_client._start_async()
        await ib_client.wait_until_ready()
        await ib_client._resubscribe_all()


async def _recover_ib_market_data(ib_client: Any, state: dict[str, Any]) -> None:
    try:
        while state["blocked"] and not getattr(ib_client, "_is_shutting_down", False):
            await asyncio.sleep(IB_DIFFERENT_IP_RETRY_SECONDS)
            if getattr(ib_client, "_is_shutting_down", False):
                return
            state["blocked"] = False
            await _restart_ib_market_data(ib_client, state["lock"])
            await asyncio.sleep(IB_DIFFERENT_IP_RECOVERY_GRACE_SECONDS)
    finally:
        state["task"] = None


@dataclass(frozen=True)
class RuntimeSettings:
    mode: str
    account_id: str
    host: str = "127.0.0.1"
    port: int | None = None
    data_client_id: int = 20
    execution_client_id: int = 30
    live_acknowledgement: str | None = None
    dashboard_runtime_path: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"paper", "live"}:
            raise ValueError("mode must be paper or live")
        if self.account_id in {"", "DU0000000", "U0000000"}:
            raise ValueError("TWS_ACCOUNT must name the account exposed by IB Gateway")
        if self.mode == "paper" and not self.account_id.startswith("DU"):
            raise ValueError("Paper mode requires a DU account")
        if self.mode == "live":
            if self.account_id.startswith("DU"):
                raise ValueError("Live mode cannot use a DU account")
            if self.live_acknowledgement != LIVE_ACKNOWLEDGEMENT:
                raise ValueError("Live mode acknowledgement is missing")
        if self.data_client_id == self.execution_client_id:
            raise ValueError("Data and execution client IDs must differ")

    @property
    def gateway_port(self) -> int:
        return self.port or (4002 if self.mode == "paper" else 4001)


def runtime_from_environment(environment: Mapping[str, str] | None = None) -> RuntimeSettings:
    values = os.environ if environment is None else environment
    return RuntimeSettings(
        mode=values.get("TRADING_MODE", "paper"),
        account_id=values.get("TWS_ACCOUNT", ""),
        host=values.get("IB_HOST", "127.0.0.1"),
        port=int(values["IB_PORT"]) if values.get("IB_PORT") else None,
        data_client_id=int(values.get("IB_DATA_CLIENT_ID", "20")),
        execution_client_id=int(values.get("IB_EXEC_CLIENT_ID", "30")),
        live_acknowledgement=values.get("LIVE_TRADING_ACK"),
        dashboard_runtime_path=values.get("DASHBOARD_RUNTIME_PATH"),
    )


def build_trading_node_config(
    *,
    runtime: RuntimeSettings,
    contracts: Sequence[ResolvedContract],
    strategy: StrategySettings,
    risk: RiskSettings,
    portfolio: PortfolioSettings | None = None,
    sectors: dict[str, str] | None = None,
    strategy_name: str = "sma-continuation",
    acceleration: PriceAccelerationSettings | None = None,
) -> TradingNodeConfig:
    if not contracts:
        raise ValueError("Trading node requires resolved contracts")
    provider = InteractiveBrokersInstrumentProviderConfig(
        load_contracts=frozenset(contract.as_ib_contract() for contract in contracts),
        cache_validity_days=1,
    )
    data_config = InteractiveBrokersDataClientConfig(
        instrument_provider=provider,
        ibg_host=runtime.host,
        ibg_port=runtime.gateway_port,
        ibg_client_id=runtime.data_client_id,
        use_regular_trading_hours=strategy_name == "price-acceleration",
        market_data_type=IBMarketDataTypeEnum.REALTIME,
        handle_revised_bars=True,
        connection_timeout=300,
        request_timeout_secs=120,
    )
    exec_config = InteractiveBrokersExecClientConfig(
        instrument_provider=provider,
        ibg_host=runtime.host,
        ibg_port=runtime.gateway_port,
        ibg_client_id=runtime.execution_client_id,
        account_id=runtime.account_id,
        routing=RoutingConfig(default=True),
        connection_timeout=300,
        request_timeout_secs=120,
        fetch_all_open_orders=True,
    )
    return TradingNodeConfig(
        trader_id="SWING-001",
        strategies=[
            acceleration_strategy_import_config(
                contracts,
                acceleration,
                risk,
                starting_equity=0.0,
                use_broker_equity=True,
                dashboard_runtime_path=runtime.dashboard_runtime_path,
                claim_external_orders=True,
            )
            if strategy_name == "price-acceleration" and acceleration is not None
            else portfolio_strategy_import_config(
                contracts,
                portfolio,
                sectors or {},
                starting_equity=0.0,
                request_warmup=True,
                use_broker_equity=True,
                aggregate_hourly_from_minutes=False,
                dashboard_runtime_path=runtime.dashboard_runtime_path,
                claim_external_orders=True,
            )
            if portfolio is not None
            else strategy_import_config(
                contracts,
                strategy,
                risk,
                starting_equity=0.0,
                request_warmup=True,
                use_broker_equity=True,
                dashboard_runtime_path=runtime.dashboard_runtime_path,
                claim_external_orders=True,
            )
        ],
        data_clients={IB: data_config},
        exec_clients={IB: exec_config},
        data_engine=LiveDataEngineConfig(
            time_bars_timestamp_on_close=False,
            validate_data_sequence=True,
            graceful_shutdown_on_exception=True,
        ),
        risk_engine=LiveRiskEngineConfig(
            bypass=False,
            max_order_submit_rate="20/00:00:01",
            max_order_modify_rate="20/00:00:01",
            graceful_shutdown_on_exception=True,
        ),
        logging=LoggingConfig(
            log_level="INFO",
            log_level_file="INFO",
            log_directory="logs",
            log_file_format="JSON",
        ),
        timeout_connection=90.0,
        timeout_reconciliation=30.0,
        timeout_portfolio=30.0,
        timeout_disconnection=10.0,
        timeout_post_stop=5.0,
    )


def build_trading_node(config: TradingNodeConfig) -> TradingNode:
    node = TradingNode(config=config)
    node.add_data_client_factory(IB, InteractiveBrokersLiveDataClientFactory)
    node.add_exec_client_factory(IB, InteractiveBrokersLiveExecClientFactory)
    node.build()
    return node


def install_ib_error_notifications(node: TradingNode, mode: str) -> None:
    notifier = telegram_notifier()
    clients = node.kernel.data_engine._clients.values()
    for data_client in clients:
        ib_client = getattr(data_client, "_client", None)
        if ib_client is None:
            continue
        original = ib_client.process_error
        connection_state = {"disconnected": False}
        recovery_lock = asyncio.Lock()
        different_ip_state: dict[str, Any] = {
            "blocked": False,
            "task": None,
            "lock": recovery_lock,
        }

        if hasattr(ib_client, "_resubscribe_after_farm_recovery"):
            async def recover_after_farm(
                self: Any, _recovery_lock: asyncio.Lock = recovery_lock
            ) -> None:
                try:
                    await _restart_ib_market_data(self, _recovery_lock)
                finally:
                    self._data_farm_degraded_since_ns = None

            ib_client._resubscribe_after_farm_recovery = MethodType(
                recover_after_farm, ib_client
            )

        async def process_error(
            self: Any,
            *,
            req_id: int,
            error_time: int,
            error_code: int,
            error_string: str,
            advanced_order_reject_json: str = "",
            _original: Any = original,
            _state: dict[str, bool] = connection_state,
            _different_ip_state: dict[str, Any] = different_ip_state,
        ) -> None:
            full_disconnect = error_code in {1100, 1300, 2110}
            reconnected = error_code in {1101, 1102}
            if full_disconnect and not _state["disconnected"]:
                _state["disconnected"] = True
                if notifier is not None:
                    notifier.send(
                        bot_disconnected_message(mode, f"IB {error_code}: {error_string}")
                    )
            elif reconnected and _state["disconnected"]:
                _state["disconnected"] = False
                if notifier is not None:
                    notifier.send(
                        bot_reconnected_message(mode, f"IB {error_code}: {error_string}")
                    )
            await _original(
                req_id=req_id,
                error_time=error_time,
                error_code=error_code,
                error_string=error_string,
                advanced_order_reject_json=advanced_order_reject_json,
            )
            different_ip = (
                error_code in {162, 420} and "different IP address" in error_string
            )
            if different_ip:
                _different_ip_state["blocked"] = True
                task = _different_ip_state["task"]
                if task is None or task.done():
                    _different_ip_state["task"] = self._create_task(
                        _recover_ib_market_data(self, _different_ip_state)
                    )

        ib_client.process_error = MethodType(process_error, ib_client)
