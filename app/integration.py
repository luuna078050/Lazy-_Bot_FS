from __future__ import annotations

import asyncio
import os

from .tobicore_bridge import signal as tc_signal, best_signal as tc_best

TOBICORE_URL = os.getenv("TOBICORE_URL", "").rstrip("/")


def _enabled() -> bool:
    return bool(TOBICORE_URL)


def _row_features(row: dict) -> tuple[float, float]:
    base = float(row.get("score", 50.0))
    x = (base - 50.0) / 10.0
    return x, x


async def enrich_ranking(main_module, rows: list[dict]) -> list[dict]:
    """Enrich Fast Scalper ranking with TobiCore decisions.

    TobiCore is a second decision layer: the local Fast Scalper score is kept,
    TobiCore contributes 55% to the final score, and the selected TobiCore
    direction becomes the effective signal. If TobiCore is unavailable, the
    local ranking is returned unchanged.
    """
    if not _enabled() or not rows:
        return rows

    async def enrich(row: dict) -> dict:
        try:
            momentum, trend = _row_features(row)
            data = await tc_signal(
                row["symbol"],
                float(row["price"]),
                momentum,
                trend,
                1.0,
                0.0,
            )
            best = tc_best(data)
            if not best:
                return row
            local_score = float(row.get("score", 50.0))
            tc_score = float(best.get("score", 50.0))
            row["score_local"] = round(local_score, 2)
            row["signal_local"] = row.get("signal", "WAIT")
            row["tobicore"] = best
            row["tobicore_signal"] = best.get("direction", "WAIT")
            row["tobicore_score"] = round(tc_score, 2)
            row["score"] = round(local_score * 0.45 + tc_score * 0.55, 2)
            row["signal"] = best.get("direction", row.get("signal", "WAIT"))
        except Exception as exc:
            row["tobicore_error"] = f"{type(exc).__name__}: {exc}"
        return row

    enriched = await asyncio.gather(*(enrich(dict(r)) for r in rows))
    enriched.sort(key=lambda x: (x.get("score", 0), x.get("volume", 0)), reverse=True)
    return enriched


def install(main_module) -> None:
    """Install the integration explicitly at application bootstrap."""
    original_ranking = main_module.ranking
    original_openp = main_module.openp

    async def ranking():
        rows = await original_ranking()
        return await enrich_ranking(main_module, rows)

    async def openp(slot: int, symbol: str):
        row = next(
            (x for x in main_module.S.get("ranking", []) if x.get("symbol") == symbol),
            None,
        )
        tc = row.get("tobicore") if row else None
        if tc and tc.get("direction") != "BUY":
            return
        return await original_openp(slot, symbol)

    main_module.ranking = ranking
    main_module.openp = openp

    original_health = getattr(main_module, "health", None)
    if original_health:
        async def health():
            data = await original_health()
            data["tobicore"] = {
                "enabled": _enabled(),
                "url_configured": bool(TOBICORE_URL),
                "live_trading": False,
            }
            return data
        route = next((r for r in main_module.app.routes if getattr(r, "path", None) == "/api/health"), None)
        if route:
            route.endpoint = health
