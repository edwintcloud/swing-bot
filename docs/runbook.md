# Operator Runbook

## Preflight

1. Confirm the machine clock is synchronized and Docker is healthy.
2. Confirm `.env` names the intended mode, account, port, and distinct client IDs.
3. Confirm `data/contracts.json` matches the configured universe and was freshly resolved.
4. Run `make test` after code or configuration changes.
5. Start IB Gateway and approve 2FA. Wait for `docker compose ps` to report healthy.
6. Run `uv run swing-bot connectivity` before discovery, download, paper, or live work.
7. Confirm startup logs show the expected IBKR account and USD net liquidation balance.
8. Open `http://localhost`, verify the dashboard reports `Running`, and reconcile its
	equity and positions with IBKR before using either control.

## IBKR Session Allocation

Historical error `162` stating that a trading TWS session is connected from a different
IP is an IBKR server-side trading or market-data session conflict, not a bad contract or
date range. It can occur even when no other TWS or Gateway process is visible. Paper data
may share the live account's entitlement, and IBKR Mobile, Client Portal, hosted
integrations, VPN changes, or a stale server-side allocation can affect the public IP
IBKR associates with it. Error `366` may follow because the rejected historical request
is no longer active.

1. Stop the download with `Ctrl+C`.
2. Disable VPN or proxy changes and keep the live and paper sessions on the same public
	IP when sharing market-data subscriptions.
3. Log the username out of TWS, Gateway, IBKR Desktop, Client Portal, and IBKR Mobile
	trading on other devices. Also stop any hosted integration using the username.
4. Wait briefly for IBKR to release the allocation, then run
	`docker compose restart ib-gateway`. Approve 2FA only if requested; IBKR can complete
	a full password login without presenting an SLS challenge.
5. Wait for `docker compose ps` to report healthy, run
	`uv run swing-bot connectivity`, and retry the download.

If Gateway logs show an existing-session dialog and taking over that session is
acceptable, temporarily set `EXISTING_SESSION_DETECTED_ACTION: primaryoverride` in
`docker-compose.yml`, recreate the Gateway with
`docker compose up -d --force-recreate ib-gateway`, and retry once. This can terminate a
session IBKR currently considers primary. Restore `primary` afterward. If no takeover
dialog appears, `primaryoverride` has nothing to act on; do not keep restarting. Contact
IBKR support and ask them to clear or identify the username's trading/market-data session
allocation. Include the exact error, timestamp, username type (live or paper), and both
public IPs if known.

Use `--retries 0` while diagnosing so a permanent session rejection is not repeated. If
two trading sessions must stay connected, create and use a distinct IBKR username and
assign the required market-data permissions to it in Client Portal. Changing the API
client ID does not resolve a different-IP trading-session conflict.

## Backtest Review

Run `validate-data` before every backtest. Inspect `manifest.json` for coverage and row
counts, then review `summary.json`, `report.html`, orders, fills, and positions together.
Reject a run with missing warmup, duplicate timestamps, implausible OHLC values, missing
symbols, unexpected venues, or timestamps outside IB's 4:00-20:00 ET stock session.

Use out-of-sample periods and sensitivity checks around SMA separation, crossover,
trailing-stop, limit-fill, and slippage assumptions. Review pre-market, regular-session,
and post-market results separately. Do not select parameters solely from the reported
period.

## Paper Promotion

Run paper mode through at least several complete signal and exit cycles. At each session:

1. Verify account and market-data subscriptions in logs.
2. Reconcile strategy open orders and positions against IB.
3. Confirm no duplicate entry brackets exist.
4. Confirm each entry fill has a reduce-only 5% trailing stop.
5. Review rejected orders, stale bars, disconnects, and circuit-breaker messages.

For `price-acceleration`, also verify that data arrives as completed regular-hours
`5-SECOND-LAST` bars, every fill receives a 15 basis point reduce-only trailing stop,
and a three-bar flatline cancels that stop before submitting one reduce-only IOC market
exit. Reconcile both orders directly in IB because the stop cancellation and immediate
exit can cross in flight. Test restart and shutdown with an open paper position before
considering any live use.

Promote to live only after observed paper fills and operational behavior are acceptable.
Use the smallest practical live capital and size initially.

## Normal Shutdown

Run `make stop` and wait for shutdown. The strategy cancels unfilled entry orders but
leaves broker-held trailing stops working for open positions. It does not flatten
positions, because forced market liquidation during an outage can be worse than retaining
the protective broker orders. Verify all orders and positions manually in IB before
stopping the Gateway:

```sh
docker compose down
```

## Incident Response

For duplicate orders, stale data, an exception loop, or unexplained exposure, stop the
bot immediately. Use IB Gateway or another authenticated IB client to cancel orders and
manage positions. Do not restart until broker state is reconciled and the cause is known.

The dashboard pause control prevents new strategy entries but leaves working exits and
positions unchanged. Flatten is an asynchronous emergency action available for all positions
or one position at a time: it pauses entries, cancels strategy orders, and submits reduce-only
GTC limit exits at a 1% collar around the latest hourly mark (or average entry while warmup is
pending). Confirm fills and remaining broker orders directly in IBKR; the position may remain
open if the market is outside the limit or trading is halted.

After a disconnect, inspect `logs/`, verify Gateway health and 2FA status, then run the
connectivity command. Startup requests all open orders for reconciliation, but the
operator must still compare the broker account before allowing new entries.

If a loss or drawdown circuit breaker fires, leave the bot stopped for review. Do not
restart merely to reset in-memory circuit references. Record the event, broker statements,
orders, fills, logs, data timestamps, and the exact configuration used.

## Live Gate

Live mode is intentionally inconvenient. It rejects `DU` accounts and requires:

```text
TRADING_MODE=live
IB_PORT=4001
LIVE_TRADING_ACK=I_UNDERSTAND_LIVE_ORDERS_ARE_REAL
```

The IB API socket is unencrypted and unauthenticated. Both Compose files bind it only to
`127.0.0.1`; do not remove that binding on an untrusted host or network.