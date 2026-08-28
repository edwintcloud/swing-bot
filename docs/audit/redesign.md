# Capital-Preservation Redesign Specification

Status: implemented as an opt-in strategy for backtest, paper, and live modes. The existing
SMA strategy remains the default.

## Implemented Research Slice

The `portfolio-momentum` mode implements the first conservative slice of this
specification: long-only cross-sectional momentum with a 252-session lookback and
21-session skip, a 200-session absolute trend filter, 63-session volatility estimate,
20-session median dollar-volume filter, inverse-volatility weighting, weekly rebalance,
and explicit name, sector, gross, and position-count caps. Its configuration lives in
`config/portfolio.toml` and `config/sectors.toml`.

The strategy builds daily observations only from completed regular-session hourly bars
and does not commit a day's close until the next session begins. Backtests apply one tick
of adverse slippage to every fill and a $0.005 per-share commission.

This remains an unpromoted strategy despite being executable in paper and live modes. It
does not yet provide
the broad point-in-time universe, delisting/corporate-action history, factor attribution,
walk-forward protocol, nonlinear impact model, or decade-plus holdout evidence required
below. Paper/live operation adds historical warmup, broker-equity sizing, order and
position reconciliation, and dashboard pause/flatten controls; it does not satisfy the
research promotion gates.

## Objective

Build a diversified research strategy whose first objective is survival across regimes. Maximize neither backtest CAGR nor the chance of crossing the 40-60% comparison band. Prefer stable, cost-aware returns with bounded drawdown and explainable sources.

## Proposed Architecture

### 1. Point-in-Time Universe

Use a broad US equity universe reconstructed as known on each historical date. Require minimum price, median dollar volume, trading history, and borrow eligibility. Preserve delisted names and corporate actions. Exclude a security only using information available at the decision time.

A practical first research tier is liquid large- and mid-cap equities. Keep NBIS and INTC as ordinary members, not privileged symbols.

### 2. Slow Candidate Ranking

Rank monthly or weekly using:

- Cross-sectional momentum over several intermediate horizons, skipping the most recent short window where appropriate.
- Optional value and quality inputs built from lagged point-in-time fundamentals.
- Liquidity and volatility penalties.

Test single factors before combinations. Combining factors is justified only if it improves untouched out-of-sample drawdown or stability, not merely in-sample return.

### 3. Absolute Trend and Regime Filter

Use a slow absolute-trend filter to reduce exposure when a candidate or broad market is below its long-term trend. Treat this as a risk gate, not an assurance against loss. Compare no filter, market-only filter, and name-plus-market filter as predeclared variants.

The existing hourly pullback may be tested as an execution-timing overlay only after the slower portfolio signal succeeds without it. This isolates whether hourly complexity adds value after costs.

### 4. Volatility-Normalized Allocation

Estimate volatility from lagged returns with floors, caps, and robust handling of jumps. Size each position toward equal forecast risk, then enforce:

- Per-name risk and notional caps.
- Sector and industry risk caps.
- Gross, net, beta, and short-exposure caps.
- Correlation or cluster budgets.
- Portfolio volatility target with automatic deleveraging.
- Cash as the default when no allocation passes gates.

Begin research unlevered. Add leverage only as a separate experiment after financing and stress losses are modeled.

### 5. Exit and Rebalance Rules

Use scheduled portfolio rebalancing plus risk exits. Compare volatility-aware ATR or return-volatility stops with no individual stop under strict portfolio risk control. Predeclare stop variants and model gap execution.

Cancel entry limits when the originating signal expires, the next rebalance occurs, or the trend/rank gate fails. Do not leave an indefinitely valid signal encoded as a GTC order.

### 6. Execution Model

Use regular-session execution as the conservative baseline. Model:

- Half-spread plus nonlinear market impact based on participation.
- Actual commissions and regulatory fees.
- Probabilistic or queue-aware limit fills.
- Stop gaps and adverse selection.
- Borrow availability, borrow fees, and recalls.
- Financing on debit balances and proceeds.
- Delays, rejects, halts, and partial fills.

Stress all costs at 1x, 2x, and 4x baseline. A strategy that fails at 2x ordinary cost has little margin of safety.

## Initial Risk Envelope

These are conservative research priors, not final production values:

| Control | Initial research range |
| --- | --- |
| Risk contribution per name | 0.10-0.35% of equity |
| Maximum name notional | 5-10% |
| Maximum sector notional | 20-25% |
| Gross exposure | 50-100% initially |
| Short exposure | 0-30%, only with borrow model |
| Portfolio volatility target | 6-10% annualized |
| Daily new-risk halt | 1% equity loss |
| Drawdown deleveraging | Begin near 5%; staged rather than binary |
| Hard research rejection | Drawdown or gap stress beyond predeclared capital limit |

Ranges must be frozen before the final holdout. Lower risk is preferred when statistical uncertainty is high.

## Research Protocol

1. Freeze data, universe rules, metrics, costs, and candidate variants.
2. Use expanding or rolling walk-forward training and validation blocks spanning bull, bear, high-volatility, low-volatility, inflation, and rate-shock regimes.
3. Keep the final multi-year period untouched until all choices are frozen.
4. Preserve every trial, including failures.
5. Report median and worst-fold performance, not only aggregate performance.
6. Bootstrap paths or trades with dependence-aware methods and show confidence intervals.
7. Calculate multiple-testing-aware statistics such as the deflated Sharpe ratio.
8. Attribute returns to market beta, standard factors, sectors, long/short books, and a small number of extreme trades.
9. Repeat with delayed signals, perturbed parameters, missing data, and stressed costs.
10. Compare against cash, SPY, QQQ, equal-weight universe, and factor controls over identical dates.

## Promotion Gates

Exact thresholds must be approved before examining the final holdout. A candidate should satisfy at least:

- Ten or more years covering several regimes, preferably longer.
- A broad point-in-time universe and enough independent positions/trades for inference.
- Positive net results in most walk-forward folds and in the untouched holdout.
- No dependence on one name, year, sector, direction, or small set of trades.
- Maximum drawdown and recovery time within the capital-preservation mandate.
- Positive performance after 2x estimated ordinary costs and survivable 4x stress.
- Stable behavior across nearby parameter values.
- Acceptable multiple-testing-adjusted evidence.
- Paper execution that reconciles signals, orders, fills, costs, borrow, positions, and broker equity through complete cycles.

A candidate that misses a gate is rejected or returned to research. The gate is not moved after seeing the result.

## Live Rollout Gate

After paper validation, begin with the smallest practical allocation and no leverage. Define automatic exposure reductions for realized volatility, drawdown, stale data, reconciliation failures, and execution divergence. Persist circuit state outside process memory. Require independent broker reconciliation before restoring risk.

## Alternatives

- **Mean reversion:** research separately with highly liquid instruments and explicit spread/impact modeling. Do not mix it into momentum until both sleeves independently pass.
- **Value/quality:** use as slower ranking or diversification inputs, with publication lags.
- **Managed futures:** a better route to cross-asset trend diversification, but it requires futures data, roll rules, margin, and a different operational mandate.
- **Buy-and-hold:** remains the benchmark and may be the preferred allocation when the active design does not improve risk-adjusted outcomes after costs.

## Decision

Retain the current bot as a frozen baseline. The recommended successor is a broad, point-in-time, cross-sectional momentum portfolio with volatility-scaled allocation and an optional slow absolute-trend risk gate. Do not implement it in live or paper code until the required data and predeclared research protocol exist.
