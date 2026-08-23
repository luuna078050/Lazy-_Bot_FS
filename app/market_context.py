from __future__ import annotations
from datetime import datetime, timezone
import requests

def _get_json(url: str, params: dict | None = None):
    r = requests.get(url, params=params, timeout=8, headers={'User-Agent':'LazyBot-FS/1.0'})
    r.raise_for_status()
    return r.json()

def context_snapshot():
    now = datetime.now(timezone.utc).isoformat()
    try:
        data = _get_json('https://api.coingecko.com/api/v3/global')
        m = data.get('data', {})
        total_change = float(m.get('market_cap_change_percentage_24h_usd') or 0)
        btc_dom = float(m.get('market_cap_percentage', {}).get('btc') or 0)
    except Exception:
        total_change, btc_dom = 0.0, 0.0
    events = [
        {'topic':'Trump / crypto regulation','impact':'bullish','weight':0.8,'note':'Pro-crypto regulatory push and pressure for clearer digital-asset rules.'},
        {'topic':'US tariffs / trade policy','impact':'risk','weight':-0.6,'note':'Tariff decisions can increase volatility, risk-off flows and dollar/yield sensitivity.'},
        {'topic':'US Treasury / liquidity','impact':'bullish-risk','weight':0.5,'note':'Treasury liquidity and buyback expectations can affect yields, dollar and crypto beta.'},
    ]
    score = max(-1.0, min(1.0, total_change / 5.0 + sum(e['weight'] for e in events) / 10.0))
    regime = 'RISK_ON' if score > 0.25 else 'RISK_OFF' if score < -0.25 else 'MIXED'
    return {'timestamp':now,'regime':regime,'score':round(score,3),'crypto_market_24h_pct':round(total_change,3),'btc_dominance_pct':round(btc_dom,3),'events':events,'policy_note':'Policy/news context is a risk modifier; it never overrides price, liquidity, execution or risk limits.'}
