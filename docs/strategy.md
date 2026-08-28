# Strategy And Risk Model

## Audit Status

The current implementation remains unchanged. The [strategy audit](audit/README.md)
treats existing backtests as screening evidence, documents their data and execution
limitations, and specifies research gates for a possible capital-preservation redesign.
It does not establish repeatable 40-60% CAGR or authorize promotion to live trading.

## Signal

Signals are evaluated after every completed one-hour bar from 4:00 through 20:00 ET,
including pre-market and post-market. SMA20 is the fast mean and SMA100 provides the
slower context. A long signal requires SMA20 to be at least 5% above SMA100, the prior
close to be at or below SMA20, and the current close to cross above SMA20 without moving
more than 1% above it. A short signal mirrors the rule: SMA20 is at least 5% below
SMA100, the prior close is at or above SMA20, and the current close crosses below SMA20
without moving more than 1% below it. This trades continuation after a pullback while
the narrow entry band prevents chasing an extended move.
Both moving averages include the current completed bar when evaluating the current
threshold. There are no RSI, z-score, candle-body, or ATR conditions.

## Price Acceleration Scalper

The opt-in `price-acceleration` strategy evaluates completed regular-hours five-second
`LAST` bars, which IB supports natively. For close $C_t$ and elapsed seconds $\Delta t$,
velocity is $v_t=(C_t/C_{t-1}-1)/\Delta t$ and acceleration is
$a_t=(v_t-v_{t-1})/\Delta t$. New entries are disabled for the first 15 minutes after
the 09:30 ET open. A long setup arms only after $a_t$ reaches 0.2 basis points per second
squared on two consecutive bars, equivalent to a 5 basis point increase between adjacent
five-second returns; a short setup mirrors the sign. Entry occurs with an IOC market order
after directional acceleration has fallen at least 0.1 basis points from its armed peak
while velocity remains in the trade direction. Setups expire after 10 seconds.

Each fill receives a reduce-only GTC trailing-stop-market order with a 15 basis point
offset. While a position is open, three consecutive bars, approximately 15 seconds, with
absolute acceleration at or below 0.04 basis points trigger an immediate reduce-only IOC market exit. The strategy
cancels the working trail before submitting that exit and waits five seconds after the
position closes before rearming. Missing five-second bars reset signal warmup so overnight or
interrupted data cannot create an acceleration measurement.

These values are configurable in `config/price_acceleration.toml` and are an unvalidated
research baseline. Five-second OHLC backtests do not model spread, queue position,
latency, market impact, stop gaps, or the cancel/exit race with broker precision.

Entry is a GTC limit order at the completed signal bar's close, with IB's `outsideRth`
flag enabled. Each entry fill immediately receives a reduce-only GTC trailing-stop-market
order with a fixed 5% (500 basis point) offset and `outsideRth` enabled. The same 5%
distance is used for risk-based position sizing. There is no profit target, minimum
reward/risk rule, ATR calculation, or maximum holding period. Entry limits can remain
unfilled, especially outside regular hours.

## Risk Controls

Position size is the lesser of risk-at-stop sizing and the per-position notional cap,
rounded down to whole shares. Every proposed bracket is then checked against:

- Maximum open positions.
- Maximum gross portfolio exposure.
- Maximum aggregate short exposure.
- Daily and weekly loss circuit breakers.
- High-water-mark drawdown circuit breaker.
- Nautilus pre-trade order-rate and per-order notional limits.

The shipped profile risks 3.2% of current equity per trade, caps each position at 64%,
and permits up to 128% gross exposure across two positions. This requires a margin
account and can produce rapid losses. The drawdown circuit tracks closed-equity highs;
unrealized peaks inside an open trade do not raise its high-water reference.

Backtests use configured starting equity. Paper and live trading use IBKR's reported USD
`NetLiquidation` balance and reject entries while the broker account or balance is
unavailable. Circuit breakers block new entries; they do not automatically liquidate
existing positions. Missing position marks cause new entries to fail closed.

## Backtest Assumptions

Backtests send only minute bars to the simulated exchange and aggregate their closes into
completed clock-hour signal bars. The deterministic fill model fills an eligible touched
limit without synthetic slippage. Minute OHLC bars still do not reproduce an order book,
queue priority, extended-hours spreads and depth, halts, borrow availability, or real IB
commissions. Corporate actions and delisted securities depend entirely on the source
data. The fixed current universe introduces survivorship bias when tested historically.

Treat results as a screening tool, not evidence of executable future returns. Validate
splits, dividends, timezone/session boundaries, exchange mappings, and shortability
before promoting a symbol or date range.