from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from swing_bot.portfolio import PortfolioSettings


@dataclass(frozen=True)
class StrategySettings:
    fast_sma_period: int = 20
    slow_sma_period: int = 100
    sma_separation_fraction: float = 0.05
    crossover_fraction: float = 0.01
    trailing_stop_fraction: float = 0.05

    def __post_init__(self) -> None:
        if self.fast_sma_period <= 0 or self.slow_sma_period <= 0:
            raise ValueError("SMA periods must be positive")
        if self.fast_sma_period >= self.slow_sma_period:
            raise ValueError("fast_sma_period must be less than slow_sma_period")
        fractions = (
            self.sma_separation_fraction,
            self.crossover_fraction,
            self.trailing_stop_fraction,
        )
        if any(not 0 < value < 1 for value in fractions):
            raise ValueError("Strategy fractions must be greater than zero and less than one")


@dataclass(frozen=True)
class PriceAccelerationSettings:
    bar_interval_seconds: int = 5
    acceleration_threshold: float = 0.0002
    deceleration_threshold: float = 0.0001
    flatline_threshold: float = 0.00002
    flatline_bars: int = 3
    trailing_stop_fraction: float = 0.0015
    setup_expiry_seconds: int = 10
    cooldown_seconds: int = 5

    def __post_init__(self) -> None:
        if self.bar_interval_seconds <= 0:
            raise ValueError("bar_interval_seconds must be positive")
        thresholds = (
            self.acceleration_threshold,
            self.deceleration_threshold,
            self.flatline_threshold,
            self.trailing_stop_fraction,
        )
        if any(not 0 < value < 1 for value in thresholds):
            raise ValueError("Acceleration thresholds and trailing stop must be between zero and one")
        if self.deceleration_threshold > self.acceleration_threshold:
            raise ValueError("deceleration_threshold cannot exceed acceleration_threshold")
        if self.flatline_bars <= 0:
            raise ValueError("flatline_bars must be positive")
        if self.setup_expiry_seconds <= 0 or self.cooldown_seconds < 0:
            raise ValueError("Setup expiry must be positive and cooldown cannot be negative")


@dataclass(frozen=True)
class RiskSettings:
    risk_per_trade: float = 0.005
    maximum_position_fraction: float = 0.10
    maximum_positions: int = 3
    maximum_gross_exposure: float = 0.30
    maximum_short_exposure: float = 0.20
    daily_loss_limit: float = 0.015
    weekly_loss_limit: float = 0.03
    maximum_drawdown: float = 0.08

    def __post_init__(self) -> None:
        fractions = (
            self.risk_per_trade,
            self.maximum_position_fraction,
            self.daily_loss_limit,
            self.weekly_loss_limit,
            self.maximum_drawdown,
        )
        if any(not 0 < value <= 1 for value in fractions):
            raise ValueError("Risk fractions must be greater than zero and at most one")
        if self.maximum_positions <= 0:
            raise ValueError("maximum_positions must be positive")
        if self.maximum_gross_exposure <= 0 or self.maximum_short_exposure <= 0:
            raise ValueError("Exposure limits must be positive")
        if self.maximum_short_exposure > self.maximum_gross_exposure:
            raise ValueError("maximum_short_exposure cannot exceed maximum_gross_exposure")
        if self.risk_per_trade > self.maximum_position_fraction:
            raise ValueError("risk_per_trade cannot exceed maximum_position_fraction")


@dataclass(frozen=True)
class AppConfig:
    symbols: tuple[str, ...]
    strategy: StrategySettings
    risk: RiskSettings

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("At least one symbol is required")
        normalized = tuple(symbol.strip().upper() for symbol in self.symbols)
        if normalized != self.symbols:
            raise ValueError("Symbols must be uppercase and contain no surrounding whitespace")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Symbols must be unique")


@dataclass(frozen=True)
class PortfolioConfig:
    settings: PortfolioSettings
    sectors: dict[str, str]


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def _reject_unknown_keys(data: dict[str, Any], model: type[Any], source: Path) -> None:
    allowed = {field.name for field in fields(model)}
    unknown = set(data) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown keys in {source}: {names}")


def load_config(config_dir: Path | str = "config") -> AppConfig:
    directory = Path(config_dir)
    universe_path = directory / "universe.toml"
    strategy_path = directory / "strategy.toml"
    risk_path = directory / "risk.toml"
    universe = _read_toml(universe_path)
    strategy_data = _read_toml(strategy_path)
    risk_data = _read_toml(risk_path)
    if set(universe) != {"symbols"}:
        raise ValueError(f"{universe_path} must contain only 'symbols'")
    _reject_unknown_keys(strategy_data, StrategySettings, strategy_path)
    _reject_unknown_keys(risk_data, RiskSettings, risk_path)
    symbols = universe["symbols"]
    if not isinstance(symbols, list) or not all(isinstance(item, str) for item in symbols):
        raise ValueError("symbols must be a list of strings")
    return AppConfig(
        symbols=tuple(symbols),
        strategy=StrategySettings(**strategy_data),
        risk=RiskSettings(**risk_data),
    )


def load_price_acceleration_config(
    config_dir: Path | str = "config",
) -> PriceAccelerationSettings:
    path = Path(config_dir) / "price_acceleration.toml"
    data = _read_toml(path)
    _reject_unknown_keys(data, PriceAccelerationSettings, path)
    return PriceAccelerationSettings(**data)


def load_portfolio_config(
    symbols: tuple[str, ...], config_dir: Path | str = "config"
) -> PortfolioConfig:
    directory = Path(config_dir)
    settings_path = directory / "portfolio.toml"
    sectors_path = directory / "sectors.toml"
    settings_data = _read_toml(settings_path)
    sectors_data = _read_toml(sectors_path)
    _reject_unknown_keys(settings_data, PortfolioSettings, settings_path)
    if set(sectors_data) != {"sectors"} or not isinstance(sectors_data["sectors"], dict):
        raise ValueError(f"{sectors_path} must contain only a sectors table")
    sectors = sectors_data["sectors"]
    if not all(isinstance(symbol, str) and isinstance(sector, str) for symbol, sector in sectors.items()):
        raise ValueError("Sector names and symbols must be strings")
    if set(sectors) != set(symbols):
        missing = sorted(set(symbols) - set(sectors))
        extra = sorted(set(sectors) - set(symbols))
        raise ValueError(f"Sector map must match universe; missing={missing}, extra={extra}")
    if any(not sector.strip() for sector in sectors.values()):
        raise ValueError("Sector names cannot be empty")
    return PortfolioConfig(
        settings=PortfolioSettings(**settings_data),
        sectors={symbol: sectors[symbol] for symbol in symbols},
    )
