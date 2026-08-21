# LazyBot FS

**FS = Fast Scalper.** Unified working baseline for the previously developed fast-scalper features, with Pchelka/Bee-derived research integration and a separate Income strategy.

## Architecture

`Bee/Pchelka search segments -> NCAM normalization/ranking -> Lazy strategy -> risk -> execution`

Research layers are read-only. They never place, modify, or close trades.

## Lazy Bot Scalper

- 24/7 observation; trades only when the strategy conditions are satisfied
- execution timeframes: **1m / 3m / 5m**
- context: **10m / 15m / 30m / 1h / 4h**
- scans multiple pairs rather than one fixed symbol
- builds a Top-10 candidate list and selects up to 3-5 active pairs
- safety + profitability + liquidity + volatility + correlation scoring
- capital modes: approximately 10% / 20% / 30%, constrained by portfolio risk
- dynamic exits and peak/retracement logic; holding time is not fixed by timeframe
- optional re-entry after a confirmed retracement; never mandatory
- 100% profit reinvestment in the planned growth model
- starting model: $200 plus $100 monthly funding from Income for one year

## Lazy Bot Income

Separate strategy optimized for withdrawable cash flow rather than compounding:

- reference working capital: **$1,000**
- weekly review cycle
- primary analysis: **3m / 5m / 10m / 15m**
- target scenario: **$700-$800/month**; this is not a guaranteed return
- profit is withdrawn; working capital is not intended to compound
- can allocate up to **$100/month** to Scalper when realized profit permits
- no forced trading to meet a calendar target

## NCAM

`app/integrations/ncam.py` is the normalization boundary for the Bee/Pchelka-derived search layer. Existing useful search modules can feed it without copying the entire Pchelka platform into LazyBot. NCAM remains research-only.

## Safety

Live trading is disabled by default. Paper testing comes first. Leverage, position size, daily loss limits, fees, slippage, and execution quality must be validated before any live deployment.
