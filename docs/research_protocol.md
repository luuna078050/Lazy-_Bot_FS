# LazyBot FS — research protocol

## Goal

Use the known three-month crypto history to teach the research layer to build and test causal/conditional chains without leaking future information into the past.

## Timeframes are separate graphs

A 3m candle, 15m candle, 1h candle and 4h candle are not interchangeable observations. Each timeframe has its own OHLCV aggregation and therefore its own trend, momentum, volatility and structure.

The execution timeframe may be 3m/5m/15m while 1h/4h act as context. Context features must be computed only from candles closed before the execution candle being evaluated.

## Cross-timeframe chain

Example research chain:

`4h regime -> 1h structure -> 15m setup -> 5m confirmation -> 3m trigger -> execution`

The chain is a hypothesis. It must be evaluated historically and then on a held-out period.

## Cross-rate analysis

For each candidate asset, the matrix should optionally compare:

- BTC/USDT regime
- ETH/USDT relative strength
- the candidate's return/volatility relative to BTC
- market-wide direction proxies
- funding/open-interest inputs when available

A cross-rate relationship is a feature, not proof of causality. The research report must distinguish correlation, temporal precedence and confirmed causal evidence.

## Three-month protocol

1. Collect the same historical window for all configured symbols.
2. Keep 3m/5m/15m/1h/4h datasets separate.
3. Build causal features using only information available at each timestamp.
4. Split the period chronologically.
5. Fit on the earlier window.
6. Freeze parameters.
7. Evaluate on an unseen later window.
8. Repeat with walk-forward windows.
9. Report hit rate, trade count, expectancy, drawdown, profit factor and false-signal rate.
10. Reject configurations that reach a target only through overfitting, too few trades or leakage.

## 93–95% target

93–95% is a target for a sufficiently large and independently evaluated signal set, not a number the system is allowed to manufacture. If the out-of-sample result is lower, report the real value and continue researching the feature chain.

A 95% result on training data alone is not considered success.

## Data source

Binance publishes historical public market data and supports K-line retrieval at different intervals; public market data can also be downloaded from Binance's data collection. See the Binance market-data documentation for the applicable limits and intervals.
