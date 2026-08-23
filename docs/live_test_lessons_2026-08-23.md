# Live test lessons — 2026-08-23

Observed during the manual TUT/USDC test and now encoded as strategy requirements.

- Quote currency is **agnostic**. Do not hard-code USDC or USDT into strategy logic; the execution adapter handles reconversion and the available quote asset.
- Lazy Bot Scalper execution horizon: **1–3 minutes**.
- Analysis stack: **4h, 2h, 1h, 30m, 15m, 5m, 3m, 1m + live order book + trade flow**.
- Higher timeframes provide regime/context; 1m/3m provide execution timing.
- Track not only direction but **trend smoothness** over 1–3–5 minute windows. A smooth rising/falling path is stronger evidence than a single candle spike.
- MA7/25/99 are dynamic state variables; sudden MA7 curvature/acceleration is a signal change, not noise.
- RSI14 and Stochastic14 are **filters/confirmation**, not standalone entry triggers.
- Order-book walls are dynamic objects. Re-evaluate every snapshot: price migration, disappearance, replenishment, side-switching, persistence and pressure velocity.
- A wall moving with price can be support/resistance migration; a wall disappearing before price reaches it increases spoof risk.
- Entry/exit orders must be repriced when the validated support/resistance zone moves. Cancel/re-place only when the new level is materially better and risk limits remain valid; avoid churn from one-tick noise.
- The bot must never treat a screenshot as a data source. Screenshots are design evidence from the manual test; live bot data must come from streaming market/depth/trade feeds.
- Paper/live execution remain separate; live trading stays locked until validation passes.

## Validation target

Run at least **1,000 simulated trades per strategy profile** on historical data. Report win rate, net PnL after configurable fees/slippage, average win/loss, expectancy, max drawdown, time in trade, turnover, and results by volatility regime. Do not use the 1,000-trade count as a forced live-trading quota.
