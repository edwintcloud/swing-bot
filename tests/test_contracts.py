import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from swing_bot.contracts import (
    ResolvedContract,
    load_resolved_contracts,
    resolve_instruments,
    save_resolved_contracts,
    select_resolved_contracts,
)


@dataclass
class Value:
    value: str


@dataclass
class FakeInstrument:
    id: Value
    symbol: Value
    venue: Value
    currency: Value
    info: dict[str, object]


class ContractTests(unittest.TestCase):
    def test_resolves_current_nautilus_nested_contract_metadata(self) -> None:
        instrument = FakeInstrument(
            id=Value("NBIS.NASDAQ"),
            symbol=Value("NBIS"),
            venue=Value("XNAS"),
            currency=Value("USD"),
            info={
                "contract": {
                    "conId": 789,
                    "primaryExchange": "NASDAQ",
                    "secType": "STK",
                    "currency": "USD",
                }
            },
        )

        resolved = resolve_instruments(["NBIS"], [instrument])

        self.assertEqual(
            resolved,
            (ResolvedContract("NBIS", "NBIS.NASDAQ", 789, "NASDAQ"),),
        )

    def test_resolves_and_round_trips_contracts(self) -> None:
        instrument = FakeInstrument(
            id=Value("MU.NASDAQ"),
            symbol=Value("MU"),
            venue=Value("NASDAQ"),
            currency=Value("USD"),
            info={"conId": 123, "primaryExchange": "NASDAQ", "secType": "STK"},
        )
        resolved = resolve_instruments(["MU"], [instrument])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.json"
            save_resolved_contracts(resolved, path)
            self.assertEqual(load_resolved_contracts(path), resolved)

    def test_missing_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "MU=0"):
            resolve_instruments(["MU"], [])

    def test_selects_only_configured_contracts_in_universe_order(self) -> None:
        contracts = (
            ResolvedContract("AMZN", "AMZN.NASDAQ", 1, "NASDAQ"),
            ResolvedContract("TSLA", "TSLA.NASDAQ", 2, "NASDAQ"),
            ResolvedContract("INTC", "INTC.NASDAQ", 3, "NASDAQ"),
        )

        selected = select_resolved_contracts(contracts, ("INTC", "TSLA"))

        self.assertEqual([contract.symbol for contract in selected], ["INTC", "TSLA"])

    def test_missing_configured_contract_is_rejected(self) -> None:
        contracts = (ResolvedContract("INTC", "INTC.NASDAQ", 3, "NASDAQ"),)

        with self.assertRaisesRegex(ValueError, "missing configured symbols: TSLA"):
            select_resolved_contracts(contracts, ("INTC", "TSLA"))

    def test_incomplete_identity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "con_id"):
            ResolvedContract("MU", "MU.NASDAQ", 0, "NASDAQ")


if __name__ == "__main__":
    unittest.main()
