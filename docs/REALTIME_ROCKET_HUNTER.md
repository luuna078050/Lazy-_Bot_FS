# Realtime Rocket Hunter

LazyBot FS now has two market-analysis layers:

1. **Strategic layer** — the normal multi-timeframe 3m/1m scanner and order-book analysis.
2. **Realtime micro layer** — Binance public websocket `aggTrade` data aggregated into one-second buckets.

The realtime layer is designed for very short 1–3 second bursts that can be missed by a 20-second REST scan.

## One-second pulse

For each tracked USDT spot pair the pulse keeps:
- 1s, 2s and 3s price acceleration;
- one-second quote volume;
- volume ratio versus recent one-second buckets;
- aggressive buyer ratio;
- trade count.

A candidate becomes `EARLY_ROCKET` or `IGNITION` only when the burst is strong enough. Ordinary noise remains `WAIT`; sharp negative acceleration is `FADE`.

## Execution safety

The pulse does not bypass LazyBot risk controls. Micro-entry requires:
- explicit `PULSE_EXECUTION_ENABLED`;
- automatic allocation to be enabled and past its validation period;
- available position slot and capital;
- daily loss guard;
- normal live-trading arming for real orders.

Default installation remains paper mode. The realtime profile is `.env.realtime.example`.

Run:
```bash
pip install -r requirements-realtime.txt
cp .env.realtime.example .env
python -m scripts.realtime_scalper_20
```

The micro layer checks snapshots about once per second while the strategic scan runs separately (20s by default). This separation prevents a slow REST scan from blocking the short-burst reaction loop.

## Important behavior

The bot does **not** promise to catch every 2–3 second pump. Network latency, websocket delivery, exchange matching latency, spread, liquidity and slippage can make a theoretical signal untradeable. The purpose of the module is to reduce the blind spot created by slow polling, not to guarantee profit.
