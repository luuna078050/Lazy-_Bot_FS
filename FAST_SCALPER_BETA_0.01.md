# Fast Scalper Beta — 0.01 REPAIR PAPER

Release baseline: commit 5b61e3eea4aabd026de57921f3278584366b1937.

## Fixed / preserved
- AUTO TOP-6 is a one-shot slot fill.
- SET PAIRS can replace or clear slots after AUTO TOP-6.
- RESET clears slots and session controls after STOP.
- Radar remains recommendations only and does not force slots.
- Live DELTA, dynamic balance allocation, Reinvest, timers, Closed Trades and duplicate protection remain part of the beta baseline.
- Binance integration has PAPER and BINANCE_TEST modes; LIVE is intentionally locked in this beta.

## Binance TEST
Server variables: BINANCE_TESTNET=1, BINANCE_LIVE_ENABLED=0.
API credentials are supplied only as Render environment secrets and are never stored in source code.

## Canonical branch
fast-scalper-beta-0.01-repair-paper

## App entrypoint
app.fast_scalper_beta_001:app
