try:
    import app.main as _fast_scalper_main
    from app import balance_overlay as _balance_overlay
    _balance_overlay.install(_fast_scalper_main)

    import asyncio, json, math, time
    from collections import deque
    from app.tobicore_bridge import signal as _tc_signal, best_signal as _tc_best

    # Requested configuration corrections/additions only.
    # Account is the dynamic total capital; Bot is the dynamic amount allocated to strategy.
    _fast_scalper_main.START_ACCOUNT = 1850.0
    _fast_scalper_main.START_BOT = 0.0
    _fast_scalper_main.TRADING_TF = "1m"
    _fast_scalper_main.ROTATE = 60
    _fast_scalper_main.S["account"] = 1850.0
    _fast_scalper_main.S["bot"] = 0.0
    _fast_scalper_main.S["free"] = 0.0

    # Keep Binance market data on the dedicated public market-data endpoint.
    _fast_scalper_main.BINANCE = "https://data-api.binance.vision"

    # Radar request budget. Base radar: 1 batch ticker + 100 klines.
    # Hot-pair enrichment adds 20 depth + 20 aggTrades requests.
    _binance_budget = 300
    _binance_used = deque()
    _binance_lock = asyncio.Lock()
    _binance_block_until = 0.0

    def _binance_weight(path, p=None):
        if path.startswith("/api/v3/klines"):
            return 2
        if path.startswith("/api/v3/ticker/24hr"):
            return 1
        if path.startswith("/api/v3/depth"):
            return 1
        if path.startswith("/api/v3/aggTrades"):
            return 1
        return 2

    async def _wait_binance_budget(weight):
        while True:
            async with _binance_lock:
                now = time.monotonic()
                while _binance_used and now - _binance_used[0][0] >= 60:
                    _binance_used.popleft()
                used = sum(w for _, w in _binance_used)
                if used + weight <= _binance_budget:
                    _binance_used.append((now, weight))
                    return
                wait_for = max(0.05, 60 - (now - _binance_used[0][0]))
            await asyncio.sleep(wait_for)

    _original_get = _fast_scalper_main.get

    async def _get_limited(path, p=None):
        global _binance_block_until

        # Never send the old all-symbol /ticker/24hr request. Keep the exact
        # universe used by Fast Scalper and request it as one 20-symbol batch.
        if path == "/api/v3/ticker/24hr" and not p:
            p = {
                "symbols": json.dumps(
                    list(_fast_scalper_main.UNIVERSE),
                    separators=(",", ":"),
                ),
                "type": "MINI",
            }

        now = time.monotonic()
        if now < _binance_block_until:
            return []

        await _wait_binance_budget(_binance_weight(path, p))
        try:
            return await _original_get(path, p)
        except Exception as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status in (418, 429):
                retry_after = 60.0
                try:
                    retry_after = float(response.headers.get("Retry-After", retry_after))
                except Exception:
                    pass
                _binance_block_until = time.monotonic() + max(1.0, retry_after)
                return []
            raise

    _fast_scalper_main.get = _get_limited

    _original_ranking = _fast_scalper_main.ranking
    _original_openp = _fast_scalper_main.openp

    async def _market_hot_metrics(symbol):
        async def depth_call():
            return await _fast_scalper_main.get("/api/v3/depth", {"symbol": symbol, "limit": 20})

        async def trades_call():
            return await _fast_scalper_main.get("/api/v3/aggTrades", {"symbol": symbol, "limit": 1000})

        depth, trades = await asyncio.gather(depth_call(), trades_call(), return_exceptions=True)
        if not isinstance(depth, dict):
            depth = {}
        if not isinstance(trades, list):
            trades = []

        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        bid_notional = sum(float(x[0]) * float(x[1]) for x in bids if len(x) >= 2)
        ask_notional = sum(float(x[0]) * float(x[1]) for x in asks if len(x) >= 2)
        total_book = bid_notional + ask_notional
        book_imbalance = (bid_notional - ask_notional) / total_book if total_book else 0.0
        orderbook_score = max(0.0, min(100.0, 50.0 + 50.0 * book_imbalance))

        spread_bps = 99.0
        if bids and asks:
            bid = float(bids[0][0]); ask = float(asks[0][0]); mid = (bid + ask) / 2.0
            if mid > 0:
                spread_bps = (ask - bid) / mid * 10000.0
        spread_score = max(0.0, min(100.0, 100.0 - max(0.0, spread_bps - 2.0) * 6.0))
        liquidity_score = max(0.0, min(100.0, 50.0 + min(math.log1p(total_book) * 5.0, 50.0))) if total_book else 0.0

        flow_score = 50.0
        volume_spike = 50.0
        acceleration_score = 50.0
        recent_return = 0.0
        if len(trades) >= 20:
            mid_idx = len(trades) // 2
            old = trades[:mid_idx]
            recent = trades[mid_idx:]

            def bucket(xs):
                quote = 0.0; buy_quote = 0.0
                for x in xs:
                    p = float(x.get("p", 0.0)); q = float(x.get("q", 0.0)); v = p * q
                    quote += v
                    # Binance aggTrades: m=true means buyer is market maker,
                    # therefore m=false is an aggressive buy.
                    if not bool(x.get("m", False)):
                        buy_quote += v
                t0 = int(xs[0].get("T", 0)); t1 = int(xs[-1].get("T", 0))
                seconds = max(1.0, (t1 - t0) / 1000.0)
                return quote, buy_quote, quote / seconds

            oq, ob, orate = bucket(old)
            rq, rb, rrate = bucket(recent)
            if rq > 0:
                flow_score = max(0.0, min(100.0, 100.0 * rb / rq))
            if orate > 0:
                ratio = rrate / orate
                volume_spike = max(0.0, min(100.0, 50.0 + 35.0 * math.log(max(ratio, 0.2), 2)))
                volume_spike = max(0.0, min(100.0, volume_spike))

            old_first = float(old[0].get("p", 0.0)); old_last = float(old[-1].get("p", 0.0))
            rec_first = float(recent[0].get("p", 0.0)); rec_last = float(recent[-1].get("p", 0.0))
            old_ret = (old_last / old_first - 1.0) if old_first else 0.0
            rec_ret = (rec_last / rec_first - 1.0) if rec_first else 0.0
            old_t = max(1.0, (int(old[-1].get("T", 0)) - int(old[0].get("T", 0))) / 1000.0)
            rec_t = max(1.0, (int(recent[-1].get("T", 0)) - int(recent[0].get("T", 0))) / 1000.0)
            old_rate = old_ret / old_t
            rec_rate = rec_ret / rec_t
            accel = rec_rate - old_rate
            acceleration_score = max(0.0, min(100.0, 50.0 + accel * 100000.0))
            recent_return = rec_ret * 100.0

        return {
            "orderbook_score": orderbook_score,
            "flow_score": flow_score,
            "volume_spike": volume_spike,
            "acceleration_score": acceleration_score,
            "spread_score": spread_score,
            "liquidity_score": liquidity_score,
            "spread_bps": round(spread_bps, 4),
            "recent_return": round(recent_return, 4),
        }

    async def _ranking_with_extra_pair_analysis():
        rows = await _original_ranking()
        if not rows:
            return rows

        prices = [max(float(r.get("price", 0.0)), 1e-12) for r in rows]
        pmin, pmax = min(prices), max(prices)
        changes = [float(r.get("change", 0.0)) for r in rows]
        cmax = max([abs(x) for x in changes] + [1.0])
        vmax = max([float(r.get("volume", 0.0)) for r in rows] + [1.0])

        async def enrich(r):
            price = max(float(r.get("price", 0.0)), 1e-12)
            change = float(r.get("change", 0.0))
            base = float(r.get("score", 50.0))
            momentum = abs(float(r.get("momentum", 0.0)))
            price_pos = (math.log(pmax) - math.log(price)) / max(math.log(pmax) - math.log(pmin), 1e-12)
            hot = min(100.0, 50.0 + (change / cmax) * 50.0)
            liquidity = min(100.0, 100.0 * math.log1p(max(float(r.get("volume", 0.0)), 0.0)) / math.log1p(vmax))
            movement = min(100.0, 50.0 + min(momentum * 20.0, 50.0))
            market = await _market_hot_metrics(r["symbol"])

            # Hot-pair score: market movement + acceleration + volume burst +
            # aggressive buy flow + order-book pressure + execution quality.
            hot_score = (
                base * 0.20
                + movement * 0.10
                + hot * 0.05
                + market["acceleration_score"] * 0.15
                + market["volume_spike"] * 0.15
                + market["flow_score"] * 0.15
                + market["orderbook_score"] * 0.10
                + market["spread_score"] * 0.05
                + liquidity * 0.05
            )

            # Do not chase a late pump: strong recent return with weakening
            # buy pressure/order-book support is penalized instead of promoted.
            late_pump = 0.0
            if market["recent_return"] > 0.35 and market["flow_score"] < 55.0 and market["orderbook_score"] < 50.0:
                late_pump = min(25.0, market["recent_return"] * 20.0)
            hot_score = max(0.0, min(100.0, hot_score - late_pump))

            r["score_local"] = round(base, 2)
            r["hot_score"] = round(hot_score, 2)
            r["price_factor"] = round(price_pos * 100.0, 2)
            r["movement_score"] = round(movement, 2)
            r["liquidity_score"] = round(liquidity, 2)
            r["acceleration_score"] = round(market["acceleration_score"], 2)
            r["volume_spike_score"] = round(market["volume_spike"], 2)
            r["buy_flow_score"] = round(market["flow_score"], 2)
            r["orderbook_score"] = round(market["orderbook_score"], 2)
            r["spread_score"] = round(market["spread_score"], 2)
            r["spread_bps"] = market["spread_bps"]
            r["late_pump_penalty"] = round(late_pump, 2)
            return r

        rows = await asyncio.gather(*(enrich(r) for r in rows), return_exceptions=True)
        rows = [x for x in rows if isinstance(x, dict)]
        rows.sort(key=lambda x: (x["hot_score"], x.get("volume", 0)), reverse=True)
        return rows[:15]

    async def _ranking_with_tobicore():
        rows = await _ranking_with_extra_pair_analysis()

        async def enrich(row):
            tc = await _tc_signal(
                row["symbol"], row["price"],
                float(row.get("hot_score", row.get("score", 50.0)) - 50.0) / 10.0,
                float(row.get("hot_score", row.get("score", 50.0)) - 50.0) / 10.0,
                1.0, 0.0,
            )
            best = _tc_best(tc)
            if best:
                row["tobicore"] = best
                tc_score = float(best.get("score", 50.0))
                row["tobicore_score"] = round(tc_score, 2)
                # Hot market data remains the dominant ranking input; TobiCore
                # is retained as context instead of suppressing hot pairs.
                row["score"] = round(float(row.get("hot_score", row.get("score", 50.0))) * 0.75 + tc_score * 0.25, 2)
                row["signal_local"] = row.get("signal")
                row["signal"] = best.get("direction", row["signal"])
            else:
                row["score"] = row.get("hot_score", row.get("score", 50.0))
            return row

        enriched = await asyncio.gather(*(enrich(r) for r in rows))
        enriched.sort(key=lambda x: (x["score"], x.get("volume", 0)), reverse=True)
        return enriched

    async def _openp_with_tobicore(i, symbol):
        row = next((x for x in _fast_scalper_main.S.get("ranking", []) if x.get("symbol") == symbol), None)
        tc = row.get("tobicore") if row else None
        if tc and tc.get("direction") == "SELL":
            return
        return await _original_openp(i, symbol)

    _fast_scalper_main.ranking = _ranking_with_tobicore
    _fast_scalper_main.openp = _openp_with_tobicore

    # Radar refresh: exactly 70 seconds minimum between passes.
    _original_radar = _fast_scalper_main.radar
    async def _radar_70s(force=False):
        if not force and time.time() - _fast_scalper_main.S["last_radar"] < 70:
            return
        return await _original_radar(force)
    _fast_scalper_main.radar = _radar_70s

    _fast_scalper_main.HTML = _fast_scalper_main.HTML.replace(
        "Trading TF: 3m", "Trading TF: 1m"
    ).replace(
        "value=\"0\"", "value=\"0\""
    )
except Exception:
    pass
