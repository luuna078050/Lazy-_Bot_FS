"""Cross-exchange transfer planning.

The planner can identify a buy -> transfer -> sell route and a common network.
Actual withdrawals are intentionally disabled by default; the router must first
validate destination address/network, fees, limits, and account permissions.
"""
from __future__ import annotations

from typing import Any

from .exchange_gateway import _norm_network, gateway


def _network_map(currencies: dict[str, Any], asset: str) -> dict[str, dict[str, Any]]:
    info = currencies.get(asset.upper(), {})
    networks = info.get("networks") or {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in networks.items():
        n = dict(value or {})
        canonical = _norm_network(n.get("network") or n.get("id") or key)
        if canonical:
            out[canonical] = n
    return out


def common_transfer_network(source_exchange: str, destination_exchange: str, asset: str) -> dict[str, Any] | None:
    src = _network_map(gateway(source_exchange).currencies(), asset)
    dst = _network_map(gateway(destination_exchange).currencies(), asset)
    common = sorted(set(src) & set(dst))
    candidates = []
    for network in common:
        s, d = src[network], dst[network]
        if s.get("withdraw") is False or d.get("deposit") is False:
            continue
        fee = s.get("fee")
        candidates.append({"network": network, "withdraw_fee": fee, "source": s, "destination": d})
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x["withdraw_fee"] is None, x["withdraw_fee"] or 0))
    return candidates[0]


def plan_cross_exchange(symbol_buy: str, symbol_sell: str, asset: str, source_exchange: str, destination_exchange: str, amount: float) -> dict[str, Any]:
    network = common_transfer_network(source_exchange, destination_exchange, asset)
    if not network:
        return {"executable": False, "reason": "no_common_deposit_withdraw_network"}
    return {
        "executable": False,
        "armed": False,
        "reason": "planning_only",
        "buy": {"exchange": source_exchange, "symbol": symbol_buy, "side": "buy", "amount": amount},
        "transfer": {"asset": asset, "network": network["network"], "withdraw_fee": network["withdraw_fee"]},
        "sell": {"exchange": destination_exchange, "symbol": symbol_sell, "side": "sell", "amount": amount},
        "required_checks": [
            "source_account_can_withdraw",
            "destination_account_can_deposit",
            "destination_address_is_verified",
            "network_matches_exactly",
            "minimum_withdrawal_and_deposit_limits",
            "all_trading_and_transfer_fees",
            "price_and_liquidity_slippage",
            "regional_product_eligibility",
        ],
    }
