# Swing Bot

A NautilusTrader `1.231.0` trading bot with hourly SMA continuation, portfolio
momentum, and price-acceleration strategies for a fixed US-stock universe (see
[config/universe.toml](config/universe.toml)), Interactive Brokers contract discovery,
historical data ingestion, backtesting, paper trading, and explicitly gated live trading.

This software can place real orders. Validate data and results, run in an IB paper
account first, and read [docs/runbook.md](docs/runbook.md) before enabling live mode.

The evidence-grounded [strategy audit](docs/audit/README.md) evaluates the current
backtests, high-CAGR claims, established strategy families, and a capital-preservation
redesign specification. The redesign is opt-in for backtest, paper, and live modes; the
SMA strategy remains the default.

## ⚠️ Legal & Financial Disclaimer

**This software is for educational and research purposes only. Do not use this code to make actual financial decisions with real money.**

### Not Financial Advice
The code, documentation, and algorithms provided in this repository do not constitute financial advice, investment advice, trading advice, or any other sort of advice. You should not treat any of the repository's content as such. 

### Risk of Loss
Trading equities involves a high degree of risk, particularly when executing active strategies like day trading, swing trading, or momentum trading. Market volatility can lead to substantial financial losses. You could lose some or all of your initial investment. Always conduct your own due diligence and consult with a licensed financial advisor before making any investment decisions.

### Software "As Is"
This trading bot is provided "as is" and "as available" without warranty of any kind, either express or implied, including, but not limited to, the implied warranties of merchantability and fitness for a particular purpose. The authors and contributors make no representations about the accuracy, reliability, or completeness of the software.

### Technical Limitations & Bugs
Algorithmic trading depends on complex systems, including third-party broker APIs, external charting webhooks, and live market data feeds. System failures, network outages, rate limits, or bugs in this code can result in unintended trades, orphaned orders, and significant financial loss. 

### Past Performance
Any backtesting results or simulated performance metrics included in this repository are hypothetical. Past performance of any trading system, indicator, or methodology is not indicative of future results. Live market conditions, including slippage and liquidity constraints, will often yield different outcomes than historical tests.

### Assumption of Liability
Under no circumstances will the authors, contributors, or copyright holders be held liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software. By running this bot, you assume all responsibility for any trading losses you may incur.

## Setup

Requirements: Python 3.13, `uv`, Docker Compose 2.24 or newer, an IB account with the
required market-data permissions, and API access enabled.

```sh
uv sync --extra dev
cp .env.example .env
mkdir -p secrets
printf '%s' 'your-ib-password' > secrets/tws_password.txt
chmod 600 secrets/tws_password.txt
```

Set `TWS_USERID` and the paper `TWS_ACCOUNT` in `.env`. Start Gateway and the paper bot:

```sh
make paper
make status
make logs
```

The React operator console is available at [http://localhost](http://localhost). Its
overview, positions, trades, and controls views show broker net liquidation, persisted
equity, exposure, performance metrics, closed trades, and open positions. Pause blocks
new entries without touching open positions. Flatten first pauses entries, cancels the
strategy's working orders, and submits reduce-only GTC limit exits with a 5% marketable
price collar. A command is acknowledged only after the bot process consumes it.

For frontend development, run `cd ui && npm install && npm run dev`; Vite proxies API and
health requests to a dashboard server listening on port 8080. Production assets are
built into the Docker image.

The dashboard binds only to `127.0.0.1:80`. Set `DASHBOARD_PASSWORD` in `.env` to enable
HTTP Basic authentication; `DASHBOARD_USERNAME` defaults to `admin`. Do not expose the
dashboard publicly without an authenticated TLS reverse proxy.

IB Gateway may require a mobile 2FA approval during login.

## Market Data Subscriptions

The bot requests real-time data and does not fall back to delayed quotes. The IBKR user
logged into Gateway therefore needs Level 1 (top-of-book) US equity market data for every
primary listing exchange in `data/contracts.json`. The robust choice is consolidated US
equity coverage for all networks used by the universe:

- Network A (CTA): NYSE-listed securities.
- Network B (CTA): NYSE American, NYSE Arca, and other regional listings.
- Network C (UTP): Nasdaq-listed securities.

The current universe includes Nasdaq stocks and may include exchange-listed ETFs. Run
`discover-contracts` first and use each contract's `primary_exchange` to determine whether
Network A or B is also required. IBKR package names, prices, professional status rules,
and waivers vary by account and region; confirm the resulting A/B/C coverage under
**Client Portal > Settings > Market Data Subscriptions**. A common non-professional bundle
may combine these feeds, but the exchange coverage is what matters to the bot.

IBKR currently includes free streaming Cboe One and IEX data for US stocks and ETFs, but
it is non-consolidated. Do not rely on it for this strategy: incomplete trades and quotes
can alter hourly signals, minute execution bars, extended-hours prices, and backtest
results.
Historical API requests generally require the corresponding market-data entitlement at
download time. Once the catalog has been downloaded, backtests run offline and require no
active subscription.

Paper accounts do not provide a separate full data entitlement. Configure the paper user
to share the live account's subscriptions and check IBKR's concurrent-session restrictions.
Errors such as IB `354` or `10167`, delayed timestamps, or missing bars indicate that the
logged-in user lacks usable real-time coverage. This stock strategy does not require Level
2/order-book, options, futures, news, or fundamental-data subscriptions.

IB error `162` with "Trading TWS session is connected from a different IP address" means
IBKR has assigned the username's trading or shared market-data session to another public
IP. It does not prove that another visible TWS or Gateway process is running: a live/paper
entitlement session, IBKR Mobile, Client Portal, a hosted integration, or a stale
server-side session can be involved. A restart may complete password authentication
without requesting 2FA, so the absence of a prompt is not diagnostic. Error `366`
immediately afterward is only the failed request's cancellation cleanup. Follow the
session-recovery procedure in `docs/runbook.md`; while diagnosing, add `--retries 0` to
`download-data` to avoid repeating a request IBKR will continue to reject. Changing the
API client ID does not affect this account-level allocation.

The running bot coalesces real-time error `420` bursts and performs a full data-client
reconnect after 60 seconds. If the conflicting mobile or desktop session remains active,
recovery repeats after subsequent rejection; log out of that session to release market
data. Historical CLI downloads still require the manual recovery procedure above.

See IBKR's current [market data pricing](https://www.interactivebrokers.com/en/pricing/research-news-marketdata.php)
and [API market data requirements](https://ibkrcampus.com/docs/general/market-data-subscriptions.md)
before subscribing, because offerings can change.

## Data And Backtest

Resolve the exact IB contracts before downloading data. Never guess exchange or conId
values.

```sh
uv run swing-bot discover-contracts --output data/contracts.json
uv run swing-bot download-data --contracts data/contracts.json --catalog data/catalog \
  --start 2025-01-01T00:00:00-05:00 --end 2026-08-01T00:00:00-05:00 \
  --hourly-chunk-days 30 --minute-chunk-days 30
uv run swing-bot validate-data --catalog data/catalog \
  --start 2025-01-01T00:00:00-05:00 --end 2026-08-01T00:00:00-05:00
uv run swing-bot backtest --contracts data/contracts.json --catalog data/catalog \
  --start 2026-01-01T00:00:00-05:00 --end 2026-08-01T00:00:00-05:00 \
  --output reports/2026
```

The price-acceleration strategy additionally requires native regular-hours five-second bars.
Download only the research interval needed because these requests are large and subject
to IB pacing limits:

```sh
uv run swing-bot download-data --contracts data/contracts.json --catalog data/catalog \
  --start 2026-08-01T09:30:00-04:00 --end 2026-08-01T16:00:00-04:00 \
  --include-second-bars --second-chunk-minutes 30
uv run swing-bot backtest --strategy price-acceleration \
  --contracts data/contracts.json --catalog data/catalog \
  --start 2026-08-01T09:30:00-04:00 --end 2026-08-01T16:00:00-04:00 \
  --output reports/price-acceleration
```

Run the cross-sectional momentum strategy explicitly:

```sh
uv run swing-bot backtest --strategy portfolio-momentum \
  --contracts data/contracts.json --catalog data/catalog \
  --start 2015-01-01T00:00:00-05:00 --end 2025-01-01T00:00:00-05:00 \
  --output reports/portfolio-momentum
```

This mode loads [config/portfolio.toml](config/portfolio.toml) and
[config/sectors.toml](config/sectors.toml), requires 500 calendar days of warmup data,
and uses conservative commission and slippage assumptions. The current catalog does not
contain the broad point-in-time history required by the audit's promotion gates.

The equivalent configurable Make target is:

```sh
make backtest
make backtest BACKTEST_START=2026-01-01T00:00:00-05:00 \
  BACKTEST_END=2026-08-20T20:00:00-04:00 BACKTEST_OUTPUT=reports/2026-final
```

The backtest writes JSON, CSV, and `report.html` artifacts. It sends only minute bars to
the simulated exchange and aggregates them into completed one-hour bars for signals.
Data includes the US pre-market, regular session, and post-market returned by IB. It
automatically loads up to 60 calendar days of earlier minute bars without permitting
warmup-period entries. Keep at least 120 earlier hourly equivalents in the catalog so
both moving averages can initialize.

Downloads are resumable. Each completed hourly or minute request is immediately stored in
`data/catalog.download-cache`; rerunning the same command skips those requests, including
completed intervals with no data. The final `data/catalog` is replaced only after all
requested units pass validation, so an interrupted download does not damage the previous
catalog. Remove `data/catalog.download-cache` to force a complete refresh. Hourly and
minute bars use separate chunk controls. `--chunk-days` remains an alias for
`--minute-chunk-days`. Catalogs created by the earlier daily/RTH strategy must be
downloaded again because they do not contain hourly extended-hours bars.

IB may return code `162` with `HMDS query returned no data` for intervals before a symbol
listed or after it stopped trading. The downloader treats that exact response as an empty
interval and continues immediately. Other code `162` responses, including different-IP
session conflicts, retain their normal failure behavior. A symbol still needs at least
220 hourly bars in the completed catalog to pass warmup validation.

## Paper And Live

Paper is the default and requires an account ID beginning with `DU`:

```sh
make paper
make logs
```

Select portfolio momentum for paper trading with an environment override or set
`TRADING_STRATEGY=portfolio-momentum` in `.env`:

```sh
TRADING_STRATEGY=portfolio-momentum make paper
```

Use `TRADING_STRATEGY=price-acceleration make paper` to select the regular-hours
five-second-bar strategy. Its parameters in
[config/price_acceleration.toml](config/price_acceleration.toml) are research defaults,
not validated evidence of profitability or live execution quality. IB supplies these
bars natively, avoiding the account-level tick-by-tick subscription ceiling.

Before changing acceleration parameters, download complete regular-hours five-second
sessions into an isolated catalog and run `tools/optimize_acceleration.py` with the last
sessions held out for validation. The screen reuses the production signal state machine
and includes adverse slippage and per-share commissions. Promote only parameter regions
that remain positive across multiple chronological development and validation sessions;
do not select a setting from one day's top result.

On startup it reconciles broker orders and positions, obtains USD `NetLiquidation`, and
requests 500 calendar days of hourly history before subscribing to live bars. It will not
rebalance until every configured instrument has reached the weekly synchronization point.
The dashboard pause and flatten controls apply to the selected strategy.

Live operation requires all of the following: the live Compose override, a non-`DU`
account, port `4001`, `TRADING_MODE=live`, and the exact acknowledgement token.

```sh
TWS_ACCOUNT=U0000000 \
LIVE_TRADING_ACK=I_UNDERSTAND_LIVE_ORDERS_ARE_REAL \
TRADING_STRATEGY=portfolio-momentum \
make live
```

Availability is not evidence of promotion readiness. The portfolio strategy still lacks
the broad point-in-time data and decade-plus validation required by the audit gates; use
live mode only after independently accepting those unresolved risks.

Use `make stop` for a graceful stop. It cancels unfilled entry orders, preserves
broker-held trailing stops for open positions, and does not liquidate positions. See the
runbook for shutdown and incident procedures.

To receive Telegram notifications for bot lifecycle events, entries, and closed trades,
set both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`, then recreate the bot
container. Notification delivery is asynchronous and a Telegram outage does not block
trading callbacks.

To find the chat ID:

1. Create a bot with Telegram's `@BotFather` and copy its API token.
2. For a private chat, open the new bot and send it a message. For a group, add the bot
   to the group and send a message or command mentioning it.
3. Export the token locally and request the bot's recent updates:

```sh
export TELEGRAM_BOT_TOKEN='token-from-botfather'
curl --silent "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"
```

Use the `result[].message.chat.id` value as `TELEGRAM_CHAT_ID`. Group chat IDs are
normally negative. If `result` is empty, send the bot another message and retry. Keep the
bot token secret; anyone with it can control the bot.

## Configuration

- [config/universe.toml](config/universe.toml): ticker universe.
- [config/strategy.toml](config/strategy.toml): SMA separation, crossover, and trailing stop.
- [config/risk.toml](config/risk.toml): sizing, exposure limits, and circuit breakers.
- [config/portfolio.toml](config/portfolio.toml): research momentum and allocation rules.
- [config/sectors.toml](config/sectors.toml): research universe sector caps.
- [docs/strategy.md](docs/strategy.md): exact rules and simulation limitations.
- [docs/runbook.md](docs/runbook.md): operator checklist and incident response.

Run local validation with `uv run pytest` and `uv run ruff check .`.

## License

This project is licensed under the [MIT License](LICENSE).