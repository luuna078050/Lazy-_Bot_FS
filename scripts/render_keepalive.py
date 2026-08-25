"""Keep Fast Scalper warm on Render Free by making inbound requests."""
from __future__ import annotations

import os
import time
import urllib.request


def run() -> None:
    url = (os.getenv("RENDER_EXTERNAL_URL") or "https://fast-scalper.onrender.com").rstrip("/") + "/health"
    while True:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                response.read(32)
            print(f"[KEEPALIVE] {url} OK", flush=True)
        except Exception as exc:
            print(f"[KEEPALIVE] failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(10 * 60)


if __name__ == "__main__":
    run()
