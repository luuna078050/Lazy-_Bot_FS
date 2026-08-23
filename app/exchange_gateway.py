"""Exchange-agnostic trading gateway for LazyBot FS.

Uses CCXT for normalized market/account/order access. Live trading remains
explicitly controlled by LIVE_TRADING in the deployment environment.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any
import ccxt
NETWORK_ALIASES={"ETH":{"ETH","ERC20","ETHEREUM"},"TRX":{"TRX","TRC20","TRON"},"BSC":{"BSC","BEP20","BEP-20","BNB SMART CHAIN"},"SOL":{"SOL","SOLANA"},"MATIC":{"MATIC","POLYGON","POL"},"ARB":{"ARB","ARBITRUM","ARBITRUM ONE"},"OP":{"OP","OPTIMISM"},"BASE":{"BASE"},"AVAXC":{"AVAXC","AVALANCHE C-CHAIN","C-CHAIN"},"BTC":{"BTC","BITCOIN"},"LTC":{"LTC","LITECOIN"}}
def _norm_network(value:str|None)->str:
    raw=(value or "").strip().upper().replace("_"," ")
    for canonical,aliases in NETWORK_ALIASES.items():
        if raw in aliases:return canonical
    return raw.replace(" ","")
@dataclass(frozen=True)
class ExchangeConfig:
    exchange_id:str; api_key:str|None=None; secret:str|None=None; password:str|None=None; sandbox:bool=False
class ExchangeGateway:
    def __init__(self,config:ExchangeConfig):
        if not hasattr(ccxt,config.exchange_id):raise ValueError(f"Unsupported CCXT exchange: {config.exchange_id}")
        cls=getattr(ccxt,config.exchange_id); params:dict[str,Any]={"enableRateLimit":True}
        if config.api_key:params["apiKey"]=config.api_key
        if config.secret:params["secret"]=config.secret
        if config.password:params["password"]=config.password
        self.exchange=cls(params)
        if config.sandbox and hasattr(self.exchange,"set_sandbox_mode"):self.exchange.set_sandbox_mode(True)
    @property
    def id(self):return self.exchange.id
    def load_markets(self):return self.exchange.load_markets()
    def public_capabilities(self):
        markets=self.load_markets(); spot=[s for s,m in markets.items() if m.get("spot") and m.get("active",True)]
        return {"exchange":self.id,"spot_markets":len(spot),"has":{k:bool(v) for k,v in self.exchange.has.items() if k in {"fetchBalance","fetchCurrencies","fetchOrderBook","fetchTicker","createOrder","withdraw","fetchDepositAddress","fetchTradingFee"}}}
    def market_entry_requirements(self,symbol:str):
        markets=self.load_markets(); market=markets.get(symbol)
        if not market or not market.get("active",True):raise ValueError("symbol_not_available")
        if not market.get("spot"):raise ValueError("not_spot_market")
        limits=market.get("limits") or {}; amount_limits=limits.get("amount") or {}; cost_limits=limits.get("cost") or {}
        amount_min=amount_limits.get("min"); cost_min=cost_limits.get("min")
        precision=(market.get("precision") or {}).get("amount")
        ticker=self.exchange.fetch_ticker(symbol); price=float(ticker.get("ask") or ticker.get("last") or 0)
        min_amount=float(amount_min) if amount_min is not None else None
        min_cost=float(cost_min) if cost_min is not None else None
        if min_amount is not None and price>0:min_cost=max(min_cost or 0.0,min_amount*price)
        quote=market.get("quote")
        return {"exchange":self.id,"symbol":symbol,"base":market.get("base"),"quote":quote,"current_ask":price,"minimum_amount":min_amount,"minimum_cost":min_cost,"amount_precision":precision,"minimum_entry_note":f"Минимальный вход: {min_cost:.8g} {quote}" if min_cost else "Минимальный вход определяется биржей при исполнении"}
    def account_preflight(self,symbol:str|None=None):
        result={"exchange":self.id,"eligible":True,"errors":[]}; markets=self.load_markets()
        if symbol:
            market=markets.get(symbol)
            if not market or not market.get("active",True):result["eligible"]=False;result["errors"].append("symbol_not_available")
            elif not market.get("spot"):result["eligible"]=False;result["errors"].append("not_spot_market")
        if getattr(self.exchange,"apiKey",None) and getattr(self.exchange,"secret",None):
            try:self.exchange.fetch_balance();result["private_api"]=True
            except Exception as exc:result["private_api"]=False;result["eligible"]=False;result["errors"].append({"type":type(exc).__name__,"message":str(exc)[:300]})
        else:result["private_api"]=False;result["errors"].append("private_credentials_missing")
        return result
    def resolve_spot_symbol(self,base:str,quote:str)->str|None:
        base=base.upper();quote=quote.upper()
        for symbol,market in self.load_markets().items():
            if market.get("spot") and market.get("active",True) and market.get("base")==base and market.get("quote")==quote:return symbol
        return None
    def find_quote_options(self,base:str,quotes:list[str]|None=None)->list[str]:
        quotes=[q.upper() for q in (quotes or ["USDC","USDT","EUR","USD","BTC","ETH"])]
        return [q for q in quotes if self.resolve_spot_symbol(base,q)]
    def fetch_order_book(self,symbol:str,limit:int=20):self.load_markets();return self.exchange.fetch_order_book(symbol,limit=limit)
    def fetch_balance(self):return self.exchange.fetch_balance()
    def create_limit_order(self,symbol:str,side:str,amount:float,price:float,live:bool=False):
        if not live:return {"dry_run":True,"exchange":self.id,"symbol":symbol,"side":side,"amount":amount,"price":price}
        if os.getenv("LIVE_TRADING","false").lower()!="true" or os.getenv("LIVE_TRADING_ARMED","false").lower()!="true":raise PermissionError("Live trading is not armed")
        return self.exchange.create_order(symbol,"limit",side,amount,price)
    def create_market_order(self,symbol:str,side:str,amount:float,live:bool=False):
        if not live:return {"dry_run":True,"exchange":self.id,"symbol":symbol,"side":side,"amount":amount}
        if os.getenv("LIVE_TRADING","false").lower()!="true" or os.getenv("LIVE_TRADING_ARMED","false").lower()!="true":raise PermissionError("Live trading is not armed")
        return self.exchange.create_order(symbol,"market",side,amount)
    def currencies(self):return self.exchange.fetch_currencies() if self.exchange.has.get("fetchCurrencies") else {}
def configured_exchange_ids():return [x.strip().lower() for x in os.getenv("EXCHANGES","binance,kraken,okx,coinbase").split(",") if x.strip()]
def gateway(exchange_id:str):
    eid=exchange_id.lower();prefix=eid.upper();key=os.getenv(f"{prefix}_API_KEY") or (os.getenv("BINANCE_API_KEY") if eid=="binance" else None);secret=os.getenv(f"{prefix}_API_SECRET") or (os.getenv("BINANCE_API_SECRET") if eid=="binance" else None);password=os.getenv(f"{prefix}_API_PASSWORD");sandbox=os.getenv(f"{prefix}_SANDBOX","false").lower()=="true";return ExchangeGateway(ExchangeConfig(eid,key,secret,password,sandbox))
def choose_best_spot(exchange_ids,symbol):
    rows=[]
    for eid in exchange_ids:
        try:
            g=gateway(eid);pre=g.account_preflight(symbol)
            if not pre["eligible"]:rows.append({"exchange":eid,"eligible":False,"errors":pre["errors"]});continue
            book=g.fetch_order_book(symbol,5);bid=book.get("bids",[[None]])[0][0] if book.get("bids") else None;ask=book.get("asks",[[None]])[0][0] if book.get("asks") else None;rows.append({"exchange":eid,"eligible":True,"bid":bid,"ask":ask,"spread":(ask-bid) if bid and ask else None})
        except Exception as exc:rows.append({"exchange":eid,"eligible":False,"errors":[{"type":type(exc).__name__,"message":str(exc)[:300]}]})
    return sorted(rows,key=lambda x:(not x.get("eligible",False),x.get("spread") is None,x.get("spread") or float("inf")))
