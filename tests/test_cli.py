import unittest

from swing_bot.cli import build_parser


class CliTests(unittest.TestCase):
    def test_help_surface_contains_all_operator_commands(self) -> None:
        help_text = build_parser().format_help()
        for command in (
            "discover-contracts",
            "download-data",
            "validate-data",
            "backtest",
            "connectivity",
            "dashboard",
            "paper",
            "live",
        ):
            self.assertIn(command, help_text)

    def test_datetime_requires_timezone(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["backtest", "--start", "2024-01-01", "--end", "2025-01-01"])

    def test_download_uses_bar_specific_chunk_defaults(self) -> None:
        args = build_parser().parse_args(
            [
                "download-data",
                "--start",
                "2024-01-01T00:00:00+00:00",
                "--end",
                "2024-02-01T00:00:00+00:00",
            ]
        )

        self.assertEqual(args.hourly_chunk_days, 30)
        self.assertEqual(args.minute_chunk_days, 30)

    def test_paper_mode_does_not_accept_manual_starting_equity(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["paper", "--starting-equity", "100000"])


if __name__ == "__main__":
    unittest.main()
