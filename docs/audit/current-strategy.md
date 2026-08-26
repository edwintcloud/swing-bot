# Current Strategy and Evidence

## Implemented Rules

The class name says `SwingReversalStrategy`, but the signal is trend continuation after a pullback.

- Signals use completed one-hour bars, including extended hours.
- SMA20 must be at least 5% above SMA100 for a long, or 5% below it for a short.
- Price must cross SMA20 in the trend direction and finish within a 1% entry band.
- A GTC limit is submitted at the signal bar close.
- A fill creates a reduce-only GTC trailing-stop-market order with a fixed 5% offset.
- There is no profit target, time stop, volatility normalization, liquidity filter, ranking across names, or portfolio correlation constraint.

Primary implementation: [`signals.py`](../../src/swing_bot/signals.py), [`strategy.py`](../../src/swing_bot/strategy.py), and [`strategy.toml`](../../config/strategy.toml).

## Shipped Risk Profile

[`risk.toml`](../../config/risk.toml) sets:

| Control | Value |
| --- | ---: |
| Risk budget per trade | 3.2% of equity |
| Maximum position notional | 64% of equity |
| Maximum open positions | 2 |
| Maximum gross exposure | 128% of equity |
| Maximum short exposure | 128% of equity |
| Daily loss gate | 1.5% |
| Weekly loss gate | 3.0% |
| Drawdown gate | 8.0% |

Position size is the lesser of stop-risk sizing and the notional cap. The loss gates block new entries but do not liquidate existing positions. High-water equity advances only while no strategy position is open, so unrealized peaks are intentionally excluded. See [`risk.py`](../../src/swing_bot/risk.py).

This is aggressive concentration, not a capital-preservation profile. Two simultaneous positions may consume margin and expose most capital to correlated equity gaps. A trailing stop does not cap losses during gaps, halts, or unavailable liquidity.

## Backtest Model

[`backtest.py`](../../src/swing_bot/backtest.py) aggregates minute bars into hourly signals and executes against minute OHLC bars. Its configured fill model uses:

- `prob_fill_on_limit = 1.0`
- `prob_slippage = 0.0`
- bar-based execution rather than order-book depth or queue priority
- a maker/taker fee model, while the reviewed position report records `0.00 USD` commissions

The simulation does not reproduce extended-hours spread/depth, borrow availability, market impact, halts, or stop slippage. These omissions are especially material for large positions in volatile single stocks.

## Available Data

The catalog [`manifest.json`](../../data/catalog/manifest.json) is internally recorded as Interactive Brokers data with checksum `273814ec18c5603a185fba04ec79b94649fa53d093e65e06876d6f601252fcb7`.

| Property | Observed value |
| --- | --- |
| Catalog request range | 2025-01-01 through 2026-08-20 |
| Earliest recorded bars | 2024-12-16 UTC |
| Instruments with bars | NBIS and INTC |
| Minute rows | 402,360 NBIS; 402,477 INTC |
| Hourly rows | 6,708 each |
| Resolved current contracts | 24 |

The 22 other resolved contracts have no bars in this catalog. The available data therefore cannot validate the configured broad universe or eliminate survivor and selection bias.

## Report Inventory

The following values come directly from each [`summary.json`](../../reports/2026-final/summary.json). Directory names are not sufficient parameter provenance, so the runs remain only partially comparable.

| Run | Period end | Total PnL | Total return | Win rate | Sharpe | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `minute-baseline` | 2026-07-31 | -$7,976.03 | -7.98% | 24.59% | -2.45 | 0.39 |
| `continuation-10pct` | 2026-07-31 | $13,452.95 | 13.45% | 56.82% | 2.88 | 4.00 |
| `target-candidate` | 2026-07-31 | $98,196.49 | 98.20% | 60.00% | 2.75 | 4.30 |
| `2026-final` | 2026-08-20 | $101,561.12 | 101.56% | 53.85% | 2.51 | 3.55 |

The strongest run begins trading in January 2026 and ends in August 2026, roughly 9.6 calendar months. Doubling in that interval is a large simulated total return, but it is not an observed CAGR and does not establish repeatability from year to year.

The corresponding [`run-1-positions.csv`](../../reports/2026-final/run-1-positions.csv) shows only NBIS and INTC, zero recorded commissions, and position notionals commonly around 60% or more of starting equity. Several concentrated winners contribute a large share of profit. This makes the result sensitive to symbol selection, event timing, sizing, and idealized fills.

## Optimization and Selection Risk

[`optimize_strategy.py`](../../tools/optimize_strategy.py) searches combinations of fast/slow periods, separation, crossover band, and trailing stop on NBIS and INTC during 2026. It uses a May 2026 split but scores and prints the best candidates from the same finite grid. The final report then extends only a few months beyond that split.

This is useful exploratory work, but it is not an untouched long-horizon holdout. The number of tried configurations, tiny universe, short validation period, and retained winner all increase selection bias.

## Evidence Verdict

The implementation is coherent enough to simulate and operate, and it has explicit entry gates, broker-side stops, exposure checks, and operational controls. Its return evidence is nevertheless **Grade E** under the audit rubric because run provenance is incomplete and the best result is short, concentrated, optimized, cost-light, and execution-optimistic.

No current artifact supports the claim that this strategy can achieve 40-60% CAGR year after year.
