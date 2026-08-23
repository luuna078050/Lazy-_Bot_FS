from __future__ import annotations

# Fast Scalper must boot its HTTP UI first. The market radar opens a Binance
# WebSocket in the background; starting that socket during module import can
# make a cold Render instance appear stuck on "Application Loading". Defer
# only the radar's two import-time background threads. The first
# /api/recommendations request still starts the radar normally.
import threading

_original_thread_start = threading.Thread.start


def _defer_radar_start(self, *args, **kwargs):
    name = getattr(self, "name", "")
    if name in {"fast-scalper-market-radar", "radar-boot-check"}:
        return
    return _original_thread_start(self, *args, **kwargs)


threading.Thread.start = _defer_radar_start
try:
    from .ui_v2 import app
finally:
    threading.Thread.start = _original_thread_start
