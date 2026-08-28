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
        self.assertEqual(args.second_chunk_minutes, 30)
        self.assertFalse(args.include_second_bars)

    def test_second_bar_download_is_explicit_opt_in(self) -> None:
        args = build_parser().parse_args(
            [
                "download-data",
                "--start",
                "2024-01-01T00:00:00+00:00",
                "--end",
                "2024-01-01T01:00:00+00:00",
                "--include-second-bars",
                "--second-chunk-minutes",
                "15",
            ]
        )
        self.assertTrue(args.include_second_bars)
        self.assertEqual(args.second_chunk_minutes, 15)

    def test_paper_mode_does_not_accept_manual_starting_equity(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["paper", "--starting-equity", "100000"])

    def test_backtest_portfolio_strategy_is_explicit_opt_in(self) -> None:
        parser = build_parser()
        baseline = parser.parse_args(
            [
                "backtest",
                "--start",
                "2024-01-01T00:00:00-05:00",
                "--end",
                "2025-01-01T00:00:00-05:00",
            ]
        )
        portfolio = parser.parse_args(
            [
                "backtest",
                "--start",
                "2024-01-01T00:00:00-05:00",
                "--end",
                "2025-01-01T00:00:00-05:00",
                "--strategy",
                "portfolio-momentum",
            ]
        )

        self.assertEqual(baseline.strategy, "sma-continuation")
        self.assertEqual(portfolio.strategy, "portfolio-momentum")

    def test_paper_and_live_accept_portfolio_strategy(self) -> None:
        parser = build_parser()

        for command in ("paper", "live"):
            baseline = parser.parse_args([command])
            portfolio = parser.parse_args([command, "--strategy", "portfolio-momentum"])
            self.assertEqual(baseline.strategy, "sma-continuation")
            self.assertEqual(portfolio.strategy, "portfolio-momentum")

    def test_acceleration_strategy_is_explicit_opt_in(self) -> None:
        parser = build_parser()
        for command in ("paper", "live"):
            args = parser.parse_args([command, "--strategy", "price-acceleration"])
            self.assertEqual(args.strategy, "price-acceleration")


if __name__ == "__main__":
    unittest.main()
