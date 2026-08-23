# LazyBot FS

**FS = Fast Scalper.** Unified working baseline for fast-scalper features, with Pchelka integration.

## Fast Scalper 3m — ready Binance profile

The current test/live profile is `scripts/fast_scalper_3m.py`.

It is designed for the user's manual workflow:

- **2 or 3 USDT spot pairs** selected by the user;
- allocation entered as percentages and required to total **100%**;
- example: **DGB 30% / ZRO 30% / TUT 40%** on 100 USDT;
- fixed strategy timeframe: **3m**;
- maximum trade budget: **180 seconds**;
- realtime Rocket Hunter pulse: **1 second**;
- profit is an **absolute USDT amount**, not a percentage;
- default minimum acceptable profit: **0.20 USDT net**;
- default target: **0.30 USDT net**;
- at 90 seconds the minimum can close the trade to recycle capital;
- at 180 seconds a non-losing position is exited by the 3m time rule;
- optional SL remains a separate checkbox.

The browser UI is available at `/fast-scalper`. It shows capital, 2–3 pairs, percentage allocation, the resulting USDT amount per pair, fixed 3m timeframe, profit controls, the bot's suggested profit range, and the SL switch.

The bot's profit metric is now **USDT per minute**, not maximum profit from one position. This directly targets the observed manual problem where a good DGB trade produced about 0.77 USDT but took 6:43 because a human missed several seconds and the position stayed open too long.

### Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.fast_scalper.example .env
python -m scripts.fast_scalper_3m
```

The default is **PAPER** while using live Binance public trade data. To enable real Binance Spot execution, configure the Binance API key/secret and explicitly set:

```text
FAST_SCALPER_LIVE=true
LIVE_TRADING=true
LIVE_TRADING_ARMED=true
```

The live runner still requires the existing execution guards in `ExchangeGateway`. It uses the Binance Spot market-order interface only; no futures and no leverage.

For live trading, use a dedicated/sub-account with only the permissions required for Spot trading, **no withdrawals**, and IP restrictions where possible. Binance's current guidance recommends least-privilege permissions and disabling withdrawals for trading bots. urlBinance API security guidancehttps://academy.binance.com/en/articles/what-is-an-api-key-and-how-to-use-it-securely

Binance's Spot WebSocket market streams are used for the one-second micro layer, while REST/CCXT remains available for account and execution operations. Binance documents the Spot WebSocket API and notes that WebSocket API connections are time-limited, so the client reconnects when needed. citeturn0news25turn0news26

## Included
- Binance / CCXT spot exchange adapter
- multi-pair radar and capital-slot allocation
- separate exchange account balance vs user-assigned **bot account balance**
- paper/live execution separation
- money/time profit targeting
- absolute USDT profit targeting for Fast Scalper 3m
- TP/SL with a **user-controlled SL switch** and daily loss guard
- dynamic order-book pressure
- regime-aware MTF intelligence: 4h/2h/1h/30m/15m/5m/3m/1m + micro-flow
- MA7/25/99, RSI14, Stochastic14, trend smoothness and impulse/pullback/retest/breakout structure
- **Rocket Hunter** for early acceleration / ignition detection rather than late pump chasing
- one-second Binance public trade pulse for short 2–3 second bursts

## Rocket Hunter

Rocket Hunter searches for the **launch**, not a rocket that is already on orbit. It prioritizes early acceleration, relative volume expansion, price acceleration, buyer imbalance, liquidity quality and higher-timeframe confirmation, while penalizing exhaustion and late-entry conditions.

A candidate can be classified as `EARLY_ROCKET`, `IGNITION`, `RELOAD`, `ORBIT`, or `WAIT`. A 2–3 second burst can therefore trigger a realtime candidate without waiting for a 3-minute candle to close.

## Capital policy
The **bot account balance** is the capital assigned to this bot, not the whole exchange account. Fast Scalper 3m lets the user explicitly distribute 100% of that bot balance across 2–3 configured pairs.

Example:

- 100 USDT total;
- DGB 30% = 30 USDT;
- ZRO 30% = 30 USDT;
- TUT 40% = 40 USDT.

The bot never automatically changes these allocation percentages. It can choose whether to enter a configured pair, but the capital ceiling for that pair is the user-defined allocation.

## Profit policy

Fast Scalper 3m does **not** use the earlier `0.25 per 1 unit of capital` model. That scaling was too aggressive for small accounts.

The current model is:

**small fixed USDT profit + short holding time + high capital turnover.**

Default:

- minimum: **0.20 USDT net**;
- target: **0.30 USDT net**;
- 90 seconds: minimum-profit exit is allowed;
- 180 seconds: time exit for a non-losing position.

The UI can propose a target based on allocated capital and estimated round-trip fees. The user can override it. No profit target guarantees a fill or a profit in live trading.

## Exit policy / SL checkbox

**☑ Ограничение убытка (SL)**
- configured stop is enforced;
- money target remains active.

**☐ Ограничение убытка (SL)**
- no fixed loss-based stop is applied;
- an underwater position can wait for recovery/strategy confirmation.

## Security

Live trading is disabled by default. Never commit API secrets. Use a Binance key restricted to the minimum required Spot permissions, disable withdrawals, and use IP restrictions where possible. Binance explicitly recommends least-privilege permissions and no withdrawal access for trading bots. citeturn0search6turn0search8

## API service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open `/fast-scalper` for the Fast Scalper configuration screen.
