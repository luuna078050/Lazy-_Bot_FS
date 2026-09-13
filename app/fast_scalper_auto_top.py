from fastapi import HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_core as core
from . import fast_scalper_approved_ui as approved_ui

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

# Patch only the AUTO TOP-10 switch behavior; keep the approved UI markup unchanged.
_PATCHED_HTML = approved_ui.HTML.replace(
    "function toggleAuto(){msg($('autoTop').checked?'AUTO TOP-10 enabled':'Manual TOP-10 enabled');refresh()}",
    "async function toggleAuto(){try{const enabled=$('autoTop').checked;await api('/api/auto-top10',{method:'POST',body:JSON.stringify({enabled})});msg(enabled?'AUTO TOP-10 enabled':'Manual TOP-10 enabled');await refresh()}catch(e){msg(e.message)}}"
)
for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/' and 'GET' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.get('/', response_class=HTMLResponse)
async def patched_approved_home():
    response = HTMLResponse(_PATCHED_HTML)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

print('FAST_SCALPER_AUTO_TOP10 enabled=1 manual_override=1 UI_SWITCH=1', flush=True)
