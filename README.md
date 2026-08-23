# LazyBot FS

**FS = Fast Scalper.** Unified working baseline for the fast-scalper features, with Pchelka integration.

## Included
- Binance / CCXT spot exchange adapter
- multi-pair radar and capital-slot allocation
- paper/live execution separation
- position sizing and leverage limits
- TP/SL and daily loss guard
- Telegram notifications adapter
- Pchelka research adapter
- signal/risk/execution separation
- **dynamic order-book pressure:** imbalance, relative walls, wall persistence and spoof-risk detection
- regime-aware MTF intelligence: 4h/2h/1h/30m/15m/5m/3m/1m + optional micro-flow
- MA7/25/99, RSI14, Stochastic14, trend smoothness and impulse/pullback/retest/breakout structure

## Live 20 USDT test
The ready runner is `scripts/live_scalper_20.py`.

It is **paper by default**. The real-test profile is `.env.real20.example` and is intentionally not armed. The runner scans a liquid spot universe, builds a top-10 radar, and can use up to five fixed slots: **10%, 10%, 20%, 20%, 30%** of the 20 USDT test capital, leaving 10% reserve. No leverage and no withdrawals.

Install:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.real20.example .env
```

Put the Binance API key/secret into `.env`. The API key should have **spot trading only** and withdrawals disabled.

First run in paper mode:
```bash
python -m scripts.live_scalper_20
```

Only after the paper run is verified, explicitly arm the real test in `.env`:
```text
TRADING_MODE=live
LIVE_TRADING=true
LIVE_TRADING_ARMED=true
```
Then run the same command. Stop with Ctrl+C.

State is kept in `scalper_state.json` so a normal restart does not intentionally forget locally tracked positions.

## Order-book intelligence
The order-book module is evidence-based: a large wall is not automatically treated as support/resistance. It tracks repeated snapshots, detects walls that disappear before price reaches them, and reduces confidence when spoof-risk rises.

## Architecture
`Pchelka -> research/evidence -> market + orderbook microstructure -> LazyBot FS -> signal -> risk -> execution`

Pchelka is research-only and never places trades. LazyBot FS remains the specialized fast-scalper brain.

## Important
Live trading is disabled by default. The bot is spot-only in the 20 USDT runner. A temporary negative PnL does not by itself trigger a sell; TP/SL or confirmed bearish reversal is required.

## API service
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
