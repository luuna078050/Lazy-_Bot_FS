from .main import app
from .market_context import context_snapshot
@app.get('/api/context')
def market_context(): return context_snapshot()
