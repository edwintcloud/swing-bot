from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _iso_timestamp(timestamp_ns: int) -> str:
    return datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class DashboardCommand:
    command_id: str
    action: str
    payload: dict[str, Any]


class DashboardBridge:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.commands_path = self.root / "commands"
        self.state_path = self.root / "state.json"
        self.equity_path = self.root / "equity.jsonl"
        self.trades_path = self.root / "trades.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.commands_path.mkdir(parents=True, exist_ok=True)
        previous = self.read_state()
        self.paused = bool(previous.get("paused", False))
        self.last_command = previous.get("last_command")
        self._last_equity_bucket = self._read_last_equity_bucket()
        self._trade_ids = self._read_trade_ids()

    def read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return value if isinstance(value, dict) else {}

    def read_commands(self) -> tuple[DashboardCommand, ...]:
        commands: list[DashboardCommand] = []
        for path in sorted(self.commands_path.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                command_id = str(value["id"])
                action = str(value["action"])
                payload = value.get("payload", {})
                if not isinstance(payload, dict):
                    raise TypeError("command payload must be an object")
                commands.append(DashboardCommand(command_id, action, payload))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
                pass
            finally:
                path.unlink(missing_ok=True)
        return tuple(commands)

    def acknowledge(self, command: DashboardCommand, result: str) -> None:
        self.last_command = {
            "id": command.command_id,
            "action": command.action,
            "result": result,
            "processed_at": datetime.now(UTC).isoformat(),
        }

    def publish(
        self,
        *,
        timestamp_ns: int,
        equity: float | None,
        positions: list[dict[str, Any]],
        status: str,
    ) -> None:
        state = {
            "updated_at": _iso_timestamp(timestamp_ns),
            "status": status,
            "paused": self.paused,
            "equity": equity,
            "positions": positions,
            "last_command": self.last_command,
        }
        _atomic_json(self.state_path, state)
        if equity is not None:
            bucket = timestamp_ns // 60_000_000_000
            if bucket != self._last_equity_bucket:
                self._append_json_line(
                    self.equity_path,
                    {"timestamp": _iso_timestamp(timestamp_ns), "equity": equity},
                )
                self._last_equity_bucket = bucket

    def record_trade(self, trade: dict[str, Any]) -> None:
        trade_id = str(trade.get("position_id", ""))
        if not trade_id or trade_id in self._trade_ids:
            return
        self._append_json_line(self.trades_path, trade)
        self._trade_ids.add(trade_id)

    def _append_json_line(self, path: Path, value: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(value, separators=(",", ":")) + "\n")
            output.flush()
            os.fsync(output.fileno())

    def _read_last_equity_bucket(self) -> int | None:
        records = read_json_lines(self.equity_path)
        if not records:
            return None
        try:
            timestamp = datetime.fromisoformat(str(records[-1]["timestamp"]))
        except (KeyError, ValueError):
            return None
        return int(timestamp.timestamp() * 1_000_000_000) // 60_000_000_000

    def _read_trade_ids(self) -> set[str]:
        return {
            str(record["position_id"])
            for record in read_json_lines(self.trades_path)
            if record.get("position_id")
        }


def enqueue_command(root: Path | str, action: str, payload: dict[str, Any]) -> str:
    command_id = uuid4().hex
    commands_path = Path(root) / "commands"
    commands_path.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        commands_path / f"{command_id}.json",
        {
            "id": command_id,
            "action": action,
            "payload": payload,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    return command_id


def read_json_lines(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if limit is not None:
        lines = lines[-limit:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def dashboard_payload(root: Path | str) -> dict[str, Any]:
    bridge_root = Path(root)
    try:
        state = json.loads((bridge_root / "state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {
            "updated_at": None,
            "status": "offline",
            "paused": True,
            "equity": None,
            "positions": [],
            "last_command": None,
        }
    state["equity_curve"] = read_json_lines(bridge_root / "equity.jsonl", limit=2_000)
    state["trades"] = list(reversed(read_json_lines(bridge_root / "trades.jsonl", limit=1_000)))
    return state