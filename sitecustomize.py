try:
    import app.main as _fast_scalper_main
    from app import balance_overlay as _balance_overlay
    _balance_overlay.install(_fast_scalper_main)

    import asyncio, math, time
    from collections import deque
    from app.tobicore_bridge import signal as _tc_signal, best_signal as _tc_best

    # Requested configuration corrections/additions only.
    _fast_scalper_main.START_ACCOUNT = 1000.0
    _fast_scalper_main.START_BOT = 600.0
    _fast_scalper_main.TRADING_TF = "1m"
    _fast_scalper_main.ROTATE = 60
    _fast_scalper_main.S["account"] = 1000.0
    _fast_scalper_main.S["bot"] = 600.0
    _fast_scalper_main.S["free"] = 600.0

    # Use Binance's dedicated market-data endpoint for the radar.
    _fast_scalper_main.BINANCE = "https://data-api.binance.vision"

    # Keep Fast Scalper well below Binance's request-weight ceiling.
    _binance_budget = 300
    _binance_used = deque()
    _binance_lock = asyncio.Lock()

    def _binance_weight(path):
        if path.startswith("/api/v3/klines"):
            return 2
        if path.startswith("/api/v3/ticker/24hr"):
            # No-symbol 24hr ticker is a heavy request.
            return 80
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
        await _wait_binance_budget(_binance_weight(path))
        return await _original_get(path, p)

    _fast_scalper_main.get = _get_limited

    _original_ranking = _fast_scalper_main.ranking
    _original_openp = _fast_scalper_main.openp

    async def _ranking_with_extra_pair_analysis():
        rows = await _original_ranking()
        if not rows:
            return rows

        prices = [max(float(r.get("price", 0.0)), 1e-12) for r in rows]
        pmin, pmax = min(prices), max(prices)
        changes = [float(r.get("change", 0.0)) for r in rows]
        cmax = max([abs(x) for x in changes] + [1.0])
        vmax = max([float(r.get("volume", 0.0)) for r in rows] + [1.0])

        for r in rows:
            price = max(float(r.get("price", 0.0)), 1e-12)
            change = float(r.get("change", 0.0))
            base = float(r.get("score", 50.0))
            momentum = abs(float(r.get("momentum", 0.0)))
            price_pos = (math.log(pmax) - math.log(price)) / max(math.log(pmax) - math.log(pmin), 1e-12)
            hot = min(100.0, 50.0 + (change / cmax) * 50.0)
            liquidity = min(100.0, 100.0 * math.log1p(max(float(r.get("volume", 0.0)), 0.0)) / math.log1p(vmax))
            movement = min(100.0, 50.0 + min(momentum * 20.0, 50.0))
            extra = (
                base * 0.50
                + movement * 0.20
                + hot * 0.15
                + liquidity * 0.10
                + price_pos * 100.0 * 0.05
            )
            r["score"] = round(max(0.0, min(100.0, extra)), 2)
            r["price_factor"] = round(price_pos * 100.0, 2)
            r["hot_score"] = round(hot, 2)
            r["movement_score"] = round(movement, 2)
            r["liquidity_score"] = round(liquidity, 2)

        rows.sort(key=lambda x: (x["score"], x.get("volume", 0)), reverse=True)
        return rows[:15]

    async def _ranking_with_tobicore():
        rows = await _ranking_with_extra_pair_analysis()

        async def enrich(row):
            tc = await _tc_signal(
                row["symbol"], row["price"],
                float(row.get("score", 50.0) - 50.0) / 10.0,
                float(row.get("score", 50.0) - 50.0) / 10.0,
                1.0, 0.0,
            )
            best = _tc_best(tc)
            if best:
                row["tobicore"] = best
                tc_score = float(best.get("score", 50.0))
                row["score_local"] = row.get("score", 50.0)
                row["score"] = round(row["score"] * 0.45 + tc_score * 0.55, 2)
                row["signal_local"] = row.get("signal")
                row["signal"] = best.get("direction", row["signal"])
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

    # Radar refresh: 70 seconds, reducing Binance request pressure.
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
