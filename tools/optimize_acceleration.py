from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, time
from itertools import product
from pathlib import Path
from statistics import fmean
from zoneinfo import ZoneInfo

from nautilus_trader.persistence.catalog import ParquetDataCatalog

from swing_bot.acceleration import AccelerationTracker
from swing_bot.config import PriceAccelerationSettings
from swing_bot.signals import Signal

COMMISSION_PER_SHARE = 0.005
SLIPPAGE_FRACTION = 0.0002
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketBar:
    timestamp_ns: int
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Trade:
    instrument_id: str
    opened_ns: int
    closed_ns: int
    return_fraction: float


@dataclass(frozen=True)
class Metrics:
    trades: int
    win_rate: float
    mean_return: float
    profit_factor: float
    compounded_return: float
    maximum_drawdown: float


def load_sessions(paths: list[Path]) -> dict[str, list[list[MarketBar]]]:
    sessions: dict[str, list[list[MarketBar]]] = {}
    for path in paths:
        catalog = ParquetDataCatalog(path)
        grouped: dict[str, list[MarketBar]] = {}
        for bar in catalog.bars():
            if "-5-SECOND-LAST-" not in str(bar.bar_type):
                continue
            grouped.setdefault(str(bar.bar_type.instrument_id), []).append(
                MarketBar(
                    timestamp_ns=bar.ts_init,
                    high=bar.high.as_double(),
                    low=bar.low.as_double(),
                    close=bar.close.as_double(),
                )
            )
        for instrument_id, bars in grouped.items():
            sessions.setdefault(instrument_id, []).append(
                sorted(bars, key=lambda value: value.timestamp_ns)
            )
    return sessions


def replay_session(
    instrument_id: str,
    bars: list[MarketBar],
    settings: PriceAccelerationSettings,
) -> list[Trade]:
    tracker = AccelerationTracker(settings)
    trades: list[Trade] = []
    signal = Signal.NONE
    entry_price = 0.0
    opened_ns = 0
    trailing_extreme = 0.0
    consecutive_losses = 0
    for bar in bars:
        local_time = datetime.fromtimestamp(
            bar.timestamp_ns / 1_000_000_000, tz=UTC
        ).astimezone(NEW_YORK).time().replace(tzinfo=None)
        entry_start = time(
            9 + (30 + settings.market_open_delay_minutes) // 60,
            (30 + settings.market_open_delay_minutes) % 60,
        )
        if signal is Signal.NONE and local_time < entry_start:
            tracker.reset_session()
            continue
        if consecutive_losses >= settings.max_consecutive_losses_per_instrument:
            break
        evaluation = tracker.update(bar.close, bar.timestamp_ns)
        if signal is Signal.NONE:
            if evaluation.signal is Signal.NONE:
                continue
            signal = evaluation.signal
            direction = 1.0 if signal is Signal.LONG else -1.0
            entry_price = bar.close * (1.0 + direction * SLIPPAGE_FRACTION)
            opened_ns = bar.timestamp_ns
            trailing_extreme = bar.close
            tracker.position_opened(signal)
            continue

        if signal is Signal.LONG:
            trailing_extreme = max(trailing_extreme, bar.high)
            stop_price = trailing_extreme * (1.0 - settings.trailing_stop_fraction)
            stopped = bar.low <= stop_price
            exit_price = stop_price * (1.0 - SLIPPAGE_FRACTION)
            gross_return = exit_price / entry_price - 1.0
        else:
            trailing_extreme = min(trailing_extreme, bar.low)
            stop_price = trailing_extreme * (1.0 + settings.trailing_stop_fraction)
            stopped = bar.high >= stop_price
            exit_price = stop_price * (1.0 + SLIPPAGE_FRACTION)
            gross_return = entry_price / exit_price - 1.0
        if not stopped and not evaluation.should_exit:
            continue
        if evaluation.should_exit and not stopped:
            exit_price = bar.close * (
                1.0 - SLIPPAGE_FRACTION if signal is Signal.LONG else 1.0 + SLIPPAGE_FRACTION
            )
            gross_return = (
                exit_price / entry_price - 1.0
                if signal is Signal.LONG
                else entry_price / exit_price - 1.0
            )
        commission_return = 2.0 * COMMISSION_PER_SHARE / entry_price
        net_return = gross_return - commission_return
        trades.append(Trade(instrument_id, opened_ns, bar.timestamp_ns, net_return))
        consecutive_losses = consecutive_losses + 1 if net_return < 0 else 0
        tracker.position_closed(bar.timestamp_ns)
        signal = Signal.NONE
    if signal is not Signal.NONE:
        final_bar = bars[-1]
        exit_price = final_bar.close * (
            1.0 - SLIPPAGE_FRACTION if signal is Signal.LONG else 1.0 + SLIPPAGE_FRACTION
        )
        gross_return = (
            exit_price / entry_price - 1.0
            if signal is Signal.LONG
            else entry_price / exit_price - 1.0
        )
        trades.append(
            Trade(
                instrument_id,
                opened_ns,
                final_bar.timestamp_ns,
                gross_return - 2.0 * COMMISSION_PER_SHARE / entry_price,
            )
        )
    return trades


def evaluate(
    sessions: dict[str, list[list[MarketBar]]],
    settings: PriceAccelerationSettings,
    session_indexes: range,
) -> Metrics:
    trades = sorted(
        (
            trade
            for instrument_id, instrument_sessions in sessions.items()
            for index in session_indexes
            if index < len(instrument_sessions)
            for trade in replay_session(instrument_id, instrument_sessions[index], settings)
        ),
        key=lambda trade: trade.opened_ns,
    )
    if not trades:
        return Metrics(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    returns = [trade.return_fraction for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    profit_factor = sum(wins) / -sum(losses) if losses else float("inf")
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, equity / peak - 1.0)
    return Metrics(
        trades=len(trades),
        win_rate=len(wins) / len(trades),
        mean_return=fmean(returns),
        profit_factor=profit_factor,
        compounded_return=equity - 1.0,
        maximum_drawdown=maximum_drawdown,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalogs", nargs="+", type=Path)
    parser.add_argument("--validation-sessions", type=int, default=1)
    parser.add_argument("--minimum-trades", type=int, default=20)
    args = parser.parse_args()
    sessions = load_sessions(args.catalogs)
    session_count = min(map(len, sessions.values()), default=0)
    development_count = session_count - args.validation_sessions
    if development_count <= 0:
        raise ValueError("At least one development and one validation session are required")

    baseline = PriceAccelerationSettings()
    baseline_development = evaluate(sessions, baseline, range(development_count))
    baseline_validation = evaluate(
        sessions, baseline, range(development_count, session_count)
    )

    candidates = []
    for threshold, minimum_velocity, confirmations, deceleration_ratio, trailing_stop, cooldown in product(
        (0.00001, 0.00002, 0.00003, 0.00004, 0.00006),
        (0.0, 0.00005, 0.0001, 0.0002),
        (2, 3),
        (0.5, 0.75),
        (0.0015, 0.0025, 0.004, 0.006, 0.008),
        (300, 600),
    ):
        settings = PriceAccelerationSettings(
            acceleration_threshold=threshold,
            minimum_velocity=minimum_velocity,
            acceleration_confirmation_bars=confirmations,
            deceleration_threshold=threshold * deceleration_ratio,
            trailing_stop_fraction=trailing_stop,
            cooldown_seconds=cooldown,
        )
        development = evaluate(sessions, settings, range(development_count))
        validation = evaluate(sessions, settings, range(development_count, session_count))
        if development.trades < args.minimum_trades or validation.trades < 3:
            continue
        score = min(development.profit_factor, validation.profit_factor)
        if development.mean_return > 0 and validation.mean_return > 0:
            candidates.append((score, settings, development, validation))

    print(
        f"sessions={session_count} development={development_count} "
        f"validation={args.validation_sessions} instruments={len(sessions)}"
    )
    print(
        f"baseline | dev={baseline_development.trades} "
        f"pf={baseline_development.profit_factor:.2f} "
        f"mean={baseline_development.mean_return:+.3%} "
        f"dd={baseline_development.maximum_drawdown:.1%} | "
        f"val={baseline_validation.trades} "
        f"pf={baseline_validation.profit_factor:.2f} "
        f"mean={baseline_validation.mean_return:+.3%} "
        f"dd={baseline_validation.maximum_drawdown:.1%}"
    )
    if not candidates:
        print("No parameter set had positive mean return in both periods.")
        return
    for _, settings, development, validation in sorted(
        candidates, key=lambda candidate: candidate[0], reverse=True
    )[:20]:
        print(
            f"threshold={settings.acceleration_threshold:.6f} "
            f"velocity={settings.minimum_velocity:.6f} "
            f"confirm={settings.acceleration_confirmation_bars} "
            f"decel={settings.deceleration_threshold:.6f} "
            f"trail={settings.trailing_stop_fraction:.4f} "
            f"cooldown={settings.cooldown_seconds} | "
            f"dev={development.trades} pf={development.profit_factor:.2f} "
            f"mean={development.mean_return:+.3%} dd={development.maximum_drawdown:.1%} | "
            f"val={validation.trades} pf={validation.profit_factor:.2f} "
            f"mean={validation.mean_return:+.3%} dd={validation.maximum_drawdown:.1%}"
        )


if __name__ == "__main__":
    main()