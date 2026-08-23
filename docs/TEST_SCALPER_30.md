# LazyBot FS — Test Scalper 30 USDT

## Purpose

Isolated test of Fast Scalper + Rocket Hunter using a virtual 30 USDT balance and live public Binance trade data. Existing manual holdings are not touched.

## Runtime

```bash
cp .env.test30.example .env
python scripts/test_scalper_30.py
```

Install realtime dependencies first:

```bash
pip install -r requirements-realtime.txt
```

## Behaviour

- public Binance websocket data;
- one-second pulse evaluation;
- 2–3 second burst detection;
- Rocket Hunter `EARLY_ROCKET` / `IGNITION` entries;
- 10% / 20% / 30% capital allocation by signal quality;
- maximum 3 simultaneous positions;
- target profit: 0.25 per 1 unit of allocated capital;
- acceptable floor after 90 seconds: 0.20 per unit;
- maximum normal holding time: 180 seconds;
- optional SL checkbox represented by `TEST_STOP_LOSS_ENABLED` and disabled by default;
- no real orders, no deposits, no withdrawals;
- state is persisted to `test_scalper_30_state.json`.

The 90-second interval is a turnover target, not a forced trade timer. The bot must wait when the signal is weak.

## Important

This test intentionally does not use the existing TUT position or any other manual holdings. The 30 USDT is an isolated simulated bot balance. Live trading remains separately armed and locked.
