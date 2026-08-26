# Claims of Sustained 40-60% CAGR

## Conclusion

The research found no public, reproducible, battle-tested rule set with independently verified 40-60% net CAGR year after year that is comparable to this bot. Renaissance Technologies' Medallion Fund is the relevant exceptional claimant, but it is closed, proprietary, capacity-constrained, highly leveraged, and operationally unlike an hourly two-stock system.

This is not an argument that the reported Medallion record is false. It is an argument that an outcome record and an implementable strategy are different evidence.

## Claim Screen

A candidate must state a multi-year period, compound return basis, gross/net status, fees, leverage, and capital base; have independent or primary corroboration; and expose enough rules and data to assess reproducibility. Claims failing those conditions remain Grade E and are not used as design targets.

| Candidate | Publicly reported claim | Best primary evidence found | Reproducible? | Audit grade |
| --- | --- | --- | --- | --- |
| Renaissance Medallion | Secondary accounts commonly cite returns near or above the requested range, depending on gross/net basis and period | 2014 US Senate PSI record documents extraordinary proprietary trading scale, leverage near 20:1 in examined structures, and over $30 billion of related profits, but not a complete audited annual return series | No | B for existence/scale; E as a strategy specification |
| Public newsletters, vendors, and social-media systems | Frequently advertise selected annual or backtested returns in this range | No qualifying primary, independently verified, complete multi-year records found in this audit | No | E |
| Academic momentum, trend, value, quality, and risk-parity portfolios | Positive long-run premia and, in some studies, attractive Sharpe ratios | Peer-reviewed research and public factor definitions | Often reproducible as research, but the papers do not promise 40-60% annual CAGR | C |

Only Medallion belongs in the high-CAGR outcome comparison. The academic families belong in the mechanism comparison, not this return-claim table.

## Medallion

The US Senate Permanent Subcommittee on Investigations' 2014 hearing and report on basket options provide unusually strong public evidence that Renaissance conducted a large, highly profitable, technology-intensive trading operation. The hearing record describes more than 100,000 trades per day, leverage that reached roughly 20:1 in the structures examined, 60 basket options, and more than $30 billion in associated profits.

Those facts make Medallion less comparable to this repository, not more:

- The trading rules, features, data, infrastructure, and portfolio construction are proprietary.
- The operation traded at vastly greater breadth and frequency.
- Material leverage and prime-broker structures affected capital efficiency.
- Capacity was actively constrained; the fund was not a scalable public product.
- Common figures such as roughly 39% net or more than 60% gross annualized returns come from secondary histories, books, and reporting rather than the accessible Senate return table. They must be attributed as secondary claims, not restated as an audited fact here.
- A fund-level record after unusual fees cannot be translated into a signal rule for two individual stocks.

The appropriate lesson is structural: exceptional returns, where real, tend to depend on diversified signals, proprietary data, execution, leverage, continual research, and constrained capacity. Copying a moving-average shape does not reproduce that system.

## Why the Requested Band Is a Poor Acceptance Test

A return target can be reached in a backtest by increasing leverage, concentration, parameter search, or optimistic execution. None creates an edge. At 40% CAGR capital doubles in about 2.1 years; at 60%, about 1.5 years. Sustaining either rate for a decade would compound one dollar to roughly $29 or $110 respectively, before taxes. That economic scale makes capacity, drawdown, and evidence quality central.

Selecting only systems that happened to land in this band also creates severe selection and survivorship bias. The failed funds, abandoned variants, and unreported accounts are not observed.

## Audit Treatment

- Retain 40-60% as a descriptive band for claimed outcomes.
- Do not optimize parameters toward it.
- Do not annualize this repository's sub-year result and call it CAGR.
- Compare designs at matched volatility and leverage.
- Require live or untouched out-of-sample evidence after realistic costs.
- Prefer drawdown, recovery, and ruin-risk gates over a headline return.

See [References](references.md) for the Senate record, regulatory guidance, and academic controls.
