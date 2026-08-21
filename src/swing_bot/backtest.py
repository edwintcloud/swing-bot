from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from nautilus_trader.analysis.reporter import ReportProvider
from nautilus_trader.backtest.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
    ImportableFeeModelConfig,
    ImportableFillModelConfig,
)
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    DataEngineConfig,
    ImportableStrategyConfig,
    LoggingConfig,
    RiskEngineConfig,
)

from swing_bot.config import RiskSettings, StrategySettings
from swing_bot.contracts import ResolvedContract

BACKTEST_WARMUP_DAYS = 60


def strategy_import_config(
    contracts: Sequence[ResolvedContract],
    strategy: StrategySettings,
    risk: RiskSettings,
    *,
    starting_equity: float,
    request_warmup: bool,
    use_broker_equity: bool = False,
    aggregate_hourly_from_minutes: bool = False,
    dashboard_runtime_path: str | None = None,
    trade_start_ns: int = 0,
) -> ImportableStrategyConfig:
    instrument_ids = tuple(contract.instrument_id for contract in contracts)
    bar_specification = "1-MINUTE-LAST" if aggregate_hourly_from_minutes else "1-HOUR-LAST"
    signal_bar_types = tuple(
        f"{instrument_id}-{bar_specification}-EXTERNAL" for instrument_id in instrument_ids
    )
    return ImportableStrategyConfig(
        strategy_path="swing_bot.strategy:SwingReversalStrategy",
        config_path="swing_bot.strategy:SwingReversalConfig",
        config={
            "instrument_ids": instrument_ids,
            "signal_bar_types": signal_bar_types,
            "starting_equity": starting_equity,
            "request_warmup": request_warmup,
            "use_broker_equity": use_broker_equity,
            "aggregate_hourly_from_minutes": aggregate_hourly_from_minutes,
            "dashboard_runtime_path": dashboard_runtime_path,
            "trade_start_ns": trade_start_ns,
            "strategy_settings": asdict(strategy),
            "risk_settings": asdict(risk),
        },
    )


def build_backtest_config(
    *,
    catalog_path: Path | str,
    contracts: Sequence[ResolvedContract],
    strategy: StrategySettings,
    risk: RiskSettings,
    start: str,
    end: str,
    starting_equity: float = 100_000.0,
) -> BacktestRunConfig:
    if not contracts:
        raise ValueError("Backtest requires at least one resolved contract")
    trade_start = datetime.fromisoformat(start)
    if trade_start.tzinfo is None:
        raise ValueError("Backtest start must include a timezone offset")
    warmup_start = (trade_start - timedelta(days=BACKTEST_WARMUP_DAYS)).isoformat()
    trade_start_ns = int(trade_start.timestamp() * 1_000_000_000)
    path = str(Path(catalog_path).resolve())
    instrument_ids = [contract.instrument_id for contract in contracts]
    data = [
        BacktestDataConfig(
            catalog_path=path,
            data_cls="nautilus_trader.model.data:Bar",
            instrument_ids=instrument_ids,
            bar_spec="1-MINUTE-LAST",
            start_time=warmup_start,
            end_time=end,
        )
    ]
    venue_names = sorted({contract.instrument_id.rsplit(".", 1)[-1] for contract in contracts})
    venue_starting_equity = starting_equity / len(venue_names)
    maximum_order_notional = int(starting_equity * risk.maximum_gross_exposure)
    venues = [
        BacktestVenueConfig(
            name=name,
            oms_type="NETTING",
            account_type="MARGIN",
            base_currency="USD",
            starting_balances=[f"{venue_starting_equity:.2f} USD"],
            book_type="L1_MBP",
            fill_model=ImportableFillModelConfig(
                fill_model_path="nautilus_trader.backtest.models:FillModel",
                config_path="nautilus_trader.backtest.config:FillModelConfig",
                config={
                    "prob_fill_on_limit": 1.0,
                    "prob_slippage": 0.0,
                    "random_seed": 42,
                },
            ),
            fee_model=ImportableFeeModelConfig(
                fee_model_path="nautilus_trader.backtest.models:MakerTakerFeeModel",
                config_path="nautilus_trader.backtest.config:MakerTakerFeeModelConfig",
                config={},
            ),
            bar_execution=True,
            bar_adaptive_high_low_ordering=True,
            use_reduce_only=True,
        )
        for name in venue_names
    ]
    engine = BacktestEngineConfig(
        trader_id="BACKTEST-001",
        strategies=[
            strategy_import_config(
                contracts,
                strategy,
                risk,
                starting_equity=starting_equity,
                request_warmup=False,
                aggregate_hourly_from_minutes=True,
                trade_start_ns=trade_start_ns,
            )
        ],
        risk_engine=RiskEngineConfig(
            bypass=False,
            max_order_submit_rate="20/00:00:01",
            max_order_modify_rate="20/00:00:01",
            max_notional_per_order={
                instrument_id: maximum_order_notional for instrument_id in instrument_ids
            },
        ),
        data_engine=DataEngineConfig(time_bars_timestamp_on_close=True),
        logging=LoggingConfig(log_level="INFO"),
        run_analysis=True,
    )
    return BacktestRunConfig(
        venues=venues,
        data=data,
        engine=engine,
        start=warmup_start,
        end=end,
        raise_exception=True,
        dispose_on_completion=False,
    )


def run_backtest(config: BacktestRunConfig) -> tuple[BacktestNode, list[object]]:
    node = BacktestNode(configs=[config])
    return node, list(node.run())


def write_backtest_reports(
    node: BacktestNode, results: Sequence[object], output_dir: Path | str
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps([asdict(result) for result in results], indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    written = [summary_path]
    html_sections = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Backtest report</title>",
        (
            "<style>body{font:14px sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}"
            "table{border-collapse:collapse;width:100%;margin-bottom:2rem}"
            "th,td{border:1px solid #ccc;padding:.4rem;text-align:right}"
            "th:first-child,td:first-child{text-align:left}</style></head><body>"
        ),
        "<h1>Backtest report</h1><h2>Summary</h2><pre>",
        escape(json.dumps([asdict(result) for result in results], indent=2, sort_keys=True)),
        "</pre>",
    ]
    for index, engine in enumerate(node.get_engines(), start=1):
        prefix = f"run-{index}"
        reports = {
            "orders": ReportProvider.generate_orders_report(engine.cache.orders()),
            "fills": ReportProvider.generate_fills_report(engine.cache.orders()),
            "positions": ReportProvider.generate_positions_report(
                engine.cache.positions(), engine.cache.position_snapshots()
            ),
        }
        accounts = engine.cache.accounts()
        if accounts:
            reports["account"] = ReportProvider.generate_account_report(accounts[0])
        for name, report in reports.items():
            path = output / f"{prefix}-{name}.csv"
            report.to_csv(path)
            written.append(path)
            html_sections.extend([f"<h2>{escape(prefix)} {escape(name)}</h2>", report.to_html()])
    html_sections.append("</body></html>")
    html_path = output / "report.html"
    html_path.write_text("".join(html_sections), encoding="utf-8")
    written.append(html_path)
    return tuple(written)
