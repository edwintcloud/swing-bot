from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MethodType
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from nautilus_trader.persistence.catalog import ParquetDataCatalog

from swing_bot.contracts import ResolvedContract

IB_TIMEZONE = ZoneInfo("America/New_York")
HMDS_NO_DATA_MESSAGE = "HMDS query returned no data:"


@dataclass(frozen=True)
class BarRecord:
    instrument_id: str
    bar_type: str
    ts_event: int
    ts_init: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class CatalogManifest:
    source: str
    start: str
    end: str
    row_counts: dict[str, int]
    first_timestamp: dict[str, int]
    last_timestamp: dict[str, int]
    checksum: str
    nautilus_version: str


@dataclass(frozen=True)
class DownloadUnit:
    bar_specification: str
    start: datetime
    end: datetime
    cache_key: str
    use_rth: bool


class HistoricalBarClient(Protocol):
    async def connect(self) -> None: ...

    async def request_instruments(self, *, contracts: list[Any]) -> Sequence[Any]: ...

    async def request_bars(self, **kwargs: Any) -> Sequence[Any]: ...


def complete_hmds_no_data_requests(client: Any) -> None:
    """Complete known-empty IB historical requests without waiting for a timeout."""
    ib_client = client._client
    original_handler = ib_client._handle_request_error

    async def handle_request_error(
        self: Any, req_id: int, error_code: int, error_string: str
    ) -> None:
        if error_code == 162 and HMDS_NO_DATA_MESSAGE in error_string:
            self._end_request(req_id, success=True)
            return
        await original_handler(req_id, error_code, error_string)

    ib_client._handle_request_error = MethodType(handle_request_error, ib_client)


def _number(value: Any) -> float:
    for method_name in ("as_double", "as_f64"):
        method = getattr(value, method_name, None)
        if method is not None:
            return float(method())
    return float(value)


def bar_to_record(bar: Any) -> BarRecord:
    return BarRecord(
        instrument_id=str(bar.bar_type.instrument_id),
        bar_type=str(bar.bar_type),
        ts_event=int(bar.ts_event),
        ts_init=int(bar.ts_init),
        open=_number(bar.open),
        high=_number(bar.high),
        low=_number(bar.low),
        close=_number(bar.close),
        volume=_number(bar.volume),
    )


def validate_bar_records(
    records: Sequence[BarRecord], *, minimum_hourly_bars: int = 220
) -> dict[str, int]:
    if not records:
        raise ValueError("No bars were returned")
    grouped: dict[str, list[BarRecord]] = {}
    for record in records:
        grouped.setdefault(record.bar_type, []).append(record)
        if record.low > min(record.open, record.close) or record.high < max(
            record.open, record.close
        ):
            raise ValueError(f"Invalid OHLC values for {record.bar_type} at {record.ts_init}")
        if record.low > record.high or record.volume < 0:
            raise ValueError(f"Invalid bar range or volume for {record.bar_type}")
        if record.ts_init < record.ts_event:
            raise ValueError(f"ts_init precedes ts_event for {record.bar_type}")

    counts: dict[str, int] = {}
    for bar_type, values in grouped.items():
        timestamps = [record.ts_init for record in values]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise ValueError(f"Timestamps must be unique and monotonic for {bar_type}")
        counts[bar_type] = len(values)
        if (
            minimum_hourly_bars > 0
            and "1-HOUR-" in bar_type
            and len(values) < minimum_hourly_bars
        ):
            raise ValueError(
                f"Hourly warmup requires {minimum_hourly_bars} bars for {bar_type}"
            )
    return counts


def build_manifest(
    records: Sequence[BarRecord], *, start: datetime, end: datetime, nautilus_version: str
) -> CatalogManifest:
    counts = Counter(record.bar_type for record in records)
    first = {
        bar_type: min(record.ts_init for record in records if record.bar_type == bar_type)
        for bar_type in counts
    }
    last = {
        bar_type: max(record.ts_init for record in records if record.bar_type == bar_type)
        for bar_type in counts
    }
    digest_rows = [
        f"{record.bar_type}|{record.ts_init}|{record.open}|{record.high}|{record.low}|{record.close}|{record.volume}"
        for record in records
    ]
    checksum = hashlib.sha256("\n".join(digest_rows).encode("ascii")).hexdigest()
    return CatalogManifest(
        source="interactive_brokers",
        start=start.isoformat(),
        end=end.isoformat(),
        row_counts=dict(sorted(counts.items())),
        first_timestamp=first,
        last_timestamp=last,
        checksum=checksum,
        nautilus_version=nautilus_version,
    )


def write_manifest(manifest: CatalogManifest, path: Path | str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def history_chunks(
    start: datetime, end: datetime, chunk_days: int
) -> tuple[tuple[datetime, datetime], ...]:
    if start >= end:
        raise ValueError("Historical start must precede end")
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return tuple(chunks)


def download_units(
    *,
    contracts: Sequence[ResolvedContract],
    start: datetime,
    end: datetime,
    hourly_chunk_days: int,
    minute_chunk_days: int,
    include_second_bars: bool = False,
    second_chunk_minutes: int = 30,
) -> tuple[DownloadUnit, ...]:
    if start >= end:
        raise ValueError("Historical start must precede end")
    contract_identity = ",".join(
        str(contract.con_id) for contract in sorted(contracts, key=lambda item: item.con_id)
    )
    units: list[DownloadUnit] = []
    specifications = (
        ("1-HOUR-LAST", timedelta(days=hourly_chunk_days), False),
        ("1-MINUTE-LAST", timedelta(days=minute_chunk_days), False),
    )
    if include_second_bars:
        if second_chunk_minutes <= 0:
            raise ValueError("second_chunk_minutes must be positive")
        specifications += (
            ("5-SECOND-LAST", timedelta(minutes=second_chunk_minutes), True),
        )
    for bar_specification, chunk_size, use_rth in specifications:
        if chunk_size <= timedelta(0):
            raise ValueError("Download chunk size must be positive")
        chunks: list[tuple[datetime, datetime]] = []
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + chunk_size, end)
            chunks.append((cursor, chunk_end))
            cursor = chunk_end
        for chunk_start, chunk_end in chunks:
            identity = (
                f"{contract_identity}|{bar_specification}|"
                f"{chunk_start.isoformat()}|{chunk_end.isoformat()}|use_rth={str(use_rth).lower()}"
            )
            units.append(
                DownloadUnit(
                    bar_specification=bar_specification,
                    start=chunk_start,
                    end=chunk_end,
                    cache_key=hashlib.sha256(identity.encode("ascii")).hexdigest()[:20],
                    use_rth=use_rth,
                )
            )
    return tuple(units)


def cached_unit_complete(cache_path: Path | str, unit: DownloadUnit) -> bool:
    return (Path(cache_path) / unit.cache_key / "complete").is_file()


def mark_cached_unit_complete(cache_path: Path | str, unit: DownloadUnit) -> None:
    unit_path = Path(cache_path) / unit.cache_key
    unit_path.mkdir(parents=True, exist_ok=True)
    marker = unit_path / "complete"
    temporary = unit_path / "complete.tmp"
    temporary.write_text("\n", encoding="ascii")
    temporary.replace(marker)


def _cached_unit_bars(cache_path: Path, unit: DownloadUnit) -> list[Any]:
    unit_catalog_path = cache_path / unit.cache_key / "catalog"
    if not unit_catalog_path.exists():
        return []
    return list(ParquetDataCatalog(unit_catalog_path).bars())


def _write_cached_unit(cache_path: Path, unit: DownloadUnit, bars: Sequence[Any]) -> None:
    unit_path = cache_path / unit.cache_key
    if bars:
        ParquetDataCatalog(unit_path / "catalog").write_data(list(bars))
    mark_cached_unit_complete(cache_path, unit)


def _replace_catalog(
    path: Path,
    instruments: Sequence[Any],
    bars: Sequence[Any],
    manifest: CatalogManifest,
) -> None:
    staging = path.with_name(f"{path.name}.staging")
    backup = path.with_name(f"{path.name}.backup")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    staging.mkdir(parents=True)
    catalog = ParquetDataCatalog(staging)
    catalog.write_data(list(instruments))
    catalog.write_data(list(bars))
    write_manifest(manifest, staging / "manifest.json")
    if path.exists():
        path.replace(backup)
    staging.replace(path)
    shutil.rmtree(backup, ignore_errors=True)


def ib_request_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("IB request datetime must include a timezone")
    return value.astimezone(IB_TIMEZONE).replace(tzinfo=None)


async def download_history(
    *,
    contracts: Sequence[ResolvedContract],
    start: datetime,
    end: datetime,
    catalog_path: Path | str,
    client_factory: Callable[[], HistoricalBarClient],
    timeout: int = 120,
    minute_chunk_days: int = 30,
    hourly_chunk_days: int = 30,
    include_second_bars: bool = False,
    second_chunk_minutes: int = 30,
    retries: int = 3,
    manifest_path: Path | str | None = None,
    cache_path: Path | str | None = None,
) -> tuple[list[Any], list[Any]]:
    units = download_units(
        contracts=contracts,
        start=start,
        end=end,
        hourly_chunk_days=hourly_chunk_days,
        minute_chunk_days=minute_chunk_days,
        include_second_bars=include_second_bars,
        second_chunk_minutes=second_chunk_minutes,
    )
    if retries < 0:
        raise ValueError("retries cannot be negative")
    path = Path(catalog_path).resolve()
    resolved_cache_path = (
        Path(cache_path).resolve()
        if cache_path is not None
        else path.with_name(f"{path.name}.download-cache")
    )
    client = client_factory()
    await client.connect()
    ib_contracts = [contract.as_ib_contract() for contract in contracts]
    instruments = list(await client.request_instruments(contracts=ib_contracts))
    downloaded: list[Any] = []
    for unit in units:
        if cached_unit_complete(resolved_cache_path, unit):
            downloaded.extend(_cached_unit_bars(resolved_cache_path, unit))
            continue
        for attempt in range(retries + 1):
            try:
                bars = list(
                    await client.request_bars(
                        bar_specifications=[unit.bar_specification],
                        start_date_time=ib_request_datetime(unit.start),
                        end_date_time=ib_request_datetime(unit.end),
                        tz_name="America/New_York",
                        contracts=ib_contracts,
                        use_rth=unit.use_rth,
                        timeout=timeout,
                    ),
                )
                _write_cached_unit(resolved_cache_path, unit, bars)
                downloaded.extend(bars)
                break
            except Exception:
                if attempt == retries:
                    raise
                await asyncio.sleep(2**attempt)

    unique: dict[tuple[str, int], tuple[Any, BarRecord]] = {}
    for bar in downloaded:
        record = bar_to_record(bar)
        unique[(record.bar_type, record.ts_init)] = (bar, record)
    ordered = sorted(unique.values(), key=lambda item: (item[1].bar_type, item[1].ts_init))
    bars = [item[0] for item in ordered]
    records = [item[1] for item in ordered]
    validate_bar_records(
        records,
        minimum_hourly_bars=0 if include_second_bars else 220,
    )
    from nautilus_trader import __version__ as nautilus_version

    manifest = build_manifest(
        records,
        start=start,
        end=end,
        nautilus_version=nautilus_version,
    )
    _replace_catalog(path, instruments, bars, manifest)
    if manifest_path is not None and Path(manifest_path).resolve() != path / "manifest.json":
        write_manifest(manifest, manifest_path)
    return instruments, bars
