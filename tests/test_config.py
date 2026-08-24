import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from swing_bot.config import StrategySettings, load_config


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


if __name__ == "__main__":
    unittest.main()
