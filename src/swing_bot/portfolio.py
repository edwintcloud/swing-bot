from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import floor, isfinite, sqrt
from statistics import fmean, stdev


@dataclass(frozen=True)
class PortfolioSettings:
    momentum_lookback: int = 252
    momentum_skip: int = 21
    trend_lookback: int = 200
    volatility_lookback: int = 63
    liquidity_lookback: int = 20
    periods_per_year: int = 252
    maximum_positions: int = 10
    target_gross_exposure: float = 0.80
    maximum_name_fraction: float = 0.10
    maximum_sector_fraction: float = 0.25
    volatility_floor: float = 0.10
    minimum_price: float = 5.0
    minimum_median_dollar_volume: float = 10_000_000.0

    def __post_init__(self) -> None:
        periods = (
            self.momentum_lookback,
            self.trend_lookback,
            self.volatility_lookback,
            self.liquidity_lookback,
            self.periods_per_year,
            self.maximum_positions,
        )
        if any(value <= 0 for value in periods) or self.momentum_skip < 0:
            raise ValueError("Portfolio periods and maximum_positions must be positive")
        fractions = (
            self.target_gross_exposure,
            self.maximum_name_fraction,
            self.maximum_sector_fraction,
            self.volatility_floor,
        )
        if any(not 0 < value <= 1 for value in fractions):
            raise ValueError("Portfolio fractions must be greater than zero and at most one")
        if self.maximum_name_fraction > self.maximum_sector_fraction:
            raise ValueError("maximum_name_fraction cannot exceed maximum_sector_fraction")


DEFAULT_PORTFOLIO_SETTINGS = PortfolioSettings()


@dataclass(frozen=True)
class CandidateSeries:
    symbol: str
    sector: str
    closes: tuple[float, ...]
    median_dollar_volume: float

    def __post_init__(self) -> None:
        if not self.symbol or not self.sector:
            raise ValueError("Candidate symbol and sector are required")
        if not isfinite(self.median_dollar_volume) or self.median_dollar_volume < 0:
            raise ValueError("median_dollar_volume must be finite and non-negative")
        if any(not isfinite(close) or close <= 0 for close in self.closes):
            raise ValueError("Candidate closes must be finite and positive")


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    sector: str
    momentum: float
    annualized_volatility: float


@dataclass(frozen=True)
class PortfolioTarget:
    symbol: str
    sector: str
    weight: float
    momentum: float
    annualized_volatility: float


@dataclass(frozen=True)
class ShareTarget:
    symbol: str
    current_shares: int
    target_shares: int

    @property
    def delta(self) -> int:
        return self.target_shares - self.current_shares


def evaluate_candidate(
    candidate: CandidateSeries, settings: PortfolioSettings = DEFAULT_PORTFOLIO_SETTINGS
) -> RankedCandidate | None:
    required_closes = max(
        settings.momentum_lookback + settings.momentum_skip + 1,
        settings.trend_lookback,
        settings.volatility_lookback + 1,
    )
    if len(candidate.closes) < required_closes:
        return None
    current_price = candidate.closes[-1]
    if current_price < settings.minimum_price:
        return None
    if candidate.median_dollar_volume < settings.minimum_median_dollar_volume:
        return None

    trend_average = fmean(candidate.closes[-settings.trend_lookback :])
    if current_price <= trend_average:
        return None

    momentum_end = candidate.closes[-settings.momentum_skip - 1]
    momentum_start = candidate.closes[
        -settings.momentum_lookback - settings.momentum_skip - 1
    ]
    momentum = momentum_end / momentum_start - 1.0
    if momentum <= 0:
        return None

    volatility_closes = candidate.closes[-settings.volatility_lookback - 1 :]
    returns = [
        current / previous - 1.0
        for previous, current in pairwise(volatility_closes)
    ]
    annualized_volatility = max(
        stdev(returns) * sqrt(settings.periods_per_year),
        settings.volatility_floor,
    )
    return RankedCandidate(
        symbol=candidate.symbol,
        sector=candidate.sector,
        momentum=momentum,
        annualized_volatility=annualized_volatility,
    )


def build_portfolio_targets(
    candidates: tuple[CandidateSeries, ...],
    settings: PortfolioSettings = DEFAULT_PORTFOLIO_SETTINGS,
) -> tuple[PortfolioTarget, ...]:
    ranked = sorted(
        filter(None, (evaluate_candidate(candidate, settings) for candidate in candidates)),
        key=lambda candidate: (-candidate.momentum, candidate.symbol),
    )[: settings.maximum_positions]
    if not ranked:
        return ()

    inverse_volatility_total = sum(1.0 / candidate.annualized_volatility for candidate in ranked)
    sector_allocations: dict[str, float] = {}
    targets: list[PortfolioTarget] = []
    gross_allocation = 0.0
    for candidate in ranked:
        risk_weight = (
            settings.target_gross_exposure
            * (1.0 / candidate.annualized_volatility)
            / inverse_volatility_total
        )
        sector_capacity = settings.maximum_sector_fraction - sector_allocations.get(
            candidate.sector, 0.0
        )
        gross_capacity = settings.target_gross_exposure - gross_allocation
        weight = min(
            risk_weight,
            settings.maximum_name_fraction,
            sector_capacity,
            gross_capacity,
        )
        if weight <= 0:
            continue
        gross_allocation += weight
        sector_allocations[candidate.sector] = (
            sector_allocations.get(candidate.sector, 0.0) + weight
        )
        targets.append(
            PortfolioTarget(
                symbol=candidate.symbol,
                sector=candidate.sector,
                weight=weight,
                momentum=candidate.momentum,
                annualized_volatility=candidate.annualized_volatility,
            )
        )
    return tuple(targets)


def build_share_targets(
    targets: tuple[PortfolioTarget, ...],
    *,
    equity: float,
    prices: dict[str, float],
    current_shares: dict[str, int],
) -> tuple[ShareTarget, ...]:
    if not isfinite(equity) or equity <= 0:
        raise ValueError("equity must be finite and positive")
    target_weights = {target.symbol: target.weight for target in targets}
    symbols = sorted(set(target_weights) | set(current_shares))
    share_targets: list[ShareTarget] = []
    for symbol in symbols:
        current = current_shares.get(symbol, 0)
        if current < 0:
            raise ValueError("Portfolio redesign is long-only")
        weight = target_weights.get(symbol, 0.0)
        if weight:
            price = prices.get(symbol)
            if price is None or not isfinite(price) or price <= 0:
                raise ValueError(f"A finite positive price is required for {symbol}")
            target = floor(equity * weight / price)
        else:
            target = 0
        if target != current:
            share_targets.append(ShareTarget(symbol, current, target))
    return tuple(share_targets)