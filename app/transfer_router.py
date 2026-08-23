from __future__ import annotations
from typing import Any
from .exchange_gateway import _norm_network, gateway

def _network_map(currencies: dict[str, Any], asset: str):
    info=currencies.get(asset.upper(),{});out={}
    for key,value in (info.get("networks") or {}).items():
        n=dict(value or {});canonical=_norm_network(n.get("network") or n.get("id") or key)
        if canonical:out[canonical]=n
    return out

def common_transfer_network(source_exchange:str,destination_exchange:str,asset:str):
    src=_network_map(gateway(source_exchange).currencies(),asset);dst=_network_map(gateway(destination_exchange).currencies(),asset);candidates=[]
    for network in sorted(set(src)&set(dst)):
        s,d=src[network],dst[network]
        if s.get("withdraw") is False or d.get("deposit") is False:continue
        candidates.append({"network":network,"withdraw_fee":s.get("fee"),"source":s,"destination":d})
    if not candidates:return None
    candidates.sort(key=lambda x:(x["withdraw_fee"] is None,x["withdraw_fee"] or 0));return candidates[0]

def plan_cross_exchange(symbol_buy:str,symbol_sell:str,asset:str,source_exchange:str,destination_exchange:str,amount:float):
    network=common_transfer_network(source_exchange,destination_exchange,asset)
    if not network:return {"executable":False,"reason":"no_common_deposit_withdraw_network"}
    buy_book=gateway(source_exchange).fetch_order_book(symbol_buy,5);sell_book=gateway(destination_exchange).fetch_order_book(symbol_sell,5)
    buy_ask=buy_book.get("asks",[[None]])[0][0] if buy_book.get("asks") else None;sell_bid=sell_book.get("bids",[[None]])[0][0] if sell_book.get("bids") else None
    gross_edge_pct=((sell_bid/buy_ask)-1)*100 if buy_ask and sell_bid else None
    return {"executable":False,"armed":False,"reason":"planning_only","economics":{"buy_ask":buy_ask,"sell_bid":sell_bid,"gross_edge_pct":gross_edge_pct,"withdraw_fee":network["withdraw_fee"]},"buy":{"exchange":source_exchange,"symbol":symbol_buy,"side":"buy","amount":amount},"transfer":{"asset":asset,"network":network["network"],"withdraw_fee":network["withdraw_fee"]},"sell":{"exchange":destination_exchange,"symbol":symbol_sell,"side":"sell","amount":amount},"required_checks":["source_account_can_withdraw","destination_account_can_deposit","destination_address_is_verified","network_matches_exactly","minimum_withdrawal_and_deposit_limits","all_trading_and_transfer_fees","price_and_liquidity_slippage","regional_product_eligibility","transfer_time_risk"]}
