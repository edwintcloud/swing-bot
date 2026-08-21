from __future__ import annotations

import json
import logging
import os
import queue
import threading
from collections.abc import Callable, Mapping
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
STOP = object()
_notifier: TelegramNotifier | None = None


def _money(value: float | None) -> str:
    return "unavailable" if value is None else f"${value:,.2f}"


def bot_started_message(mode: str) -> str:
    return f"Bot started\nMode: {mode.upper()}"


def trade_entered_message(
    *, ticker: str, quantity: float, price: float, equity: float | None
) -> str:
    return "\n".join(
        (
            "Trade entered",
            f"Ticker: {ticker}",
            f"Quantity: {quantity:g}",
            f"Price/share: {_money(price)}",
            f"Total: {_money(quantity * price)}",
            f"Current equity: {_money(equity)}",
        )
    )


def trade_closed_message(
    *,
    ticker: str,
    quantity: float,
    price: float,
    entry_price: float,
    profit: float,
    equity: float | None,
) -> str:
    entry_notional = quantity * entry_price
    profit_percent = profit / entry_notional * 100 if entry_notional else 0.0
    return "\n".join(
        (
            "Trade closed",
            f"Ticker: {ticker}",
            f"Quantity: {quantity:g}",
            f"Price/share: {_money(price)}",
            f"Total: {_money(quantity * price)}",
            f"Profit: {_money(profit)} ({profit_percent:+.2f}%)",
            f"Current equity: {_money(equity)}",
        )
    )


def bot_stopped_message(mode: str, reason: str) -> str:
    return f"Bot stopped or disconnected\nMode: {mode.upper()}\nReason: {reason}"


def bot_disconnected_message(mode: str, reason: str) -> str:
    return f"Bot disconnected\nMode: {mode.upper()}\nReason: {reason}"


def bot_reconnected_message(mode: str, reason: str) -> str:
    return f"Bot reconnected\nMode: {mode.upper()}\nReason: {reason}"


def _post_message(token: str, chat_id: str, text: str, timeout: float) -> None:
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        response.read()


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        timeout: float = 10.0,
        sender: Callable[[str, str, str, float], None] = _post_message,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout
        self._sender = sender
        self._messages: queue.Queue[str | object] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="telegram-notifier", daemon=True)
        self._thread.start()

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> TelegramNotifier | None:
        values = os.environ if environment is None else environment
        token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = values.get("TELEGRAM_CHAT_ID", "").strip()
        if not token and not chat_id:
            return None
        if not token or not chat_id:
            LOGGER.error(
                "Telegram notifications disabled: TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID must both be set"
            )
            return None
        return cls(token, chat_id)

    def send(self, text: str) -> None:
        self._messages.put(text)

    def close(self, timeout: float = 5.0) -> None:
        self._messages.put(STOP)
        self._thread.join(timeout)
        if self._thread.is_alive():
            LOGGER.error("Telegram notifier did not stop within %.1f seconds", timeout)

    def _run(self) -> None:
        while True:
            message = self._messages.get()
            try:
                if message is STOP:
                    return
                try:
                    self._sender(self._token, self._chat_id, str(message), self._timeout)
                except Exception as exc:  # noqa: BLE001
                    LOGGER.error("Telegram notification failed: %s", exc)
            finally:
                self._messages.task_done()


def configure_telegram(environment: Mapping[str, str] | None = None) -> TelegramNotifier | None:
    global _notifier
    _notifier = TelegramNotifier.from_environment(environment)
    return _notifier


def telegram_notifier() -> TelegramNotifier | None:
    return _notifier


def close_telegram() -> None:
    global _notifier
    if _notifier is not None:
        _notifier.close()
        _notifier = None
