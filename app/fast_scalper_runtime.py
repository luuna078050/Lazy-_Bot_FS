from fastapi.responses import HTMLResponse
from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_user_fix as consolidated

ROTATION_POOL = consolidated.ROTATION_POOL
TRADE_SLOTS = consolidated.TRADE_SLOTS
DEFAULT_PROFIT = consolidated.DEFAULT_PROFIT

# One user-facing runtime layer only. Prevent stale browser HTML from masking deployed changes.
for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/' and 'GET' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.get('/', response_class=HTMLResponse)
async def approved_home():
    response = HTMLResponse(legacy.HTML)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

legacy.S['profit'] = DEFAULT_PROFIT
legacy.S['reinvest'] = True
print('FAST_SCALPER_SINGLE_RUNTIME APPROVED_UI=1 ROTATION_POOL=20 TRADE_SLOTS=10 TP=0.33 NO_CACHE=1', flush=True)
