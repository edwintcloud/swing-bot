from __future__ import annotations

import argparse
import asyncio
import json
import signal
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from nautilus_trader.adapters.interactive_brokers.historical.client import (
    HistoricInteractiveBrokersClient,
)
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from swing_bot.backtest import build_backtest_config, run_backtest, write_backtest_reports
from swing_bot.config import (
    load_config,
    load_portfolio_config,
    load_price_acceleration_config,
)
from swing_bot.contracts import (
    discover_contracts,
    load_resolved_contracts,
    save_resolved_contracts,
    select_resolved_contracts,
)
from swing_bot.data import (
    bar_to_record,
    build_manifest,
    complete_hmds_no_data_requests,
    download_history,
    validate_bar_records,
    write_manifest,
)
from swing_bot.node import (
    build_trading_node,
    build_trading_node_config,
    install_ib_error_notifications,
    runtime_from_environment,
)
from swing_bot.telegram import (
    bot_started_message,
    bot_stopped_message,
    close_telegram,
    configure_telegram,
)

STRATEGY_CHOICES = ("sma-continuation", "portfolio-momentum", "price-acceleration")


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO-8601 datetime: {value}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Datetime must include a timezone offset")
    return parsed


def _historical_client(host: str, port: int, client_id: int) -> HistoricInteractiveBrokersClient:
    client = HistoricInteractiveBrokersClient(host=host, port=port, client_id=client_id)
    complete_hmds_no_data_requests(client)
    return client


def _discover(args: argparse.Namespace) -> None:
    app = load_config(args.config_dir)
    contracts = asyncio.run(
        discover_contracts(
            app.symbols,
            lambda: _historical_client(args.host, args.port, args.client_id),
        )
    )
    save_resolved_contracts(contracts, args.output)
    print(f"Resolved {len(contracts)} contracts to {args.output}")


def _download(args: argparse.Namespace) -> None:
    contracts = load_resolved_contracts(args.contracts)
    instruments, bars = asyncio.run(
        download_history(
            contracts=contracts,
            start=args.start,
            end=args.end,
            catalog_path=args.catalog,
            client_factory=lambda: _historical_client(args.host, args.port, args.client_id),
            timeout=args.timeout,
            minute_chunk_days=args.minute_chunk_days,
            hourly_chunk_days=args.hourly_chunk_days,
            include_second_bars=args.include_second_bars,
            second_chunk_minutes=args.second_chunk_minutes,
            retries=args.retries,
        )
    )
    print(f"Wrote {len(instruments)} instruments and {len(bars)} bars to {args.catalog}")


def _validate(args: argparse.Namespace) -> None:
    catalog = ParquetDataCatalog(Path(args.catalog).resolve())
    bars = catalog.bars()
    records = [bar_to_record(bar) for bar in bars]
    counts = validate_bar_records(records)
    if args.start and args.end:
        from nautilus_trader import __version__ as nautilus_version

        write_manifest(
            build_manifest(
                records, start=args.start, end=args.end, nautilus_version=nautilus_version
            ),
            Path(args.catalog) / "manifest.json",
        )
    print(json.dumps(counts, indent=2, sort_keys=True))


def _backtest(args: argparse.Namespace) -> None:
    app = load_config(args.config_dir)
    acceleration = (
        load_price_acceleration_config(args.config_dir)
        if args.strategy == "price-acceleration"
        else None
    )
    contracts = select_resolved_contracts(
        load_resolved_contracts(args.contracts), app.symbols
    )
    portfolio_config = (
        load_portfolio_config(app.symbols, args.config_dir)
        if args.strategy == "portfolio-momentum"
        else None
    )
    config = build_backtest_config(
        catalog_path=args.catalog,
        contracts=contracts,
        strategy=app.strategy,
        risk=app.risk,
        start=args.start.isoformat(),
        end=args.end.isoformat(),
        starting_equity=args.starting_equity,
        portfolio=portfolio_config.settings if portfolio_config else None,
        sectors=portfolio_config.sectors if portfolio_config else None,
        strategy_name=args.strategy,
        acceleration=acceleration,
    )
    node, results = run_backtest(config)
    try:
        paths = write_backtest_reports(node, results, args.output)
        print("\n".join(str(path) for path in paths))
    finally:
        node.dispose()


def _connectivity(args: argparse.Namespace) -> None:
    app = load_config(args.config_dir)

    async def probe() -> int:
        client = _historical_client(args.host, args.port, args.client_id)
        contracts = await discover_contracts(app.symbols, lambda: client)
        return len(contracts)

    count = asyncio.run(probe())
    print(f"IB connectivity OK; resolved {count} configured symbols")


def _trade(args: argparse.Namespace) -> None:
    app = load_config(args.config_dir)
    acceleration = (
        load_price_acceleration_config(args.config_dir)
        if args.strategy == "price-acceleration"
        else None
    )
    portfolio_config = (
        load_portfolio_config(app.symbols, args.config_dir)
        if args.strategy == "portfolio-momentum"
        else None
    )
    runtime = runtime_from_environment()
    if runtime.mode != args.command:
        raise ValueError(f"TRADING_MODE must be {args.command} for this command")
    contracts = select_resolved_contracts(
        load_resolved_contracts(args.contracts), app.symbols
    )
    config = build_trading_node_config(
        runtime=runtime,
        contracts=contracts,
        strategy=app.strategy,
        risk=app.risk,
        portfolio=portfolio_config.settings if portfolio_config else None,
        sectors=portfolio_config.sectors if portfolio_config else None,
        strategy_name=args.strategy,
        acceleration=acceleration,
    )
    notifier = configure_telegram()
    node = None
    stop_requested = False
    stop_reason = "trading node stopped"

    def request_stop(signum: int, _: object) -> None:
        nonlocal stop_reason, stop_requested
        if not stop_requested:
            stop_requested = True
            stop_reason = signal.Signals(signum).name
            if node is not None:
                node.stop()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        node = build_trading_node(config)
        install_ib_error_notifications(node, runtime.mode)
        if notifier:
            notifier.send(bot_started_message(runtime.mode))
        node.run(raise_exception=True)
    except BaseException as exc:
        stop_reason = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if notifier:
            notifier.send(bot_stopped_message(runtime.mode, stop_reason))
        try:
            if node is not None:
                node.dispose()
        finally:
            close_telegram()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swing-bot")
    parser.add_argument("--config-dir", default="config")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_connection(command: argparse.ArgumentParser) -> None:
        command.add_argument("--host", default="127.0.0.1")
        command.add_argument("--port", type=int, default=4002)
        command.add_argument("--client-id", type=int, default=10)

    discover = subparsers.add_parser("discover-contracts")
    add_connection(discover)
    discover.add_argument("--output", default="data/contracts.json")
    discover.set_defaults(handler=_discover)

    download = subparsers.add_parser("download-data")
    add_connection(download)
    download.add_argument("--contracts", default="data/contracts.json")
    download.add_argument("--catalog", default="data/catalog")
    download.add_argument("--start", type=_datetime, required=True)
    download.add_argument("--end", type=_datetime, required=True)
    download.add_argument("--timeout", type=int, default=120)
    download.add_argument("--minute-chunk-days", "--chunk-days", type=int, default=30)
    download.add_argument("--hourly-chunk-days", type=int, default=30)
    download.add_argument("--include-second-bars", action="store_true")
    download.add_argument("--second-chunk-minutes", type=int, default=30)
    download.add_argument("--retries", type=int, default=3)
    download.set_defaults(handler=_download)

    validate = subparsers.add_parser("validate-data")
    validate.add_argument("--catalog", default="data/catalog")
    validate.add_argument("--start", type=_datetime)
    validate.add_argument("--end", type=_datetime)
    validate.set_defaults(handler=_validate)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--contracts", default="data/contracts.json")
    backtest.add_argument("--catalog", default="data/catalog")
    backtest.add_argument("--start", type=_datetime, required=True)
    backtest.add_argument("--end", type=_datetime, required=True)
    backtest.add_argument("--starting-equity", type=float, default=100_000.0)
    backtest.add_argument("--output", default="reports/latest")
    backtest.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default="sma-continuation",
    )
    backtest.set_defaults(handler=_backtest)

    connectivity = subparsers.add_parser("connectivity")
    add_connection(connectivity)
    connectivity.set_defaults(handler=_connectivity)

    dashboard = subparsers.add_parser("dashboard")
    dashboard.add_argument("--runtime-dir", default="runtime")
    dashboard.add_argument("--host", default="0.0.0.0")
    dashboard.add_argument("--port", type=int, default=8080)
    dashboard.set_defaults(
        handler=lambda args: __import__("swing_bot.dashboard", fromlist=["main"]).main(
            ["--runtime-dir", args.runtime_dir, "--host", args.host, "--port", str(args.port)]
        )
    )

    for name in ("paper", "live"):
        trade = subparsers.add_parser(name)
        trade.add_argument("--contracts", default="data/contracts.json")
        trade.add_argument("--strategy", choices=STRATEGY_CHOICES, default="sma-continuation")
        trade.set_defaults(handler=_trade)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
