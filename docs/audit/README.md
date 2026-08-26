# Strategy Audit

Audit date: 2026-08-25

## Executive Summary

The current bot is an hourly trend-continuation system applied to two cataloged stocks. Its strongest report turns $100,000 into $201,561.12 during January-August 2026, but that is a simulated sub-year total return, not demonstrated CAGR. The result uses a selected two-name universe, optimized parameters, perfect touched-limit eligibility, no synthetic slippage, and zero recorded position commissions while allowing concentrated exposure.

No evidence in this repository establishes 40-60% CAGR year after year. Public research supports continued study of momentum, trend, value, quality, reversal, and diversified risk allocation, but those are portfolio premia and frameworks rather than generic high-CAGR engines. Medallion is an exceptional proprietary outcome record, not a reproducible public strategy.

The present live and paper implementation remains unchanged. The recommended research successor is a broad point-in-time cross-sectional momentum portfolio with volatility-scaled sizing, diversification constraints, realistic execution costs, optional slow trend gates, and predeclared capital-preservation promotion criteria.

## Priority Risks

1. Less than two years of historical data and only two securities with bars.
2. Parameter and symbol selection on the same short era used for evaluation.
3. Optimistic limit, stop, spread, commission, borrow, and extended-hours assumptions.
4. Shipped limits of 3.2% risk per trade, 64% per name, and 128% gross exposure.
5. No cross-sectional ranking, volatility target, sector budget, or correlation control.

## Reading Order

1. [Methodology](methodology.md): evidence grades, metric definitions, and comparison rules.
2. [Current Strategy](current-strategy.md): exact implementation, risk configuration, data coverage, and report inventory.
3. [High-CAGR Claims](high-cagr-claims.md): what the requested return band does and does not establish.
4. [Strategy Comparisons](strategy-comparisons.md): trend, momentum, mean reversion, value/quality, managed futures/risk parity, and benchmarks.
5. [Findings](findings.md): severity-ranked audit conclusions.
6. [Redesign](redesign.md): capital-preservation research specification and promotion gates.
7. [References](references.md): government, regulatory, academic, and dataset sources.

## Decision Status

- **Current strategy:** retain only as a baseline; no evidence-based capital increase.
- **40-60% CAGR target:** comparison band, not optimization objective or promise.
- **Redesign:** recommendations only; not implemented.
- **Next dependency:** acquire a long, broad, point-in-time dataset with delistings, corporate actions, liquidity, and realistic execution inputs.

This audit is research documentation, not investment advice or a forecast.
