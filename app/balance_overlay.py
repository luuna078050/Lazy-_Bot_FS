from __future__ import annotations
import hashlib, hmac, time
from urllib.parse import urlencode
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

BINANCE = "https://api.binance.com"
KEYS = {"api_key": "", "secret_key": ""}
REAL = {"usdt": None, "updated": 0.0, "error": None}

class WithdrawRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)

async def _real_usdt():
    if not KEYS["api_key"] or not KEYS["secret_key"]:
        return None
    now_ms = int(time.time() * 1000)
    params = {"timestamp": now_ms, "recvWindow": 5000}
    query = urlencode(params)
    sig = hmac.new(KEYS["secret_key"].encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    headers = {"X-MBX-APIKEY": KEYS["api_key"]}
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(BINANCE + "/api/v3/account", params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    for b in data.get("balances", []):
        if b.get("asset") == "USDT":
            return float(b.get("free", 0))
    return 0.0

async def _cached_real_usdt():
    if not KEYS["api_key"] or not KEYS["secret_key"]:
        return None
    if time.time() - REAL["updated"] < 15 and REAL["usdt"] is not None:
        return REAL["usdt"]
    try:
        REAL["usdt"] = await _real_usdt()
        REAL["updated"] = time.time()
        REAL["error"] = None
    except Exception as e:
        REAL["error"] = f"Account: {type(e).__name__}: {e}"
    return REAL["usdt"]

def _route(app, path):
    for r in app.routes:
        if getattr(r, "path", None) == path and getattr(r, "methods", None):
            return r
    return None

def install(m):
    app = m.app
    original_state = _route(app, "/api/state").endpoint

    async def state():
        d = await original_state()
        real = await _cached_real_usdt()
        if real is not None:
            d["account"] = real
            d["account_source"] = "BINANCE"
        else:
            d["account_source"] = "PAPER"
        d["real_account"] = real
        d["strategy_balance"] = float(m.S.get("bot", 0.0))
        d["strategy_profit"] = max(0.0, float(m.S.get("bot", 0.0)) - float(m.START_BOT))
        d["withdraw_available"] = max(0.0, min(float(m.S.get("free", 0.0)), float(m.S.get("bot", 0.0)) - float(m.START_BOT)))
        d["account_error"] = REAL["error"]
        return d

    async def keys(b):
        KEYS["api_key"] = b.api_key.strip()
        KEYS["secret_key"] = b.secret_key.strip()
        REAL.update({"usdt": None, "updated": 0.0, "error": None})
        configured = bool(KEYS["api_key"] and KEYS["secret_key"])
        if configured:
            await _cached_real_usdt()
        return {"ok": True, "configured": configured, "account_source": "BINANCE" if configured and REAL["usdt"] is not None else "PAPER"}

    async def withdraw(b: WithdrawRequest):
        # Strategy-to-account transfer in the PAPER accounting model.
        # This endpoint never sends a withdrawal request to Binance.
        async with m.L:
            bot = float(m.S.get("bot", 0.0))
            free = float(m.S.get("free", 0.0))
            available = max(0.0, min(free, bot - float(m.START_BOT)))
            amount = float(b.amount)
            if amount > available + 1e-9:
                raise HTTPException(400, f"Maximum available for withdraw: {available:.4f} USDT")
            m.S["bot"] = bot - amount
            m.S["free"] = free - amount
            m.S["account"] = float(m.S.get("account", m.START_ACCOUNT)) + amount
        return await state()

    r = _route(app, "/api/state")
    if r:
        r.endpoint = state
    r = _route(app, "/api/keys")
    if r:
        r.endpoint = keys
    app.add_api_route("/api/strategy/withdraw", withdraw, methods=["POST"])

    marker = "</body></html>"
    if marker not in m.HTML:
        return
    injected = r'''<script>
(function(){
  function ensureWithdraw(){
    if(document.getElementById('strategyBox')) return;
    const host=document.getElementById('free')?.closest('.stat');
    if(!host) return;
    host.id='strategyBox';
    host.innerHTML='<div class="m">Free Balance / Bot Balance</div><div class="v" id="free">100.0000 / 100.0000 USDT</div><div class="m" style="margin-top:5px">Strategy Profit: <span id="strategyProfit">0.0000</span> USDT</div><div style="display:flex;gap:6px;margin-top:7px"><input class="input" id="withdrawAmount" type="number" min="0" step="0.0001" placeholder="Withdraw USDT"><button class="btn" onclick="withdrawStrategy()">WITHDRAW</button></div><div class="m" id="withdrawInfo" style="margin-top:5px"></div>';
  }
  window.withdrawStrategy=async function(){
    const a=Number(document.getElementById('withdrawAmount')?.value||0);
    if(!(a>0)){alert('Укажи сумму вывода');return;}
    try{
      const r=await fetch('/api/strategy/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:a})});
      const d=await r.json();
      if(!r.ok) throw Error(d.detail||'Withdraw error');
      document.getElementById('withdrawAmount').value='';
      document.getElementById('withdrawInfo').textContent='Transferred to Account Balance: '+Number(a).toFixed(4)+' USDT';
      if(typeof load==='function') await load();
    }catch(e){document.getElementById('withdrawInfo').textContent=e.message;}
  };
  async function syncBalances(){
    try{
      ensureWithdraw();
      const r=await fetch('/api/state',{cache:'no-store'}); const d=await r.json();
      if(document.getElementById('account')) document.getElementById('account').textContent=Number(d.account||0).toFixed(4)+' USDT';
      if(document.getElementById('free')) document.getElementById('free').textContent=Number(d.free||0).toFixed(4)+' / '+Number(d.bot_balance||0).toFixed(4)+' USDT';
      if(document.getElementById('strategyProfit')) document.getElementById('strategyProfit').textContent=Number(d.strategy_profit||0).toFixed(4);
      const info=document.getElementById('withdrawInfo');
      if(info && !info.textContent) info.textContent='Available: '+Number(d.withdraw_available||0).toFixed(4)+' USDT';
    }catch(e){}
  }
  setTimeout(syncBalances,300); setInterval(syncBalances,5000);
})();
</script>'''
    m.HTML = m.HTML.replace(marker, injected + marker)
