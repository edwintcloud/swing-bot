# Audit Methodology

Audit date: 2026-08-25

This audit evaluates evidence; it does not predict returns or provide personalized investment advice. A reported backtest is evidence about a simulation under stated assumptions, not evidence that the same result was executable or will recur.

## Questions

1. What does the current strategy actually do?
2. How reliable are its reported results?
3. Which established strategy families are genuinely comparable?
4. Which public claims support sustained 40-60% CAGR, and how strong is that evidence?
5. What research design would prioritize preservation of capital?

## Evidence Grades

| Grade | Evidence |
| --- | --- |
| A | Audited or regulatory primary record of live, net returns with a defined period and capital base |
| B | Independently documented live results with material assumptions disclosed |
| C | Peer-reviewed or fully reproducible research using point-in-time data and realistic costs |
| D | Practitioner research or a reproducible backtest with important limitations |
| E | Marketing, interviews, anecdotes, unverifiable summaries, or provenance-incomplete backtests |

A strong return alone does not raise the grade. Missing fee, leverage, survivorship, capacity, or selection information lowers it.

## Metrics

For beginning equity $V_0$, ending equity $V_T$, and elapsed years $T$:

$$
\operatorname{CAGR} = \left(\frac{V_T}{V_0}\right)^{1/T} - 1
$$

CAGR is reported only for periods of at least one year. Applying the formula to a shorter period is labeled an **annualized extrapolation**, never an observed annual return.

For periodic returns $r_t$, periods per year $N$, and periodic risk-free return $r_{f,t}$:

$$
\operatorname{Sharpe} = \sqrt{N}\frac{\operatorname{mean}(r_t-r_{f,t})}{\operatorname{stdev}(r_t-r_{f,t})}
$$

Sortino replaces total volatility with downside deviation. Maximum drawdown is the largest decline from an equity high to a subsequent low. Calmar is CAGR divided by absolute maximum drawdown. These ratios are not comparable unless return frequency, risk-free treatment, valuation frequency, and sample period agree.

The audit also records total return, yearly returns, volatility, turnover, gross and net exposure, leverage, hit rate, profit factor, trade count, holding period, capacity, and time to recover. Results are identified as gross or net of commissions, spread, slippage, borrow costs, financing, and fees.

## Comparison Rules

- Compare executable portfolio returns with executable benchmarks where possible.
- Keep factor returns, hypothetical portfolios, fund returns, and ETF returns in separate columns.
- Use total-return benchmarks with dividends when strategy equity includes all trading PnL.
- Align calendars, currency, sampling frequency, and risk-free assumptions.
- Show unlevered and volatility-matched results separately.
- Do not infer performance for symbols absent from the historical catalog.
- Do not select a strategy on the same observations used to tune it.
- Report all tested variants or apply a multiple-testing correction.

## Reproducibility Record

Every empirical result should preserve:

- Source URL, publisher, access date, release or vintage date, and license constraints.
- Raw-file checksum and immutable local path when redistribution is permitted.
- Universe construction, delisting treatment, corporate actions, and survivorship policy.
- Signal time, execution time, timezone, session, and look-ahead controls.
- Fill, spread, slippage, commission, borrow, financing, and market-impact assumptions.
- Parameters, tested alternatives, random seeds, train/validation/holdout boundaries, and code revision.

## Promotion Standard

The redesign is judged primarily on loss containment and robustness. Promotion requires predeclared out-of-sample gates, not achievement of a target CAGR. A 40-60% CAGR is retained only as a claimed-outcome comparison band.

## Limitations

The repository currently contains less than two years of data for two securities. It cannot independently test long-run persistence, broad-universe cross-sectional strategies, delisting effects, or performance across several market cycles. Any redesign remains a research specification until suitable point-in-time data and live paper evidence exist.
