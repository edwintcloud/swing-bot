from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from nautilus_trader.adapters.interactive_brokers.common import IBContract


@dataclass(frozen=True)
class ResolvedContract:
    symbol: str
    instrument_id: str
    con_id: int
    primary_exchange: str
    security_type: str = "STK"
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.upper():
            raise ValueError("Resolved symbol must be uppercase")
        missing = []
        if not self.instrument_id:
            missing.append("instrument_id")
        if self.con_id <= 0:
            missing.append("con_id")
        if not self.primary_exchange:
            missing.append("primary_exchange")
        if missing:
            raise ValueError(f"Resolved contract identity is incomplete: {', '.join(missing)}")

    def as_ib_contract(self) -> IBContract:
        return IBContract(
            secType=self.security_type,
            conId=self.con_id,
            exchange="SMART",
            primaryExchange=self.primary_exchange,
            symbol=self.symbol,
            currency=self.currency,
        )


class HistoricalInstrumentClient(Protocol):
    async def connect(self) -> None: ...

    async def request_instruments(self, *, contracts: list[IBContract]) -> Sequence[Any]: ...


def requested_stock_contracts(symbols: Sequence[str]) -> list[IBContract]:
    return [
        IBContract(secType="STK", exchange="SMART", symbol=symbol, currency="USD")
        for symbol in symbols
    ]


def _instrument_value(instrument: Any, name: str) -> str:
    value = getattr(instrument, name, "")
    return str(getattr(value, "value", value))


def resolve_instruments(
    symbols: Sequence[str], instruments: Sequence[Any]
) -> tuple[ResolvedContract, ...]:
    matches: dict[str, list[ResolvedContract]] = {symbol: [] for symbol in symbols}
    for instrument in instruments:
        info = dict(getattr(instrument, "info", {}) or {})
        contract = dict(info.get("contract") or {})
        symbol = _instrument_value(instrument, "symbol").upper()
        if symbol not in matches:
            continue
        con_id = int(
            contract.get("conId")
            or contract.get("con_id")
            or info.get("conId")
            or info.get("con_id")
            or 0
        )
        primary_exchange = str(
            contract.get("primaryExchange")
            or contract.get("primary_exchange")
            or info.get("primaryExchange")
            or info.get("primary_exchange")
            or _instrument_value(instrument, "venue")
        )
        security_type = str(
            contract.get("secType")
            or contract.get("security_type")
            or info.get("secType")
            or info.get("security_type")
            or "STK"
        )
        currency = str(contract.get("currency") or _instrument_value(instrument, "currency") or "USD")
        matches[symbol].append(
            ResolvedContract(
                symbol=symbol,
                instrument_id=_instrument_value(instrument, "id"),
                con_id=con_id,
                primary_exchange=primary_exchange,
                security_type=security_type,
                currency=currency,
            )
        )

    problems = [symbol for symbol, candidates in matches.items() if len(candidates) != 1]
    if problems:
        details = ", ".join(f"{symbol}={len(matches[symbol])}" for symbol in problems)
        raise ValueError(f"Each symbol must resolve exactly once: {details}")
    return tuple(matches[symbol][0] for symbol in symbols)


async def discover_contracts(
    symbols: Sequence[str],
    client_factory: Callable[[], HistoricalInstrumentClient],
) -> tuple[ResolvedContract, ...]:
    client = client_factory()
    await client.connect()
    instruments = await client.request_instruments(contracts=requested_stock_contracts(symbols))
    return resolve_instruments(symbols, instruments)


def save_resolved_contracts(contracts: Sequence[ResolvedContract], path: Path | str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"contracts": [asdict(contract) for contract in contracts]}
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")


def load_resolved_contracts(path: Path | str) -> tuple[ResolvedContract, ...]:
    payload = json.loads(Path(path).read_text(encoding="ascii"))
    if set(payload) != {"contracts"} or not isinstance(payload["contracts"], list):
        raise ValueError("Resolved contract file must contain a contracts list")
    contracts = tuple(ResolvedContract(**item) for item in payload["contracts"])
    if len({contract.symbol for contract in contracts}) != len(contracts):
        raise ValueError("Resolved contract symbols must be unique")
    return contracts


def select_resolved_contracts(
    contracts: Sequence[ResolvedContract], symbols: Sequence[str]
) -> tuple[ResolvedContract, ...]:
    by_symbol = {contract.symbol: contract for contract in contracts}
    missing = [symbol for symbol in symbols if symbol not in by_symbol]
    if missing:
        raise ValueError(f"Resolved contract file is missing configured symbols: {', '.join(missing)}")
    return tuple(by_symbol[symbol] for symbol in symbols)
