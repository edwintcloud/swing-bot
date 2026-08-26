# Strategy Family Comparisons

The current bot is an hourly single-name trend-continuation entry with a fixed trailing exit. Established strategies are portfolio processes, not isolated indicators. The largest gaps are universe construction, relative ranking, volatility scaling, diversification, cost modeling, and validation depth.

## Summary

| Family | Canonical horizon | Primary edge or role | Main failure mode | Fit with current bot |
| --- | --- | --- | --- | --- |
| Time-series momentum | Months | Persistence in each market's own trend | Whipsaw and crowded reversals | Related directionally, but current horizon and universe differ sharply |
| Cross-sectional momentum | 3-12 month formation, monthly rebalance | Relative continuation among winners and losers | Momentum crashes, turnover, short costs | Strong redesign candidate with a broad universe |
| Mean reversion | Intraday to multi-year | Temporary overreaction or liquidity provision | Structural breaks and trading costs | Useful contrasting sleeve, not what current signal implements |
| Value/quality | Months to years | Cheap assets and profitable firms | Long droughts and stale accounting data | Diversifying ranking inputs, not hourly timing signals |
| Managed futures/risk parity | Portfolio framework | Diversification and balanced risk | Leverage, covariance shifts, financing | Portfolio/risk lessons transfer; instruments do not |
| Buy-and-hold | Years | Market risk premium | Full equity drawdowns | Required investable baseline |

## Time-Series Momentum and Trend Following

Moskowitz, Ooi, and Pedersen test whether each of 58 futures and forwards continues in the direction of its own past excess return. The canonical implementation uses roughly 12-month lookback information, monthly decisions, many markets, and volatility scaling. Hurst, Ooi, and Pedersen reconstruct related rules across a much longer historical period.

Similarity: both systems trade in the direction of an established trend and attempt to let gains run.

Differences:

- The bot uses SMA separation and a one-hour pullback cross, not past 12-month excess return.
- It trades two cataloged stocks rather than diversified futures across asset classes.
- It sizes from a fixed 5% stop rather than equalizing forecast risk.
- Its fixed trailing stop and extended-hours limit behavior dominate realized results.

Trend evidence supports studying continuation, not the current parameters or return claim.

## Cross-Sectional Momentum

Jegadeesh and Titman rank securities by prior relative performance, buy winners, and sell losers. The Kenneth French momentum factor provides a public, documented control formed from size and prior-return portfolios.

This is the closest useful redesign family because the configured universe already spans sectors. A research design could rank a point-in-time liquid universe, require an absolute-trend filter, and allocate only to the strongest names while limiting sector and factor concentration.

Risks include crash exposure after market rebounds, high turnover, short borrow costs, and hidden loading on volatile growth stocks. These require explicit stress periods and cost models.

## Mean Reversion

Short-horizon reversal research finds that recent moves can partially reverse, but bid-ask bounce, liquidity provision, and market impact explain or consume part of the effect. De Bondt and Thaler's long-horizon loser/winner reversal is a different multi-year phenomenon.

The bot is not mean reversion: it enters with the dominant trend after a pullback. Renaming documentation to continuation avoids importing unsupported assumptions from reversal research.

A separate mean-reversion sleeve would need independent signals, tighter liquidity/session controls, and a much more conservative execution model. It should not be blended into the current signal until independently validated.

## Value and Quality

Fama-French value and profitability factors and Novy-Marx's profitability evidence operate at accounting and monthly/annual horizons. They can improve candidate selection or diversify momentum, but cannot validate an hourly crossover.

Use point-in-time fundamentals with publication lags. Current fundamentals applied retrospectively would create look-ahead bias. Value and momentum can diversify each other, but each may underperform for years.

## Managed Futures and Risk Parity

Managed-futures evidence demonstrates the value of many independent markets, volatility targets, and systematic rebalancing. Risk parity allocates risk rather than nominal dollars and often uses leverage to raise a diversified low-volatility portfolio to a target risk.

Transferable lessons:

- Normalize positions by forecast volatility.
- Cap correlated and sector risk.
- Define a portfolio volatility target and delever when estimates rise.
- Separate alpha assumptions from leverage decisions.

Risk parity is not an alpha signal and does not imply high CAGR. Financing costs, covariance instability, and simultaneous stock/bond losses are material.

## Buy-and-Hold Controls

At minimum, compare against total-return SPY and QQQ over identical dates, plus cash or Treasury bills. Use a broad-market total-return series for long samples. Bessembinder's evidence that aggregate stock-market wealth creation is concentrated in a small minority of stocks reinforces why a survivor-selected two-name test is not a neutral benchmark.

Report:

- Unlevered strategy versus each benchmark.
- Strategy and benchmark at matched realized volatility.
- Alpha and beta against market, size, value, profitability, investment, and momentum factors.
- Drawdown, recovery time, turnover, and cost sensitivity.

## Reproducible Data Controls

| Control | Purpose | Required handling |
| --- | --- | --- |
| Kenneth French market and momentum factors | Long-run market/factor context | Preserve vintage, definitions, missing-value rules, and CRSP methodology changes |
| Kenneth French five factors | Value, profitability, investment attribution | Treat as research factors, not directly executable returns |
| AQR paper datasets | Published trend/value/momentum replication | Check redistribution terms and paper-specific scaling |
| SPY/QQQ adjusted total return | Investable same-period baseline | Include dividends, splits, and actual expense ratios |
| One-month Treasury bill | Cash and excess-return baseline | Match frequency and source vintage |

No external series should be merged with intraday IB bars without a documented calendar, timezone, dividend, and sampling transformation.

## Overall Assessment

The current strategy borrows the intuition of trend continuation but omits the breadth and portfolio construction central to battle-tested momentum research. The strongest redesign direction is a diversified, volatility-scaled cross-sectional momentum process with an optional absolute-trend regime filter. Value/quality can inform slow candidate selection; mean reversion should remain a separately tested sleeve; risk-parity ideas should govern allocation rather than signal generation.
