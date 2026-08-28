import unittest
from asyncio import run
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from swing_bot.contracts import ResolvedContract
from swing_bot.data import (
    BarRecord,
    cached_unit_complete,
    complete_hmds_no_data_requests,
    download_history,
    download_units,
    history_chunks,
    ib_request_datetime,
    mark_cached_unit_complete,
    validate_bar_records,
)


def record(timestamp: int, *, bar_type: str = "MU.NASDAQ-1-HOUR-LAST-EXTERNAL") -> BarRecord:
    return BarRecord("MU.NASDAQ", bar_type, timestamp, timestamp, 10, 12, 9, 11, 1000)


class DataValidationTests(unittest.TestCase):
    def test_download_history_resumes_completed_units_without_bar_requests(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.requests = 0

            async def connect(self) -> None:
                pass

            async def request_instruments(self, **_kwargs: object) -> list[str]:
                return ["instrument"]

            async def request_bars(self, **kwargs: object) -> list[SimpleNamespace]:
                self.requests += 1
                return [
                    SimpleNamespace(
                        timestamp=self.requests,
                        bar_type=SimpleNamespace(
                            instrument_id="MU.NASDAQ",
                            specification=str(kwargs["bar_specifications"][0]),
                        ),
                    )
                ]

        contract = ResolvedContract("MU", "MU.NASDAQ", 9939, "NASDAQ")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 3, 1, tzinfo=UTC)
        cached_bars: dict[str, list[SimpleNamespace]] = {}

        def write_cached_unit(path: Path, unit: object, bars: list[SimpleNamespace]) -> None:
            cached_bars[unit.cache_key] = bars
            mark_cached_unit_complete(path, unit)

        def read_cached_unit(_path: Path, unit: object) -> list[SimpleNamespace]:
            return cached_bars[unit.cache_key]

        def to_record(bar: SimpleNamespace) -> BarRecord:
            return record(bar.timestamp, bar_type=f"MU.NASDAQ-{bar.bar_type}-EXTERNAL")

        first_client = FakeClient()
        second_client = FakeClient()
        with TemporaryDirectory() as directory, patch(
            "swing_bot.data._write_cached_unit", side_effect=write_cached_unit
        ), patch("swing_bot.data._cached_unit_bars", side_effect=read_cached_unit), patch(
            "swing_bot.data._replace_catalog"
        ), patch("swing_bot.data.bar_to_record", side_effect=to_record), patch(
            "swing_bot.data.validate_bar_records"
        ):
            arguments = {
                "contracts": [contract],
                "start": start,
                "end": end,
                "catalog_path": Path(directory) / "catalog",
                "cache_path": Path(directory) / "cache",
                "hourly_chunk_days": 30,
                "minute_chunk_days": 30,
                "retries": 0,
            }
            run(download_history(client_factory=lambda: first_client, **arguments))
            run(download_history(client_factory=lambda: second_client, **arguments))

        self.assertEqual(first_client.requests, 4)
        self.assertEqual(second_client.requests, 0)

    def test_download_history_rejects_partial_multi_contract_batch(self) -> None:
        class FakeClient:
            async def connect(self) -> None:
                pass

            async def request_instruments(self, **_kwargs: object) -> list[str]:
                return ["instrument"]

            async def request_bars(self, **_kwargs: object) -> list[SimpleNamespace]:
                return [
                    SimpleNamespace(
                        bar_type=SimpleNamespace(instrument_id="MU.NASDAQ")
                    )
                ]

        contracts = [
            ResolvedContract("MU", "MU.NASDAQ", 9939, "NASDAQ"),
            ResolvedContract("AMD", "AMD.NASDAQ", 4391, "NASDAQ"),
        ]
        with TemporaryDirectory() as directory, patch(
            "swing_bot.data._replace_catalog"
        ), patch("swing_bot.data.validate_bar_records"), self.assertRaisesRegex(
            RuntimeError, "omitted requested instruments: AMD.NASDAQ"
        ):
            run(
                download_history(
                    contracts=contracts,
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    end=datetime(2024, 1, 2, tzinfo=UTC),
                    catalog_path=Path(directory) / "catalog",
                    cache_path=Path(directory) / "cache",
                    client_factory=FakeClient,
                    retries=0,
                )
            )

    def test_download_units_use_separate_bar_intervals(self) -> None:
        contracts = [ResolvedContract("MU", "MU.NASDAQ", 9939, "NASDAQ")]
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 3, 1, tzinfo=UTC)

        units = download_units(
            contracts=contracts,
            start=start,
            end=end,
            hourly_chunk_days=30,
            minute_chunk_days=30,
        )

        self.assertEqual([unit.bar_specification for unit in units], [
            "1-HOUR-LAST",
            "1-HOUR-LAST",
            "1-MINUTE-LAST",
            "1-MINUTE-LAST",
        ])
        self.assertTrue(all(not unit.use_rth for unit in units))

    def test_second_bar_units_are_opt_in_regular_hours_and_short_chunked(self) -> None:
        units = download_units(
            contracts=[ResolvedContract("MU", "MU.NASDAQ", 9939, "NASDAQ")],
            start=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
            end=datetime(2024, 1, 2, 15, 31, tzinfo=UTC),
            hourly_chunk_days=30,
            minute_chunk_days=30,
            include_second_bars=True,
            second_chunk_minutes=30,
        )

        second_units = [unit for unit in units if unit.bar_specification == "5-SECOND-LAST"]
        self.assertEqual(len(second_units), 3)
        self.assertTrue(all(unit.use_rth for unit in second_units))
        self.assertEqual(second_units[0].end - second_units[0].start, timedelta(minutes=30))

    def test_second_bar_research_can_skip_hourly_warmup_minimum(self) -> None:
        counts = validate_bar_records(
            [record(1), record(2, bar_type="MU.NASDAQ-5-SECOND-LAST-EXTERNAL")],
            minimum_hourly_bars=0,
        )

        self.assertEqual(counts["MU.NASDAQ-1-HOUR-LAST-EXTERNAL"], 1)
        self.assertEqual(counts["MU.NASDAQ-5-SECOND-LAST-EXTERNAL"], 1)

    def test_completed_empty_unit_is_resumable(self) -> None:
        unit = download_units(
            contracts=[ResolvedContract("MU", "MU.NASDAQ", 9939, "NASDAQ")],
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
            hourly_chunk_days=30,
            minute_chunk_days=30,
        )[0]

        with TemporaryDirectory() as directory:
            self.assertFalse(cached_unit_complete(directory, unit))
            mark_cached_unit_complete(directory, unit)
            self.assertTrue(cached_unit_complete(directory, unit))

    def test_download_units_reject_invalid_range(self) -> None:
        moment = datetime(2024, 1, 1, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "start must precede end"):
            download_units(
                contracts=[ResolvedContract("MU", "MU.NASDAQ", 9939, "NASDAQ")],
                start=moment,
                end=moment,
                hourly_chunk_days=30,
                minute_chunk_days=30,
            )

    def test_hmds_no_data_completes_request_as_empty(self) -> None:
        class FakeIbClient:
            def __init__(self) -> None:
                self.ended: list[tuple[int, bool]] = []
                self.delegated: list[tuple[int, int, str]] = []

            def _end_request(self, req_id: int, success: bool) -> None:
                self.ended.append((req_id, success))

            async def _handle_request_error(
                self, req_id: int, error_code: int, error_string: str
            ) -> None:
                self.delegated.append((req_id, error_code, error_string))

        ib_client = FakeIbClient()
        complete_hmds_no_data_requests(SimpleNamespace(_client=ib_client))

        run(
            ib_client._handle_request_error(
                10009,
                162,
                "Historical Market Data Service error message:HMDS query returned no data: SPCX",
            )
        )

        self.assertEqual(ib_client.ended, [(10009, True)])
        self.assertEqual(ib_client.delegated, [])

    def test_other_162_errors_remain_failures(self) -> None:
        class FakeIbClient:
            def __init__(self) -> None:
                self.ended: list[tuple[int, bool]] = []
                self.delegated: list[tuple[int, int, str]] = []

            def _end_request(self, req_id: int, success: bool) -> None:
                self.ended.append((req_id, success))

            async def _handle_request_error(
                self, req_id: int, error_code: int, error_string: str
            ) -> None:
                self.delegated.append((req_id, error_code, error_string))

        ib_client = FakeIbClient()
        complete_hmds_no_data_requests(SimpleNamespace(_client=ib_client))
        message = "Trading TWS session is connected from a different IP address"

        run(ib_client._handle_request_error(10005, 162, message))

        self.assertEqual(ib_client.ended, [])
        self.assertEqual(ib_client.delegated, [(10005, 162, message)])

    def test_ib_request_datetime_converts_to_naive_new_york_time(self) -> None:
        value = datetime.fromisoformat("2024-07-01T12:00:00+00:00")

        converted = ib_request_datetime(value)

        self.assertEqual(converted, datetime(2024, 7, 1, 8))  # noqa: DTZ001
        self.assertIsNone(converted.tzinfo)

    def test_ib_request_datetime_requires_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            ib_request_datetime(datetime(2024, 1, 1))  # noqa: DTZ001

    def test_history_chunks_cover_range_without_gaps(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 3, 5, tzinfo=UTC)
        chunks = history_chunks(start, end, 30)
        self.assertEqual(chunks[0][0], start)
        self.assertEqual(chunks[-1][1], end)
        self.assertTrue(all(left[1] == right[0] for left, right in pairwise(chunks)))

    def test_history_chunks_reject_invalid_size(self) -> None:
        moment = datetime(2024, 1, 1, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "positive"):
            history_chunks(moment, moment.replace(day=2), 0)

    def test_valid_records_are_counted(self) -> None:
        records = [record(index) for index in range(220)]
        counts = validate_bar_records(records)
        self.assertEqual(counts[records[0].bar_type], 220)

    def test_duplicate_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique and monotonic"):
            validate_bar_records([record(1), record(1)], minimum_hourly_bars=1)

    def test_invalid_ohlc_is_rejected(self) -> None:
        invalid = BarRecord("MU.NASDAQ", "MU.NASDAQ-1-MINUTE-LAST-EXTERNAL", 1, 1, 10, 9, 8, 10, 1)
        with self.assertRaisesRegex(ValueError, "Invalid OHLC"):
            validate_bar_records([invalid], minimum_hourly_bars=1)

    def test_insufficient_hourly_warmup_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "warmup"):
            validate_bar_records([record(1)])


if __name__ == "__main__":
    unittest.main()
