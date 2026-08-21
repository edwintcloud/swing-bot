from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from statistics import fmean

from swing_bot.config import StrategySettings

DEFAULT_STRATEGY_SETTINGS = StrategySettings()


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Bar OHLC values are inconsistent")
        if self.low > self.high:
            raise ValueError("Bar low cannot exceed high")
        if self.volume < 0:
            raise ValueError("Bar volume cannot be negative")


class Signal(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass(frozen=True)
class SignalEvaluation:
    signal: Signal
    fast_sma: float | None = None
    slow_sma: float | None = None
    reason: str = ""


def evaluate_latest(
    bars: Sequence[Bar], settings: StrategySettings = DEFAULT_STRATEGY_SETTINGS
) -> SignalEvaluation:
    minimum_bars = settings.slow_sma_period + 1
    if len(bars) < minimum_bars:
        return SignalEvaluation(Signal.NONE, reason=f"warmup requires {minimum_bars} bars")

    closes = [bar.close for bar in bars]
    previous_fast_sma = fmean(
        closes[-settings.fast_sma_period - 1 : -1]
    )
    fast_sma = fmean(closes[-settings.fast_sma_period :])
    slow_sma = fmean(closes[-settings.slow_sma_period :])
    previous_close = closes[-2]
    current_close = closes[-1]

    fast_far_below = fast_sma <= slow_sma * (1.0 - settings.sma_separation_fraction)
    fast_far_above = fast_sma >= slow_sma * (1.0 + settings.sma_separation_fraction)
    crossed_long = (
        previous_close <= previous_fast_sma
        and fast_sma < current_close <= fast_sma * (1.0 + settings.crossover_fraction)
    )
    crossed_short = (
        previous_close >= previous_fast_sma
        and fast_sma * (1.0 - settings.crossover_fraction) <= current_close < fast_sma
    )

    if fast_far_above and crossed_long:
        return SignalEvaluation(
            Signal.LONG,
            fast_sma=fast_sma,
            slow_sma=slow_sma,
            reason="price crossed above SMA20 in an established uptrend",
        )
    if fast_far_below and crossed_short:
        return SignalEvaluation(
            Signal.SHORT,
            fast_sma=fast_sma,
            slow_sma=slow_sma,
            reason="price crossed below SMA20 in an established downtrend",
        )
    return SignalEvaluation(
        Signal.NONE,
        fast_sma=fast_sma,
        slow_sma=slow_sma,
        reason="SMA separation or crossover not met",
    )


def evaluate_at(
    bars: Sequence[Bar], index: int, settings: StrategySettings = DEFAULT_STRATEGY_SETTINGS
) -> SignalEvaluation:
    if index < 0 or index >= len(bars):
        raise IndexError("bar index out of range")
    return evaluate_latest(bars[: index + 1], settings)