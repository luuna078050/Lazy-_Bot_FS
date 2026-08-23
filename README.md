# LazyBot FS

**FS = Fast Scalper.** Unified working baseline for the previously developed fast-scalper features, with Pchelka integration.

## Included
- Binance / CCXT exchange adapter layer
- multi-exchange spot routing with account/region eligibility checks
- async market data interface
- paper/live execution separation
- position sizing and leverage limits
- TP/SL, trailing stop, break-even stop
- fees and daily loss guard
- Telegram notifications adapter
- Pchelka research adapter
- signal/risk/execution separation
- configurable symbols and risk limits
- **dynamic order-book pressure module:** bid/ask imbalance, relative walls, wall persistence and spoof-risk detection

## Order-book intelligence
The order-book module is evidence-based: a large wall is not automatically treated as support/resistance. The analyzer tracks repeated snapshots, detects walls that disappear before price reaches them, and reduces confidence when spoof-risk rises. It is exposed through `/api/orderbook/analyze` and is intended to become a confirmation input for the signal/risk layer.

## Architecture
`Pchelka -> research/evidence -> market + orderbook microstructure -> LazyBot FS -> signal -> risk -> execution`

Pchelka is research-only and never places trades. LazyBot FS remains the specialized fast-scalper brain.

## Important
This package is a consolidated implementation of the previously specified Fast Scalper capabilities. It does not pretend to recover byte-for-byte historical source code that is not present in the current repository. Live trading is disabled by default.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Modes
`TRADING_MODE=paper` is the default. Set `TRADING_MODE=live` only after configuring exchange credentials and validating the strategy.
