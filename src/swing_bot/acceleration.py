from __future__ import annotations

from dataclasses import dataclass

from swing_bot.config import PriceAccelerationSettings
from swing_bot.signals import Signal

NS_PER_SECOND = 1_000_000_000
FLOAT_TOLERANCE = 1e-12


@dataclass(frozen=True)
class AccelerationEvaluation:
    signal: Signal = Signal.NONE
    should_exit: bool = False
    velocity: float | None = None
    acceleration: float | None = None
    reason: str = ""


class AccelerationTracker:
    def __init__(self, settings: PriceAccelerationSettings) -> None:
        self.settings = settings
        self.previous_close: float | None = None
        self.previous_velocity: float | None = None
        self.previous_timestamp_ns: int | None = None
        self.confirmation_signal = Signal.NONE
        self.confirmation_count = 0
        self.armed_signal = Signal.NONE
        self.armed_at_ns: int | None = None
        self.peak_directional_acceleration = 0.0
        self.flatline_count = 0
        self.position_signal = Signal.NONE
        self.cooldown_until_ns = 0

    def update(self, close: float, timestamp_ns: int) -> AccelerationEvaluation:
        if close <= 0:
            raise ValueError("close must be positive")
        elapsed_seconds: float | None = None
        if self.previous_timestamp_ns is not None:
            if timestamp_ns <= self.previous_timestamp_ns:
                raise ValueError("timestamps must be strictly increasing")
            elapsed_ns = timestamp_ns - self.previous_timestamp_ns
            if elapsed_ns > self.settings.bar_interval_seconds * NS_PER_SECOND:
                self.reset_session()
            else:
                elapsed_seconds = elapsed_ns / NS_PER_SECOND
        self.previous_timestamp_ns = timestamp_ns
        if self.previous_close is None:
            self.previous_close = close
            return AccelerationEvaluation(reason="velocity warmup")

        assert elapsed_seconds is not None
        velocity = (close / self.previous_close - 1.0) / elapsed_seconds
        self.previous_close = close
        if self.previous_velocity is None:
            self.previous_velocity = velocity
            return AccelerationEvaluation(velocity=velocity, reason="acceleration warmup")

        acceleration = (velocity - self.previous_velocity) / elapsed_seconds
        self.previous_velocity = velocity
        if self.position_signal is not Signal.NONE:
            return self._evaluate_exit(velocity, acceleration)
        return self._evaluate_entry(timestamp_ns, velocity, acceleration)

    def position_opened(self, signal: Signal) -> None:
        if signal is Signal.NONE:
            raise ValueError("position signal must be directional")
        self.position_signal = signal
        self.flatline_count = 0
        self._reset_setup()

    def position_closed(self, timestamp_ns: int) -> None:
        self.position_signal = Signal.NONE
        self.flatline_count = 0
        self.cooldown_until_ns = timestamp_ns + self.settings.cooldown_seconds * NS_PER_SECOND
        self._reset_setup()

    def reset_session(self) -> None:
        self.previous_close = None
        self.previous_velocity = None
        self.previous_timestamp_ns = None
        self.flatline_count = 0
        self._reset_setup()

    def _evaluate_entry(
        self, timestamp_ns: int, velocity: float, acceleration: float
    ) -> AccelerationEvaluation:
        if timestamp_ns < self.cooldown_until_ns:
            self._reset_setup()
            return AccelerationEvaluation(
                velocity=velocity, acceleration=acceleration, reason="cooldown active"
            )
        expiry_ns = self.settings.setup_expiry_seconds * NS_PER_SECOND
        if self.armed_at_ns is not None and timestamp_ns - self.armed_at_ns >= expiry_ns:
            self._reset_setup()

        threshold = self.settings.acceleration_threshold
        candidate = (
            Signal.LONG
            if acceleration + FLOAT_TOLERANCE >= threshold
            else Signal.SHORT
            if acceleration - FLOAT_TOLERANCE <= -threshold
            else Signal.NONE
        )
        if candidate is not Signal.NONE and candidate is not self.armed_signal:
            if self.armed_signal is not Signal.NONE:
                self._reset_setup()
            if candidate is self.confirmation_signal:
                self.confirmation_count += 1
            else:
                self.confirmation_signal = candidate
                self.confirmation_count = 1
            if self.confirmation_count < self.settings.acceleration_confirmation_bars:
                return AccelerationEvaluation(
                    velocity=velocity,
                    acceleration=acceleration,
                    reason=(
                        f"{candidate.value} setup confirmation "
                        f"{self.confirmation_count}/"
                        f"{self.settings.acceleration_confirmation_bars}"
                    ),
                )
            self.armed_signal = candidate
            self.armed_at_ns = timestamp_ns
            self.peak_directional_acceleration = abs(acceleration)
            self.confirmation_signal = Signal.NONE
            self.confirmation_count = 0
            return AccelerationEvaluation(
                velocity=velocity, acceleration=acceleration, reason=f"{candidate.value} setup armed"
            )
        if self.armed_signal is Signal.NONE:
            self.confirmation_signal = Signal.NONE
            self.confirmation_count = 0
            return AccelerationEvaluation(
                velocity=velocity, acceleration=acceleration, reason="acceleration threshold not met"
            )

        direction = 1.0 if self.armed_signal is Signal.LONG else -1.0
        directional_acceleration = direction * acceleration
        self.peak_directional_acceleration = max(
            self.peak_directional_acceleration, directional_acceleration
        )
        decelerated = (
            self.peak_directional_acceleration - directional_acceleration
            + FLOAT_TOLERANCE
            >= self.settings.deceleration_threshold
        )
        if decelerated and direction * velocity > 0:
            signal = self.armed_signal
            self._reset_setup()
            return AccelerationEvaluation(
                signal=signal,
                velocity=velocity,
                acceleration=acceleration,
                reason="directional acceleration decelerated from peak",
            )
        return AccelerationEvaluation(
            velocity=velocity, acceleration=acceleration, reason="waiting for deceleration"
        )

    def _evaluate_exit(self, velocity: float, acceleration: float) -> AccelerationEvaluation:
        if abs(acceleration) <= self.settings.flatline_threshold + FLOAT_TOLERANCE:
            self.flatline_count += 1
        else:
            self.flatline_count = 0
        should_exit = self.flatline_count >= self.settings.flatline_bars
        return AccelerationEvaluation(
            should_exit=should_exit,
            velocity=velocity,
            acceleration=acceleration,
            reason="acceleration flatlined" if should_exit else "position active",
        )

    def _reset_setup(self) -> None:
        self.confirmation_signal = Signal.NONE
        self.confirmation_count = 0
        self.armed_signal = Signal.NONE
        self.armed_at_ns = None
        self.peak_directional_acceleration = 0.0