import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

def validate_market_data(
    df: pd.DataFrame,
    option_chain: Optional[Dict[str, Any]] = None,
    max_delay_minutes: int = 30
) -> Tuple[bool, str]:
    """
    Validates market and option-chain data quality.
    Returns (is_valid, error_reason)
    """
    # 1. Validate Spot DataFrame
    if df.empty:
        return False, "DATA QUALITY FAILURE: Market Spot DataFrame is empty."
        
    if len(df) < 20:
        return False, f"DATA QUALITY FAILURE: Insufficient candles ({len(df)} < 20)."

    # Check for duplicate timestamps in index
    if df.index.duplicated().any():
        return False, "DATA QUALITY FAILURE: Duplicate timestamps detected in price history."

    # Check for stale data (timestamp check) - Skip in SIMULATION mode
    import os
    system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()
    if system_mode != "SIMULATION":
        latest_time = df.index[-1]
        now = datetime.now(timezone.utc)
        
        # Standardize timezone comparison
        if latest_time.tzinfo is not None:
            delay = (now - latest_time).total_seconds() / 60.0
        else:
            # Assume UTC if naive
            naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
            delay = (naive_now - latest_time).total_seconds() / 60.0

        if delay > max_delay_minutes:
            return False, f"DATA QUALITY FAILURE: Price feed is stale by {delay:.1f} minutes."

    # Check for dead prices (stale prices over last 10 candles)
    closes = df["Close"].values
    if len(closes) >= 10:
        last_10 = closes[-10:]
        if np.all(last_10 == last_10[0]) and last_10[0] > 0:
            return False, "DATA QUALITY FAILURE: Price feed frozen (LTP constant over last 10 ticks)."

    # Check for invalid values
    if df["Close"].isna().any() or (df["Close"] <= 0).any():
        return False, "DATA QUALITY FAILURE: NaN or negative prices detected in history."

    # 2. Validate Option Chain (if provided)
    if option_chain is not None:
        if not option_chain or "chain" not in option_chain or not option_chain["chain"]:
            return False, "DATA QUALITY FAILURE: Option chain payload is empty or missing."

        spot_price = option_chain.get("spot_price", 0.0)
        atm_strike = option_chain.get("atm_strike", 0)
        
        if spot_price <= 0 or atm_strike <= 0:
            return False, "DATA QUALITY FAILURE: Invalid spot price or ATM strike in option chain."

        # Check for stale contract prices / mismatch
        chain_list = option_chain["chain"]
        
        # Verify strikes presence
        strikes = [x["strike"] for x in chain_list]
        if len(strikes) < 3:
            return False, f"DATA QUALITY FAILURE: Insufficient option strikes listed ({len(strikes)} < 3)."

        # Check if option prices are frozen/stale
        ce_prices = [x["ce_ltp"] for x in chain_list]
        pe_prices = [x["pe_ltp"] for x in chain_list]
        
        if all(p == 0 for p in ce_prices) or all(p == 0 for p in pe_prices):
            return False, "DATA QUALITY FAILURE: Option premiums are invalid (all LTPs zero)."

    return True, "DATA QUALITY OK"
