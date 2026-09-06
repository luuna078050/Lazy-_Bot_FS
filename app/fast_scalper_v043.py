from __future__ import annotations
import time
from .fast_scalper_v042 import app
from . import fast_scalper_v042_base as base

# v0.4.3: keep the exact v0.4.2-repair UI and paper controls from v042,
# but restore the proven base Radar implementation.
async def radar(force=False):
    if not force and base.S['last_radar'] and time.time()-base.S['last_radar'] < base.RADAR_INTERVAL:
        return
    try:
        base.S['ranking'] = await base.build_ranking()
        base.S['last_radar'] = time.time()
        base.S['error'] = None
    except Exception as e:
        base.S['error'] = f'Radar: {type(e).__name__}: {e}'
        base.S['last_radar'] = time.time()

base.radar = radar
