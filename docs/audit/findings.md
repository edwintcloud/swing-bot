# Audit Findings

## Overall Verdict

The bot implements a comprehensible trend-continuation hypothesis, but the available evidence does not establish a durable edge or sustained 40-60% CAGR. The strongest backtest should be treated as a hypothesis-generating result. It is not suitable evidence for increasing capital or promoting the current risk profile.

## Critical Findings

### C1. The return claim is unsupported by the available period

**Observed:** The strongest run reports 101.56% total return from January through August 2026 on $100,000. The catalog contains data from December 2024 through August 2026.

**Inference:** A high sub-year return can be annualized mathematically, but the result would be an extrapolation through unobserved market regimes. It is not observed CAGR and says nothing about year-after-year persistence.

**Required evidence:** Multiple full market cycles, yearly return distribution, untouched holdout periods, and live paper execution.

### C2. Universe and selection bias dominate the result

**Observed:** Only NBIS and INTC have catalog bars. The optimizer explicitly searches parameters on those names, while 24 current contracts are resolved.

**Inference:** The report may reflect favorable symbol, event, period, and parameter selection rather than a transferable strategy effect. Current survivors cannot represent a point-in-time historical universe.

**Required evidence:** A broad point-in-time universe including delistings, corporate actions, changing liquidity, and frozen historical membership.

### C3. Execution assumptions are materially optimistic

**Observed:** Every eligible touched limit is fillable, synthetic slippage is zero, position reports show zero commissions, and minute OHLC bars stand in for order books during extended hours.

**Inference:** The simulation is likely to overstate fill quality and stop execution, particularly at the shipped position sizes. Direction and magnitude require measurement rather than an arbitrary haircut.

**Required evidence:** Spread-aware fills, queue or probabilistic limit fills, stop gap/slippage, commissions, borrow and financing, market impact, and stress cases.

## High Findings

### H1. Shipped risk is inconsistent with capital preservation

Risking 3.2% per trade with 64% name caps and 128% gross exposure permits two concentrated, potentially correlated positions. A nominal 5% stop does not guarantee a 3.2% maximum loss. Gaps and halts can exceed it, while weekly and drawdown gates only block future entries.

### H2. Portfolio construction is largely absent

Signals are evaluated independently. There is no ranking, sector budget, beta target, correlation cap, portfolio volatility target, or rule for simultaneous candidates. First arrival can determine capital allocation.

### H3. Multiple testing is not incorporated into reported confidence

The optimizer searches a parameter grid and prints top candidates. The repository does not preserve all trial outcomes in the report, calculate a deflated Sharpe ratio, or reserve a long untouched holdout. The favorable candidate is therefore selected evidence.

### H4. Fixed percentage exits ignore changing volatility

A 5% trail can be tight for a volatile stock and extremely wide for a stable one. It changes the effective holding period, turnover, and risk across names and regimes while sizing assumes the same distance defines risk.

### H5. Short execution lacks borrow modeling

The strategy can submit short entries, but the backtest does not establish locate availability, borrow fees, recalls, or hard-to-borrow rejection. Short results are therefore less executable than long results.

## Medium Findings

### M1. Stale GTC entry limits can outlive the signal

An entry order remains open while later market information may invalidate the hourly setup. There is no maximum age or cancellation when trend state changes.

### M2. Extended-hours behavior increases microstructure risk

Signals and orders include pre-market and post-market. These sessions often have wider spreads and less depth, exactly where minute OHLC fill assumptions are weakest.

### M3. Circuit references are memory-resident

Daily, weekly, and high-water references are initialized and updated in process. Operational guidance warns against restarting after a breaker, but persistence and restart semantics are not a durable risk boundary.

### M4. Naming obscures the hypothesis

`SwingReversalStrategy` describes reversal while the signal trades continuation. This does not alter returns, but it increases the chance of applying the wrong research literature or operational interpretation.

## Positive Controls

- Entry sizing and portfolio gates fail closed on missing marks or equity.
- Broker equity is used in live and paper modes.
- Entry fills receive reduce-only broker-held trailing stops.
- Open positions and orders are reconciled through the trading framework.
- Live mode requires an explicit account and acknowledgement gate.
- The runbook already recognizes survivorship, slippage, extended-hours, and paper-promotion limitations.

These controls reduce operational risk but do not validate forecast edge.

## Claim Verdicts

| Claim | Verdict |
| --- | --- |
| The code implements trend continuation after a pullback | Supported by code |
| The current backtest made about 101.6% on $100,000 | Supported as a simulated total return |
| The strategy has demonstrated 40-60% CAGR | Unsupported |
| The strategy can repeat its 2026 result | Unknown and untested |
| The strategy is comparable to Medallion | Unsupported |
| Momentum/trend literature supports further research | Supported at a broad mechanism level |
| Current sizing prioritizes preservation of capital | Contradicted by configuration |

## Immediate Recommendation

Do not infer deployable expected return from the current reports and do not increase live capital based on them. Preserve the implementation for baseline comparison, but require the research and promotion gates in [Redesign](redesign.md) before considering replacement behavior.
