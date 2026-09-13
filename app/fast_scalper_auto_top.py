from fastapi import HTTPException
from pydantic import BaseModel
from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_core as core

legacy.S['auto_top10'] = True
_original_refresh_slots = core.refresh_slots

def refresh_slots_guarded():
    if not legacy.S.get('auto_top10', True):
        return
    _original_refresh_slots()

core.refresh_slots = refresh_slots_guarded

class AutoTopBody(BaseModel):
    enabled: bool = True

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/auto-top10' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/auto-top10')
async def auto_top10(b: AutoTopBody):
    legacy.S['auto_top10'] = bool(b.enabled)
    if legacy.S['auto_top10']:
        _original_refresh_slots()
    return {'ok': True, 'auto_top10': legacy.S['auto_top10'], 'slots': legacy.S.get('slots', [])}

print('FAST_SCALPER_AUTO_TOP10 enabled=1 manual_override=1', flush=True)
