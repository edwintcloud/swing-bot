import unittest

from swing_bot.portfolio import (
    CandidateSeries,
    PortfolioSettings,
    PortfolioTarget,
    build_portfolio_targets,
    build_share_targets,
    evaluate_candidate,
)

SETTINGS = PortfolioSettings(
    momentum_lookback=4,
    momentum_skip=1,
    trend_lookback=3,
    volatility_lookback=3,
    periods_per_year=12,
    maximum_positions=3,
    target_gross_exposure=0.60,
    maximum_name_fraction=0.30,
    maximum_sector_fraction=0.40,
    volatility_floor=0.01,
    minimum_price=5.0,
    minimum_median_dollar_volume=1_000_000.0,
)


def candidate(
    symbol: str,
    sector: str,
    closes: tuple[float, ...],
    median_dollar_volume: float = 20_000_000.0,
) -> CandidateSeries:
    return CandidateSeries(symbol, sector, closes, median_dollar_volume)


class CandidateEvaluationTests(unittest.TestCase):
    def test_positive_momentum_above_trend_is_eligible(self) -> None:
        result = evaluate_candidate(
            candidate("AAA", "Technology", (10.0, 11.0, 12.0, 13.0, 14.0, 15.0)),
            SETTINGS,
        )

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.momentum if result else 0.0, 14.0 / 10.0 - 1.0)

    def test_latest_skipped_period_does_not_create_momentum(self) -> None:
        result = evaluate_candidate(
            candidate("AAA", "Technology", (10.0, 10.0, 10.0, 10.0, 10.0, 20.0)),
            SETTINGS,
        )

        self.assertIsNone(result)

    def test_liquidity_and_absolute_trend_are_required(self) -> None:
        illiquid = candidate(
            "AAA",
            "Technology",
            (10.0, 11.0, 12.0, 13.0, 14.0, 15.0),
            median_dollar_volume=500_000.0,
        )
        below_trend = candidate(
            "BBB", "Industrials", (10.0, 20.0, 20.0, 20.0, 15.0, 10.0)
        )

        self.assertIsNone(evaluate_candidate(illiquid, SETTINGS))
        self.assertIsNone(evaluate_candidate(below_trend, SETTINGS))


class PortfolioConstructionTests(unittest.TestCase):
    def test_targets_are_ranked_and_respect_hard_caps(self) -> None:
        targets = build_portfolio_targets(
            (
                candidate("AAA", "Technology", (10.0, 11.0, 12.0, 13.0, 14.0, 15.0)),
                candidate("BBB", "Technology", (10.0, 10.5, 11.0, 11.5, 12.0, 12.5)),
                candidate("CCC", "Industrials", (10.0, 10.2, 10.4, 10.6, 10.8, 11.0)),
            ),
            SETTINGS,
        )

        self.assertEqual([target.symbol for target in targets], ["AAA", "BBB", "CCC"])
        self.assertLessEqual(sum(target.weight for target in targets), 0.60)
        self.assertTrue(all(target.weight <= 0.30 for target in targets))
        technology_weight = sum(
            target.weight for target in targets if target.sector == "Technology"
        )
        self.assertLessEqual(technology_weight, 0.40)

    def test_lower_volatility_receives_more_uncapped_weight(self) -> None:
        settings = PortfolioSettings(
            momentum_lookback=4,
            momentum_skip=1,
            trend_lookback=3,
            volatility_lookback=3,
            periods_per_year=12,
            maximum_positions=2,
            target_gross_exposure=0.80,
            maximum_name_fraction=0.80,
            maximum_sector_fraction=0.80,
            volatility_floor=0.01,
            minimum_price=5.0,
            minimum_median_dollar_volume=1_000_000.0,
        )
        targets = build_portfolio_targets(
            (
                candidate("VOLATILE", "Technology", (10.0, 15.0, 11.0, 16.0, 12.0, 18.0)),
                candidate("STABLE", "Industrials", (10.0, 10.5, 11.0, 11.5, 12.0, 12.5)),
            ),
            settings,
        )
        weights = {target.symbol: target.weight for target in targets}

        self.assertGreater(weights["STABLE"], weights["VOLATILE"])

    def test_no_eligible_candidates_holds_cash(self) -> None:
        targets = build_portfolio_targets(
            (candidate("AAA", "Technology", (10.0, 9.0, 8.0)),), SETTINGS
        )

        self.assertEqual(targets, ())


class ShareTargetTests(unittest.TestCase):
    def test_share_targets_enter_resize_and_exit(self) -> None:
        targets = (
            PortfolioTarget("AAA", "Technology", 0.10, 0.20, 0.15),
            PortfolioTarget("BBB", "Industrials", 0.05, 0.10, 0.10),
        )

        result = build_share_targets(
            targets,
            equity=100_000.0,
            prices={"AAA": 100.0, "BBB": 50.0},
            current_shares={"AAA": 80, "OLD": 25},
        )

        self.assertEqual(
            [(target.symbol, target.current_shares, target.target_shares) for target in result],
            [("AAA", 80, 100), ("BBB", 0, 100), ("OLD", 25, 0)],
        )

    def test_missing_target_price_fails_closed(self) -> None:
        targets = (PortfolioTarget("AAA", "Technology", 0.10, 0.20, 0.15),)

        with self.assertRaisesRegex(ValueError, "price is required"):
            build_share_targets(targets, equity=100_000.0, prices={}, current_shares={})


if __name__ == "__main__":
    unittest.main()