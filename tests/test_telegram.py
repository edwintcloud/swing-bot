import unittest

from swing_bot.telegram import (
    TelegramNotifier,
    bot_disconnected_message,
    bot_started_message,
    bot_stopped_message,
    trade_closed_message,
    trade_entered_message,
)


class TelegramMessageTests(unittest.TestCase):
    def test_event_messages_include_requested_trade_details(self) -> None:
        self.assertEqual(bot_started_message("paper"), "Bot started\nMode: PAPER")
        self.assertIn(
            "Total: $1,250.00",
            trade_entered_message(ticker="MU", quantity=10, price=125, equity=25_000),
        )
        closed = trade_closed_message(
            ticker="MU",
            quantity=10,
            price=130,
            entry_price=125,
            profit=50,
            equity=25_050,
        )
        self.assertIn("Profit: $50.00 (+4.00%)", closed)
        self.assertIn("Current equity: $25,050.00", closed)
        self.assertIn("Reason: IB connection lost", bot_stopped_message("live", "IB connection lost"))
        self.assertIn(
            "Reason: IB 1100: Connectivity lost",
            bot_disconnected_message("paper", "IB 1100: Connectivity lost"),
        )

    def test_notifier_sends_on_worker_and_contains_transport_errors(self) -> None:
        sent: list[str] = []

        def sender(_token: str, _chat_id: str, text: str, _timeout: float) -> None:
            sent.append(text)
            if text == "fails":
                raise OSError("offline")

        notifier = TelegramNotifier("token", "chat", sender=sender)
        notifier.send("first")
        notifier.send("fails")
        notifier.send("last")
        notifier.close()

        self.assertEqual(sent, ["first", "fails", "last"])

    def test_environment_requires_both_credentials(self) -> None:
        self.assertIsNone(TelegramNotifier.from_environment({}))
        self.assertIsNone(TelegramNotifier.from_environment({"TELEGRAM_BOT_TOKEN": "token"}))


if __name__ == "__main__":
    unittest.main()