from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from statistics import fmean

from nautilus_trader.persistence.catalog import ParquetDataCatalog


@dataclass(frozen=True)
class MarketBar:
    timestamp_ns: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Signal:
    timestamp_ns: int
    side: str
    limit_price: float


@dataclass(frozen=True)
class Trade:
    opened_ns: int
    closed_ns: int
    return_fraction: float


@dataclass(frozen=True)
class Metrics:
    trades: int
    win_rate: float
    compounded_return: float
    maximum_drawdown: float


def load_bars(catalog_path: Path, instrument_id: str, specification: str) -> list[MarketBar]:
    catalog = ParquetDataCatalog(catalog_path)
    prefix = f"{instrument_id}-{specification}-"
    bars = sorted(
        (bar for bar in catalog.bars() if str(bar.bar_type).startswith(prefix)),
        key=lambda bar: bar.ts_init,
    )
    return [
        MarketBar(
            timestamp_ns=bar.ts_init,
            open=bar.open.as_double(),
            high=bar.high.as_double(),
            low=bar.low.as_double(),
            close=bar.close.as_double(),
        )
        for bar in bars
    ]


def continuation_signals(
    bars: list[MarketBar],
    *,
    start_ns: int,
    end_ns: int,
    fast_period: int,
    slow_period: int,
    separation: float,
    crossover_band: float,
) -> list[Signal]:
    closes = [bar.close for bar in bars]
    signals: list[Signal] = []
    for index in range(slow_period, len(bars)):
        bar = bars[index]
        if not start_ns <= bar.timestamp_ns < end_ns:
            continue
        previous_fast = fmean(closes[index - fast_period : index])
        fast = fmean(closes[index - fast_period + 1 : index + 1])
        slow = fmean(closes[index - slow_period + 1 : index + 1])
        previous_close = closes[index - 1]
        current_close = closes[index]
        crossed_up = previous_close <= previous_fast and fast < current_close <= fast * (
            1.0 + crossover_band
        )
        crossed_down = previous_close >= previous_fast and fast * (
            1.0 - crossover_band
        ) <= current_close < fast
        if fast >= slow * (1.0 + separation) and crossed_up:
            signals.append(Signal(bar.timestamp_ns, "LONG", current_close))
        elif fast <= slow * (1.0 - separation) and crossed_down:
            signals.append(Signal(bar.timestamp_ns, "SHORT", current_close))
    return signals


def replay(signals: list[Signal], minute_bars: list[MarketBar], trailing_stop: float) -> list[Trade]:
    signal_index = 0
    pending: Signal | None = None
    position: tuple[str, float, float, int] | None = None
    trades: list[Trade] = []
    for bar in minute_bars:
        while signal_index < len(signals) and signals[signal_index].timestamp_ns <= bar.timestamp_ns:
            if pending is None and position is None:
                pending = signals[signal_index]
            signal_index += 1
        if pending is not None:
            if pending.side == "LONG" and bar.low <= pending.limit_price:
                entry = min(bar.open, pending.limit_price)
                position = (pending.side, entry, entry, bar.timestamp_ns)
                pending = None
            elif pending.side == "SHORT" and bar.high >= pending.limit_price:
                entry = max(bar.open, pending.limit_price)
                position = (pending.side, entry, entry, bar.timestamp_ns)
                pending = None
            continue
        if position is None:
            continue
        side, entry, extreme, opened_ns = position
        if side == "LONG":
            extreme = max(extreme, bar.high)
            stop = extreme * (1.0 - trailing_stop)
            if bar.low <= stop:
                exit_price = min(bar.open, stop)
                trades.append(Trade(opened_ns, bar.timestamp_ns, exit_price / entry - 1.0))
                position = None
            else:
                position = (side, entry, extreme, opened_ns)
        else:
            extreme = min(extreme, bar.low)
            stop = extreme * (1.0 + trailing_stop)
            if bar.high >= stop:
                exit_price = max(bar.open, stop)
                trades.append(Trade(opened_ns, bar.timestamp_ns, entry / exit_price - 1.0))
                position = None
            else:
                position = (side, entry, extreme, opened_ns)
    return trades


def metrics(
    trades: list[Trade], start_ns: int, end_ns: int, position_fraction: float
) -> Metrics:
    selected = [trade for trade in trades if start_ns <= trade.opened_ns < end_ns]
    if not selected:
        return Metrics(0, 0.0, 0.0, 0.0)
    equity = 1.0
    high_water = equity
    maximum_drawdown = 0.0
    for trade in sorted(selected, key=lambda item: item.closed_ns):
        equity *= 1.0 + trade.return_fraction * position_fraction
        high_water = max(high_water, equity)
        maximum_drawdown = max(maximum_drawdown, 1.0 - equity / high_water)
    return Metrics(
        trades=len(selected),
        win_rate=sum(trade.return_fraction > 0 for trade in selected) / len(selected),
        compounded_return=equity - 1.0,
        maximum_drawdown=maximum_drawdown,
    )


def timestamp_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000_000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog"))
    parser.add_argument("--start", default="2026-01-01T00:00:00+00:00")
    parser.add_argument("--split", default="2026-05-01T00:00:00+00:00")
    parser.add_argument("--end", default="2026-08-21T00:00:00+00:00")
    parser.add_argument("--position-fraction", type=float, default=0.10)
    args = parser.parse_args()
    start_ns, split_ns, end_ns = map(timestamp_ns, (args.start, args.split, args.end))
    instruments = ("NBIS.NASDAQ", "INTC.NASDAQ")
    hourly = {
        instrument: load_bars(args.catalog, instrument, "1-HOUR-LAST")
        for instrument in instruments
    }
    minute = {
        instrument: [
            bar
            for bar in load_bars(args.catalog, instrument, "1-MINUTE-LAST")
            if start_ns <= bar.timestamp_ns < end_ns
        ]
        for instrument in instruments
    }
    candidates = []
    parameters = product(
        (10, 20, 40),
        (100, 200, 300),
        (0.0, 0.02, 0.05, 0.10),
        (0.01, 0.03, 0.05),
        (0.01, 0.02, 0.03, 0.05, 0.08),
    )
    for fast, slow, separation, crossover_band, trailing_stop in parameters:
        if fast >= slow:
            continue
        trades: list[Trade] = []
        for instrument in instruments:
            signals = continuation_signals(
                hourly[instrument],
                start_ns=start_ns,
                end_ns=end_ns,
                fast_period=fast,
                slow_period=slow,
                separation=separation,
                crossover_band=crossover_band,
            )
            trades.extend(replay(signals, minute[instrument], trailing_stop))
        development = metrics(trades, start_ns, split_ns, args.position_fraction)
        validation = metrics(trades, split_ns, end_ns, args.position_fraction)
        full = metrics(trades, start_ns, end_ns, args.position_fraction)
        if development.trades >= 8 and validation.trades >= 5:
            score = min(development.win_rate, validation.win_rate) + min(
                development.compounded_return, validation.compounded_return
            )
            candidates.append(
                (score, fast, slow, separation, crossover_band, trailing_stop, development, validation, full)
            )
    for candidate in sorted(candidates, reverse=True)[:20]:
        _, fast, slow, separation, band, trail, development, validation, full = candidate
        print(
            f"fast={fast} slow={slow} separation={separation:.0%} band={band:.0%} "
            f"trail={trail:.0%} | dev={development.trades} {development.win_rate:.1%} "
            f"{development.compounded_return:+.1%} dd={development.maximum_drawdown:.1%} | "
            f"val={validation.trades} {validation.win_rate:.1%} "
            f"{validation.compounded_return:+.1%} dd={validation.maximum_drawdown:.1%} | "
            f"full={full.trades} {full.win_rate:.1%} {full.compounded_return:+.1%} "
            f"dd={full.maximum_drawdown:.1%}"
        )


if __name__ == "__main__":
    main()