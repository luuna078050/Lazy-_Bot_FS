try:
    import app.main as _fast_scalper_main
    from app import balance_overlay as _balance_overlay
    _balance_overlay.install(_fast_scalper_main)

    import asyncio
    from app.tobicore_bridge import signal as _tc_signal, best_signal as _tc_best
    _original_ranking = _fast_scalper_main.ranking
    _original_openp = _fast_scalper_main.openp

    async def _ranking_with_tobicore():
        rows = await _original_ranking()

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
except Exception:
    pass
