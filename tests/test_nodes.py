import unittest
from asyncio import run
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from nautilus_trader.backtest.results import BacktestResult

from swing_bot.backtest import build_backtest_config, write_backtest_reports
from swing_bot.config import RiskSettings, StrategySettings
from swing_bot.contracts import ResolvedContract
from swing_bot.node import (
    LIVE_ACKNOWLEDGEMENT,
    RuntimeSettings,
    build_trading_node_config,
    install_ib_error_notifications,
)

CONTRACT = ResolvedContract("MU", "MU.NASDAQ", 123, "NASDAQ")


class NodeConfigTests(unittest.TestCase):
    def test_ib_disconnect_errors_are_notified_and_still_processed(self) -> None:
        calls: list[int] = []
        messages: list[str] = []

        class FakeIbClient:
            async def process_error(self, **kwargs: object) -> None:
                calls.append(int(kwargs["error_code"]))

        ib_client = FakeIbClient()
        data_client = SimpleNamespace(_client=ib_client)
        node = SimpleNamespace(
            kernel=SimpleNamespace(data_engine=SimpleNamespace(_clients={"IB": data_client}))
        )
        notifier = SimpleNamespace(send=messages.append)
        with patch("swing_bot.node.telegram_notifier", return_value=notifier):
            install_ib_error_notifications(node, "paper")

        run(
            ib_client.process_error(
                req_id=-1,
                error_time=0,
                error_code=1100,
                error_string="Connectivity lost",
            )
        )

        self.assertEqual(calls, [1100])
        self.assertIn("Mode: PAPER", messages[0])
        self.assertIn("IB 1100: Connectivity lost", messages[0])

    def test_report_writer_emits_summary(self) -> None:
        result = BacktestResult(
            "BACKTEST-001", "host", None, "instance", "run", 1, 2, 1, 2, 1.0, 1, 2, 0, 0, {}, {}, {}
        )
        node = type("FakeNode", (), {"get_engines": lambda self: []})()
        with TemporaryDirectory() as directory:
            paths = write_backtest_reports(node, [result], directory)
            self.assertEqual(paths[-1], Path(directory) / "report.html")
            self.assertIn('"trader_id": "BACKTEST-001"', paths[0].read_text())
            self.assertIn("Backtest report", paths[-1].read_text())

    def test_backtest_config_uses_minute_data_for_execution_and_signals(self) -> None:
        config = build_backtest_config(
            catalog_path="catalog",
            contracts=[CONTRACT],
            strategy=StrategySettings(),
            risk=RiskSettings(),
            start="2024-01-01T00:00:00-05:00",
            end="2025-01-01T00:00:00-05:00",
        )
        self.assertEqual(len(config.data), 1)
        self.assertEqual(config.start, "2023-11-02T00:00:00-05:00")
        self.assertEqual(config.data[0].bar_spec, "1-MINUTE-LAST")
        self.assertEqual(config.data[0].start_time, "2023-11-02T00:00:00-05:00")
        strategy_config = config.engine.strategies[0].config
        self.assertEqual(
            strategy_config["signal_bar_types"],
            ("MU.NASDAQ-1-MINUTE-LAST-EXTERNAL",),
        )
        self.assertTrue(strategy_config["aggregate_hourly_from_minutes"])
        self.assertEqual(
            strategy_config["trade_start_ns"],
            int(datetime.fromisoformat("2024-01-01T00:00:00-05:00").timestamp() * 1_000_000_000),
        )
        self.assertEqual(config.venues[0].name, "NASDAQ")
        self.assertEqual(
            config.venues[0].fill_model.fill_model_path,
            "nautilus_trader.backtest.models:FillModel",
        )
        self.assertEqual(config.venues[0].fill_model.config["prob_fill_on_limit"], 1.0)
        self.assertEqual(config.venues[0].fill_model.config["prob_slippage"], 0.0)
        self.assertEqual(
            config.venues[0].fee_model.fee_model_path,
            "nautilus_trader.backtest.models:MakerTakerFeeModel",
        )
        self.assertEqual(config.engine.risk_engine.max_notional_per_order, {"MU.NASDAQ": 30_000})
        self.assertFalse(config.dispose_on_completion)

    def test_paper_mode_defaults_to_gateway_port_4002(self) -> None:
        runtime = RuntimeSettings(
            mode="paper",
            account_id="DU123",
            dashboard_runtime_path="/app/runtime",
        )
        self.assertEqual(runtime.gateway_port, 4002)
        config = build_trading_node_config(
            runtime=runtime,
            contracts=[CONTRACT],
            strategy=StrategySettings(),
            risk=RiskSettings(),
        )
        self.assertIn("INTERACTIVE_BROKERS", config.data_clients)
        self.assertFalse(config.data_clients["INTERACTIVE_BROKERS"].use_regular_trading_hours)
        strategy_config = config.strategies[0].config
        self.assertEqual(
            strategy_config["signal_bar_types"],
            ("MU.NASDAQ-1-HOUR-LAST-EXTERNAL",),
        )
        self.assertTrue(strategy_config["use_broker_equity"])
        self.assertFalse(strategy_config["aggregate_hourly_from_minutes"])
        self.assertEqual(strategy_config["dashboard_runtime_path"], "/app/runtime")
        self.assertEqual(config.risk_engine.max_notional_per_order, {})

    def test_live_mode_requires_acknowledgement(self) -> None:
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            RuntimeSettings(mode="live", account_id="U123")
        runtime = RuntimeSettings(
            mode="live",
            account_id="U123",
            live_acknowledgement=LIVE_ACKNOWLEDGEMENT,
        )
        self.assertEqual(runtime.gateway_port, 4001)

    def test_paper_mode_rejects_live_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "DU"):
            RuntimeSettings(mode="paper", account_id="U123")

    def test_runtime_rejects_placeholder_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "TWS_ACCOUNT"):
            RuntimeSettings(mode="paper", account_id="DU0000000")


if __name__ == "__main__":
    unittest.main()
