# LazyBot FS

**FS = Fast Scalper.** Unified working baseline for fast-scalper features, with Pchelka integration.

## Included
- Binance / CCXT spot exchange adapter
- multi-pair radar and capital-slot allocation
- separate exchange account balance vs user-assigned **bot account balance**
- bot balance can be configured by fixed amount or percentage of account balance
- paper/live execution separation
- position sizing and leverage limits
- money/time profit targeting plus optional percentage TP mode
- TP/SL with a **user-controlled SL switch** and daily loss guard
- Telegram notifications adapter
- Pchelka research adapter
- signal/risk/execution separation
- dynamic order-book pressure: imbalance, relative walls, wall persistence and spoof-risk detection
- regime-aware MTF intelligence: 4h/2h/1h/30m/15m/5m/3m/1m + optional micro-flow
- MA7/25/99, RSI14, Stochastic14, trend smoothness and impulse/pullback/retest/breakout structure
- **Rocket Hunter** for early acceleration / ignition detection rather than late pump chasing

## Money + time profit mode

The main scalper profile no longer has to think in percentages. It can work from two plain-language targets:

1. **Profit per one unit of allocated capital** — e.g. `0.25` means the bot aims for 0.25 units of net profit for each 1 unit allocated to the trade.
2. **Target interval between completed trades** — e.g. `90` seconds means the bot tries to recycle completed trades around every 1.5 minutes.

There is also a lower profit floor. With the default profile:

- target: **0.25 per 1 unit**;
- floor: **0.20 per 1 unit**;
- target interval: **90 seconds**;
- maximum hold budget for a still-valid non-losing position: **180 seconds**.

If the full money target is reached early, the bot closes. At 90 seconds it may accept the lower floor to increase turnover. At 180 seconds it may recycle a non-losing still-valid position. An underwater position is not forced closed by this time policy; the separate SL switch controls loss-based protection.

The interval is a **throughput target, not a promise**. The bot must not create weak entries just to hit the clock. It increases the chance of higher turnover through multi-pair scanning/ranking and multiple controlled positions.

`ESTIMATED_ROUND_TRIP_FEE_PCT` can be supplied so the money target is evaluated against estimated net profit rather than gross price movement.

The legacy percentage TP remains available when `PROFIT_TARGET_MODE=percent`. The default is `money_time`.

## Exit policy / SL checkbox

The scalper keeps the profit target independent from **Stop Loss**.

**☑ Ограничение убытка (SL)**
- the configured stop-loss level is enforced;
- a position can be closed at the SL level;
- the money/time profit target remains active.

**☐ Ограничение убытка (SL)**
- no fixed loss-based stop is applied;
- an underwater position is allowed to wait for recovery / a valid strategy exit;
- a bearish reversal by itself does not close an underwater position;
- profitable confirmed reversal exits remain allowed.

The setting is exposed through `/api/settings/risk` and `/api/settings/risk/stop-loss`, persisted in `scalper_settings.json`, and has a visible browser control at `/settings/risk`. The default remains **enabled** so the existing protective behavior is preserved until the user deliberately switches it off.

## Rocket Hunter

Rocket Hunter searches for the **launch**, not a rocket that is already on orbit. It prioritizes early acceleration, relative volume expansion, price acceleration, buyer imbalance, liquidity quality and higher-timeframe confirmation, while penalizing exhaustion and late-entry conditions.

A candidate can be classified as `EARLY_ROCKET`, `IGNITION`, `WATCH`, or `IGNORE`. The module is part of LazyBot FS; it is not a separate bot.

## Capital policy
The **bot account balance** is the capital the user assigns to this bot. It is not the whole exchange account balance. The user may allocate it by fixed amount or percentage of the account balance.

The user may manually assign up to **100% of the bot account balance** to one position if they explicitly choose to do so.

The separate **automatic allocation policy** is more conservative: while automatic allocation is enabled, the bot itself may use **at most 40% of bot account balance for one position**. This 40% limit does NOT restrict a user's manual allocation choice.

Automatic dynamic allocation is initially frozen during the validation period. After validation, it may size positions from signal quality, subject to the 40% automatic cap.

## Commercial policy
Commercial mode is locked until the validated strategy effectiveness reaches at least **75%**. Profit share is **0.1% (0.001)** of positive realized **net** profit only. No profit share is charged on losing trades.

## Live 20 USDT test
The ready runner is `scripts/live_scalper_20.py`.

It is **paper by default**. The real-test profile is `.env.real20.example` and is intentionally not armed. No leverage and no withdrawals.

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
`Pchelka -> research/evidence -> market + orderbook microstructure -> Rocket Hunter / LazyBot FS -> signal -> risk -> money/time target -> execution`

Pchelka is research-only and never places trades. LazyBot FS remains the specialized fast-scalper brain.

## Important
Live trading is disabled by default. The bot is spot-only in the 20 USDT runner. A temporary negative PnL does not by itself trigger a sell when SL is disabled; the exit policy then waits for recovery/strategy confirmation. With SL enabled, the configured stop is active.

## API service
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
