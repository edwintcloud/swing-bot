from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor, isfinite

from swing_bot.config import RiskSettings

DEFAULT_RISK_SETTINGS = RiskSettings()


@dataclass(frozen=True)
class PositionSize:
    shares: int
    risk_amount: float
    notional: float
    limiting_factor: str


@dataclass(frozen=True)
class PortfolioSnapshot:
    equity: float
    day_start_equity: float
    week_start_equity: float
    high_water_equity: float
    gross_exposure: float
    short_exposure: float
    open_positions: int


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass
class EquityReferences:
    equity: float
    day_start_equity: float
    week_start_equity: float
    high_water_equity: float
    day: object
    week: tuple[int, int]

    @classmethod
    def initialize(cls, equity: float, timestamp: datetime) -> EquityReferences:
        if not isfinite(equity) or equity <= 0:
            raise ValueError("Equity must be finite and positive")
        iso = timestamp.isocalendar()
        return cls(equity, equity, equity, equity, timestamp.date(), (iso.year, iso.week))

    def update(self, equity: float, timestamp: datetime, *, track_high_water: bool = True) -> None:
        if not isfinite(equity) or equity <= 0:
            raise ValueError("Equity must be finite and positive")
        iso = timestamp.isocalendar()
        current_week = (iso.year, iso.week)
        if timestamp.date() != self.day:
            self.day = timestamp.date()
            self.day_start_equity = equity
        if current_week != self.week:
            self.week = current_week
            self.week_start_equity = equity
        self.equity = equity
        if track_high_water:
            self.high_water_equity = max(self.high_water_equity, equity)


def calculate_position_size(
    *,
    equity: float,
    entry_price: float,
    stop_price: float,
    settings: RiskSettings = DEFAULT_RISK_SETTINGS,
) -> PositionSize:
    values = (equity, entry_price, stop_price)
    if not all(isfinite(value) for value in values):
        raise ValueError("Sizing inputs must be finite")
    if equity <= 0 or entry_price <= 0 or stop_price <= 0:
        raise ValueError("Equity and prices must be positive")
    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        raise ValueError("Entry and stop prices must differ")

    risk_budget = equity * settings.risk_per_trade
    notional_budget = equity * settings.maximum_position_fraction
    risk_limited_shares = floor(risk_budget / stop_distance)
    notional_limited_shares = floor(notional_budget / entry_price)
    shares = min(risk_limited_shares, notional_limited_shares)
    limiting_factor = "risk" if risk_limited_shares <= notional_limited_shares else "notional"
    return PositionSize(
        shares=shares,
        risk_amount=shares * stop_distance,
        notional=shares * entry_price,
        limiting_factor=limiting_factor,
    )


def evaluate_entry_risk(
    *,
    snapshot: PortfolioSnapshot,
    proposed_notional: float,
    is_short: bool,
    settings: RiskSettings = DEFAULT_RISK_SETTINGS,
) -> RiskDecision:
    snapshot_values = (
        snapshot.equity,
        snapshot.day_start_equity,
        snapshot.week_start_equity,
        snapshot.high_water_equity,
        snapshot.gross_exposure,
        snapshot.short_exposure,
        proposed_notional,
    )
    if not all(isfinite(value) for value in snapshot_values):
        return RiskDecision(False, "portfolio values must be finite")
    if (
        min(
            snapshot.equity,
            snapshot.day_start_equity,
            snapshot.week_start_equity,
            snapshot.high_water_equity,
        )
        <= 0
    ):
        return RiskDecision(False, "equity references must be positive")
    if proposed_notional <= 0:
        return RiskDecision(False, "proposed notional must be positive")
    if snapshot.gross_exposure < 0 or snapshot.short_exposure < 0:
        return RiskDecision(False, "exposures cannot be negative")
    if snapshot.open_positions >= settings.maximum_positions:
        return RiskDecision(False, "maximum open positions reached")

    daily_return = snapshot.equity / snapshot.day_start_equity - 1.0
    weekly_return = snapshot.equity / snapshot.week_start_equity - 1.0
    drawdown = snapshot.equity / snapshot.high_water_equity - 1.0
    if daily_return <= -settings.daily_loss_limit:
        return RiskDecision(False, "daily loss circuit breaker active")
    if weekly_return <= -settings.weekly_loss_limit:
        return RiskDecision(False, "weekly loss circuit breaker active")
    if drawdown <= -settings.maximum_drawdown:
        return RiskDecision(False, "drawdown circuit breaker active")

    proposed_fraction = proposed_notional / snapshot.equity
    if snapshot.gross_exposure + proposed_fraction > settings.maximum_gross_exposure:
        return RiskDecision(False, "maximum gross exposure exceeded")
    if is_short and snapshot.short_exposure + proposed_fraction > settings.maximum_short_exposure:
        return RiskDecision(False, "maximum short exposure exceeded")
    return RiskDecision(True, "entry permitted")
