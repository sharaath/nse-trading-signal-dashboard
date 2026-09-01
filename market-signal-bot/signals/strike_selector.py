import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

def score_and_select_best_strike(
    option_chain: Dict[str, Any],
    option_type: str,
    close_price: float
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Ranks all available option strikes based on normalized (0-100) scoring components.
    Formula:
      Strike Score = 0.25*Liquidity + 0.25*Premium Momentum + 0.20*OI Change + 0.20*Spread + 0.10*Delta
    """
    chain_list = option_chain.get("chain", [])
    if not chain_list:
        return None, []

    target_delta = 0.55 if option_type == "CE" else -0.55
    atm_strike = option_chain.get("atm_strike", int(close_price))
    
    ranked_strikes = []

    for contract in chain_list:
        strike = contract["strike"]
        
        # 1. Extract values
        ltp = contract["ce_ltp"] if option_type == "CE" else contract["pe_ltp"]
        delta = contract["ce_delta"] if option_type == "CE" else contract["pe_delta"]
        oi = contract["ce_oi"] if option_type == "CE" else contract["pe_oi"]
        vol = contract["ce_volume"] if option_type == "CE" else contract["pe_volume"]
        chng_pct = contract["ce_chng_pct"] if option_type == "CE" else contract["pe_chng_pct"]
        
        # In real APIs change in open interest might be mapped, else fallback
        oi_change = int(contract.get("ce_oi_change" if option_type == "CE" else "pe_oi_change") or int(oi * 0.05))
        
        # Spread estimation (from real bid/ask, default to 0.5% if bid/ask not present or invalid)
        bid = float(contract.get("ce_bid" if option_type == "CE" else "pe_bid") or 0.0)
        ask = float(contract.get("ce_ask" if option_type == "CE" else "pe_ask") or 0.0)
        if bid > 0 and ask >= bid:
            spread_pct = (ask - bid) / bid
        else:
            spread_pct = 0.005
        
        # 2. Normalize components to 0-100
        
        # Liquidity (Volume-based)
        if vol >= 10000:
            liq_score = 100.0
        elif vol <= 500:
            liq_score = 0.0
        else:
            liq_score = ((vol - 500) / 9500.0) * 100.0
            
        # Premium Momentum
        if chng_pct >= 50.0:
            mom_score = 100.0
        elif chng_pct <= -20.0:
            mom_score = 0.0
        else:
            mom_score = ((chng_pct + 20.0) / 70.0) * 100.0
            
        # OI Change
        if oi_change >= 5000:
            oic_score = 100.0
        elif oi_change <= 0:
            oic_score = 0.0
        else:
            oic_score = (oi_change / 5000.0) * 100.0
            
        # Non-linear Spread Score
        if spread_pct < 0.005:
            spread_score = 100.0
        elif spread_pct < 0.01:
            spread_score = 90.0
        elif spread_pct < 0.02:
            spread_score = 70.0
        elif spread_pct < 0.05:
            spread_score = 40.0
        else:
            spread_score = 0.0
            
        # Delta Score
        delta_diff = abs(delta - target_delta)
        if delta_diff >= 0.25:
            delta_score = 0.0
        else:
            delta_score = ((0.25 - delta_diff) / 0.25) * 100.0

        # Calculate final weighted score
        final_score = (
            0.25 * liq_score +
            0.25 * mom_score +
            0.20 * oic_score +
            0.20 * spread_score +
            0.10 * delta_score
        )
        
        # Reject far OTM strike selections (delta < 0.2)
        if abs(delta) < 0.20:
            final_score -= 50.0  # heavy penalty

        ranked_strikes.append({
            "strike": strike,
            "score": round(final_score, 1),
            "ltp": ltp,
            "delta": delta,
            "volume": vol,
            "oi": oi,
            "spread_pct": spread_pct,
            "contract": contract
        })

    # Sort descending by score
    ranked_strikes.sort(key=lambda x: x["score"], reverse=True)
    
    best_strike = ranked_strikes[0] if ranked_strikes else None
    return best_strike, ranked_strikes
