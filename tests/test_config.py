import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from swing_bot.config import (
    PriceAccelerationSettings,
    StrategySettings,
    load_config,
    load_portfolio_config,
    load_price_acceleration_config,
)


class ConfigTests(unittest.TestCase):
    def test_default_configuration_loads(self) -> None:
        config = load_config()
        self.assertEqual(
            config.symbols,
            (
                "NBIS",
                "INTC",
                "GOOGL",
                "META",
                "AMZN",
                "TSLA",
                "WMT",
                "COST",
                "XOM",
                "CVX",
                "JPM",
                "V",
                "LLY",
                "JNJ",
                "GE",
                "RTX",
                "NVDA",
                "MSFT",
                "LIN",
                "SHW",
                "PLD",
                "AMT",
                "NEE",
                "SO",
            ),
        )
        self.assertEqual(config.strategy.fast_sma_period, 20)
        self.assertEqual(config.strategy.slow_sma_period, 100)
        self.assertEqual(config.strategy.sma_separation_fraction, 0.05)
        self.assertEqual(config.strategy.crossover_fraction, 0.01)

    def test_portfolio_configuration_loads_complete_sector_map(self) -> None:
        app = load_config()
        portfolio = load_portfolio_config(app.symbols)

        self.assertEqual(portfolio.settings.momentum_lookback, 252)
        self.assertEqual(portfolio.settings.target_gross_exposure, 0.80)
        self.assertEqual(portfolio.sectors["NBIS"], "Information Technology")
        self.assertEqual(set(portfolio.sectors), set(app.symbols))

    def test_price_acceleration_configuration_is_isolated(self) -> None:
        settings = load_price_acceleration_config()
        self.assertEqual(settings.acceleration_threshold, 0.0002)
        self.assertEqual(settings.flatline_bars, 3)
        self.assertEqual(settings.trailing_stop_fraction, 0.0015)

    def test_acceleration_deceleration_cannot_exceed_arm_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "deceleration_threshold"):
            PriceAccelerationSettings(
                acceleration_threshold=0.01,
                deceleration_threshold=0.02,
            )

    def test_unknown_strategy_key_is_rejected(self) -> None:
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "universe.toml").write_text('symbols = ["MU"]\n', encoding="ascii")
            (directory / "strategy.toml").write_text("mystery = 1\n", encoding="ascii")
            (directory / "risk.toml").write_text("risk_per_trade = 0.005\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Unknown keys"):
                load_config(directory)

    def test_fast_sma_must_be_shorter_than_slow_sma(self) -> None:
        with self.assertRaisesRegex(ValueError, "fast_sma_period"):
            StrategySettings(fast_sma_period=200, slow_sma_period=20)

    def test_strategy_fractions_must_be_less_than_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "fractions"):
            StrategySettings(crossover_fraction=1.0)

    def test_portfolio_sector_map_must_match_universe(self) -> None:
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "portfolio.toml").write_text(
                "momentum_lookback = 10\n", encoding="ascii"
            )
            (directory / "sectors.toml").write_text(
                '[sectors]\nOTHER = "Industrials"\n', encoding="ascii"
            )

            with self.assertRaisesRegex(ValueError, "must match universe"):
                load_portfolio_config(("MU",), directory)


if __name__ == "__main__":
    unittest.main()
