import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from swing_bot.dashboard_bridge import DashboardBridge, dashboard_payload, enqueue_command


class DashboardBridgeTests(unittest.TestCase):
    def test_command_round_trip_and_pause_persistence(self) -> None:
        with TemporaryDirectory() as directory:
            command_id = enqueue_command(directory, "set_paused", {"paused": True})
            bridge = DashboardBridge(directory)
            commands = bridge.read_commands()
            self.assertEqual(commands[0].command_id, command_id)
            self.assertEqual(commands[0].payload, {"paused": True})
            bridge.paused = True
            bridge.acknowledge(commands[0], "entries paused")
            bridge.publish(timestamp_ns=60_000_000_000, equity=100_000, positions=[], status="running")
            self.assertTrue(DashboardBridge(directory).paused)

    def test_equity_is_sampled_once_per_minute_and_trades_are_deduplicated(self) -> None:
        with TemporaryDirectory() as directory:
            bridge = DashboardBridge(directory)
            bridge.publish(timestamp_ns=60_000_000_000, equity=100_000, positions=[], status="running")
            bridge.publish(timestamp_ns=61_000_000_000, equity=100_100, positions=[], status="running")
            bridge.publish(timestamp_ns=120_000_000_000, equity=100_200, positions=[], status="running")
            trade = {"position_id": "P-1", "realized_pnl": 200}
            bridge.record_trade(trade)
            bridge.record_trade(trade)
            payload = dashboard_payload(directory)
            self.assertEqual(len(payload["equity_curve"]), 2)
            self.assertEqual(len(payload["trades"]), 1)

    def test_corrupt_command_is_removed_without_execution(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "commands"
            path.mkdir()
            (path / "bad.json").write_text("not-json", encoding="ascii")
            self.assertEqual(DashboardBridge(directory).read_commands(), ())
            self.assertFalse((path / "bad.json").exists())


if __name__ == "__main__":
    unittest.main()