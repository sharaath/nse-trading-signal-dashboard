import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional

def detect_swings(df: pd.DataFrame, window: int = 3, up_to_index: Optional[int] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Detects swing highs and swing lows with strict Point-in-Time integrity.
    A swing at index i requires window bars before AND window bars after.
    Therefore, at time T (up_to_index), a swing at i is ONLY confirmed if i + window <= up_to_index.
    """
    swing_highs = []
    swing_lows = []
    
    if len(df) < 2 * window + 1:
        return swing_highs, swing_lows
        
    eval_limit = up_to_index if up_to_index is not None else (len(df) - 1)
    # A candidate at index i needs i + window <= eval_limit
    max_candidate_idx = eval_limit - window
    if max_candidate_idx < window:
        return swing_highs, swing_lows

    highs = df['High'].values
    lows = df['Low'].values
    times = df.index
    closes = df['Close'].values
    
    for i in range(window, max_candidate_idx + 1):
        val_high = highs[i]
        val_low = lows[i]
        
        # Check swing high
        is_high = True
        for j in range(1, window + 1):
            if highs[i - j] >= val_high or highs[i + j] > val_high:
                is_high = False
                break
        if is_high:
            swing_highs.append({
                "index": i,
                "price": float(val_high),
                "timestamp": str(times[i]),
                "type": "high"
            })
            
        # Check swing low
        is_low = True
        for j in range(1, window + 1):
            if lows[i - j] <= val_low or lows[i + j] < val_low:
                is_low = False
                break
        if is_low:
            swing_lows.append({
                "index": i,
                "price": float(val_low),
                "timestamp": str(times[i]),
                "type": "low"
            })
            
    return swing_highs, swing_lows

def detect_liquidity_levels(
    df: pd.DataFrame,
    daily_df: Optional[pd.DataFrame] = None,
    window: int = 3
) -> Dict[str, List[float]]:
    """
    Calculates key liquidity pool levels:
    - PDH (Previous Day High), PDL (Previous Day Low)
    - PWH (Previous Week High), PWL (Previous Week Low)
    - Significant Swing Highs / Swing Lows from the intraday chart
    """
    levels = {
        "pdh": [],
        "pdl": [],
        "pwh": [],
        "pwl": [],
        "swings_high": [],
        "swings_low": []
    }
    
    # 1. Fetch from daily data if provided
    if daily_df is not None and len(daily_df) >= 2:
        # Latest daily bar completed is iloc[-2] (or iloc[-1] if daily_df represents closed bars)
        # To be safe, we extract the last completed daily bar (or last few)
        last_daily = daily_df.iloc[-1]
        levels["pdh"].append(float(last_daily["High"]))
        levels["pdl"].append(float(last_daily["Low"]))
        
        # Weekly high/low
        if len(daily_df) >= 5:
            last_5_days = daily_df.tail(5)
            levels["pwh"].append(float(last_5_days["High"].max()))
            levels["pwl"].append(float(last_5_days["Low"].min()))
            
    # 2. Extract swings from the intraday dataframe
    sh, sl = detect_swings(df, window=window)
    levels["swings_high"] = [s["price"] for s in sh[-10:]] # last 10 highs
    levels["swings_low"] = [s["price"] for s in sl[-10:]]  # last 10 lows
    
    return levels

def check_liquidity_sweep(
    df: pd.DataFrame,
    levels: Dict[str, List[float]],
    lookback_candles: int = 5
) -> Dict[str, Any]:
    """
    Checks if a liquidity sweep occurred on the latest completed candles.
    A sweep is defined as price dipping below support/low (or surging above resistance/high)
    but closing back inside the range, indicating rejection.
    """
    result = {"bullish_sweep": False, "bearish_sweep": False, "swept_level": 0.0, "level_type": ""}
    
    if len(df) < lookback_candles:
        return result
        
    # We evaluate on the latest completed candle (iloc[-2]) or the one before it to prevent repainting.
    # To capture immediate sweeps, let's examine the last 3 completed candles.
    for offset in [-2, -3]:
        row = df.iloc[offset]
        low_val = float(row["Low"])
        high_val = float(row["High"])
        close_val = float(row["Close"])
        
        # Bullish sweep (sweeping low/support and closing higher)
        # Check against PDL, PWL, and Swing Lows
        for level in levels["pdl"] + levels["pwl"] + levels["swings_low"]:
            # If low penetrated the level, but close is above it
            if low_val < level and close_val > level:
                # Rejection confirmation: body should close in top 50% of the range
                candle_range = high_val - low_val
                if candle_range > 0 and (close_val - low_val) / candle_range > 0.4:
                    result["bullish_sweep"] = True
                    result["swept_level"] = level
                    result["level_type"] = "PDL/Swing Low"
                    return result
                    
        # Bearish sweep (sweeping high/resistance and closing lower)
        for level in levels["pdh"] + levels["pwh"] + levels["swings_high"]:
            if high_val > level and close_val < level:
                # Rejection confirmation: body should close in bottom 50% of the range
                candle_range = high_val - low_val
                if candle_range > 0 and (high_val - close_val) / candle_range > 0.4:
                    result["bearish_sweep"] = True
                    result["swept_level"] = level
                    result["level_type"] = "PDH/Swing High"
                    return result
                    
    return result

def detect_displacement(df: pd.DataFrame, index: int, lookback: int = 20) -> bool:
    """
    Detects if the candle at 'index' has displacement (unusually high volume and body range).
    Body must exceed 1.5x of the average body size over lookback.
    """
    if index < lookback:
        return False
        
    bodies = (df["Close"] - df["Open"]).abs().values
    current_body = bodies[index]
    avg_body = np.mean(bodies[index - lookback:index])
    
    # Also check volume expansion if volume is present
    vol_expansion = True
    if "Volume" in df.columns:
        vols = df["Volume"].values
        current_vol = vols[index]
        avg_vol = np.mean(vols[index - lookback:index])
        if avg_vol > 0:
            vol_expansion = current_vol > 1.2 * avg_vol
            
    return current_body > 1.5 * avg_body and vol_expansion

def detect_mss_choch(
    df: pd.DataFrame,
    swings_high: List[Dict[str, Any]],
    swings_low: List[Dict[str, Any]],
    sweep_result: Dict[str, Any]
) -> Tuple[bool, Optional[int], float]:
    """
    Detects Market Structure Shift (MSS) after a liquidity sweep.
    - Bullish MSS: After a bullish sweep, price breaks above the recent swing high with displacement.
    - Bearish MSS: After a bearish sweep, price breaks below the recent swing low with displacement.
    """
    mss_detected = False
    mss_index = None
    trigger_price = 0.0
    
    if not sweep_result["bullish_sweep"] and not sweep_result["bearish_sweep"]:
        return mss_detected, mss_index, trigger_price
        
    closes = df["Close"].values
    
    if sweep_result["bullish_sweep"] and swings_high:
        # Find the last swing high before the sweep
        recent_highs = [s for s in swings_high if s["index"] < len(df) - 1]
        if not recent_highs:
            return mss_detected, mss_index, trigger_price
        target_high = recent_highs[-1]
        level_to_break = target_high["price"]
        
        # Check last 5 candles for a close above this level with displacement
        for idx in range(len(df) - 5, len(df) - 1):
            if idx < 0:
                continue
            if closes[idx] > level_to_break:
                # Verify displacement
                if detect_displacement(df, idx):
                    mss_detected = True
                    mss_index = idx
                    trigger_price = level_to_break
                    break
                    
    elif sweep_result["bearish_sweep"] and swings_low:
        recent_lows = [s for s in swings_low if s["index"] < len(df) - 1]
        if not recent_lows:
            return mss_detected, mss_index, trigger_price
        target_low = recent_lows[-1]
        level_to_break = target_low["price"]
        
        # Check last 5 candles for a close below this level with displacement
        for idx in range(len(df) - 5, len(df) - 1):
            if idx < 0:
                continue
            if closes[idx] < level_to_break:
                if detect_displacement(df, idx):
                    mss_detected = True
                    mss_index = idx
                    trigger_price = level_to_break
                    break
                    
    return mss_detected, mss_index, trigger_price

def detect_fvgs(df: pd.DataFrame, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Finds Fair Value Gaps (FVG) in the latest 'limit' completed candles.
    Returns list of unmitigated and mitigated FVGs.
    """
    fvgs = []
    if len(df) < 3:
        return fvgs
        
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    times = df.index
    
    # Scan recent candles
    start_idx = max(2, len(df) - 30)
    for i in range(start_idx, len(df) - 1):
        # Bullish FVG: Candle 1 High < Candle 3 Low
        if highs[i - 2] < lows[i]:
            fvg_top = lows[i]
            fvg_bottom = highs[i - 2]
            fvg_size = fvg_top - fvg_bottom
            
            # Check if mitigated by any candle after i
            mitigated = False
            mitigation_index = None
            for k in range(i + 1, len(df)):
                if lows[k] <= fvg_bottom:
                    mitigated = True
                    mitigation_index = k
                    break
                    
            fvgs.append({
                "type": "bullish",
                "index": i - 1, # FVG sits at candle i-1
                "timestamp": str(times[i - 1]),
                "top": float(fvg_top),
                "bottom": float(fvg_bottom),
                "size": float(fvg_size),
                "mitigated": mitigated,
                "mitigation_index": mitigation_index
            })
            
        # Bearish FVG: Candle 1 Low > Candle 3 High
        elif lows[i - 2] > highs[i]:
            fvg_top = lows[i - 2]
            fvg_bottom = highs[i]
            fvg_size = fvg_top - fvg_bottom
            
            mitigated = False
            mitigation_index = None
            for k in range(i + 1, len(df)):
                if highs[k] >= fvg_top:
                    mitigated = True
                    mitigation_index = k
                    break
                    
            fvgs.append({
                "type": "bearish",
                "index": i - 1,
                "timestamp": str(times[i - 1]),
                "top": float(fvg_top),
                "bottom": float(fvg_bottom),
                "size": float(fvg_size),
                "mitigated": mitigated,
                "mitigation_index": mitigation_index
            })
            
    return fvgs

def detect_order_blocks(
    df: pd.DataFrame,
    mss_index: Optional[int],
    direction: str
) -> Optional[Dict[str, Any]]:
    """
    Detects Order Blocks (OB).
    - Bullish OB: The last down close candle before a bullish MSS displacement.
    - Bearish OB: The last up close candle before a bearish MSS displacement.
    """
    if mss_index is None or mss_index < 2:
        return None
        
    opens = df["Open"].values
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    times = df.index
    
    # Search backwards from the MSS trigger to find the origin of the displacement move
    # Typically within last 5-8 candles before the MSS break
    for i in range(mss_index, max(0, mss_index - 8), -1):
        if direction == "BULLISH" and closes[i] < opens[i]:
            # Last down close candle
            # Check if subsequent candles mitigated it
            mitigated = False
            for k in range(mss_index + 1, len(df)):
                if lows[k] < lows[i]:
                    mitigated = True
                    break
            return {
                "type": "bullish",
                "index": i,
                "timestamp": str(times[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "mitigated": mitigated
            }
        elif direction == "BEARISH" and closes[i] > opens[i]:
            # Last up close candle
            mitigated = False
            for k in range(mss_index + 1, len(df)):
                if highs[k] > highs[i]:
                    mitigated = True
                    break
            return {
                "type": "bearish",
                "index": i,
                "timestamp": str(times[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "mitigated": mitigated
            }
            
    return None

def check_po3_setup(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Power of Three (PO3): Accumulation -> Manipulation -> Distribution
    Determines if current intraday chart shows a daily PO3 structure:
    1. Flat trading during session open (Accumulation)
    2. Sharp stop hunt sweeping session range (Manipulation)
    3. Strong directional trend expansion (Distribution)
    """
    result = {"is_po3": False, "phase": "UNKNOWN", "details": ""}
    if len(df) < 30:
        return result
        
    # Standard session open refers to first 10 candles (e.g. 9:15 - 9:45 AM on 3-min chart)
    # We analyze the price ranges relative to daily open
    daily_open = float(df.iloc[0]["Open"])
    session_range = df.iloc[0:15]
    session_high = float(session_range["High"].max())
    session_low = float(session_range["Low"].min())
    
    # Check if subsequent price action swept the session range
    post_session = df.iloc[15:]
    if post_session.empty:
        return result
        
    swept_low = float(post_session["Low"].min()) < session_low
    swept_high = float(post_session["High"].max()) > session_high
    
    current_price = float(df.iloc[-1]["Close"])
    
    # Bullish PO3: Daily open -> dip down (manipulation) -> expand up (distribution)
    if swept_low and not swept_high and current_price > session_high:
        result["is_po3"] = True
        result["phase"] = "DISTRIBUTION"
        result["details"] = "Accumulation range swept to the downside (low sweep), now expanding bullishly."
    # Bearish PO3: Daily open -> rally up (manipulation) -> expand down (distribution)
    elif swept_high and not swept_low and current_price < session_low:
        result["is_po3"] = True
        result["phase"] = "DISTRIBUTION"
        result["details"] = "Accumulation range swept to the upside (high sweep), now expanding bearishly."
        
    return result

def check_crt_4h_sweep(
    df_4h: pd.DataFrame,
    current_high: float,
    current_low: float,
    current_price: float,
    sweep_mode: str = "LIVE_SWEEP"  # "LIVE_SWEEP" (Mode A) or "CONFIRMED_SWEEP" (Mode B)
) -> Dict[str, Any]:
    """
    Candle Range Theory (CRT) 4H Sweep Detection with strict anti-lookahead integrity.
    Never uses the forming 4H candle's close until the candle is completed.
    - Mode A (LIVE_SWEEP): current_4H_high > prev_4H_high (or low < prev_4H_low) -> SWEEP_DETECTED
    - Mode B (CONFIRMED_SWEEP): requires 4H candle close back inside range -> SWEEP_CONFIRMED
    """
    result = {
        "sweep_detected": False,
        "sweep_confirmed": False,
        "direction": "NONE",
        "sweep_level": 0.0,
        "sweep_high": 0.0,
        "sweep_low": 0.0,
        "break_closing_level": 0.0,
        "prev_4h_high": 0.0,
        "prev_4h_low": 0.0,
        "prev_4h_open": 0.0,
        "prev_4h_close": 0.0,
        "mode": sweep_mode,
        "status": "NOT_PRESENT"
    }
    
    if df_4h is None or len(df_4h) < 2:
        return result

    # The previous completed 4H bar is iloc[-2] if df_4h contains the forming bar, else iloc[-1]
    prev_bar = df_4h.iloc[-2] if len(df_4h) >= 2 else df_4h.iloc[-1]
    prev_h = float(prev_bar["High"])
    prev_l = float(prev_bar["Low"])
    prev_o = float(prev_bar["Open"])
    prev_c = float(prev_bar["Close"])

    result["prev_4h_high"] = prev_h
    result["prev_4h_low"] = prev_l
    result["prev_4h_open"] = prev_o
    result["prev_4h_close"] = prev_c

    # Bearish CRT candidate: current candle pushed above previous 4H high
    if current_high > prev_h:
        # Rejection: current price is trading back below or at previous high
        if current_price <= prev_h or (current_high - current_price) > (current_high - prev_h) * 0.5:
            result["sweep_detected"] = True
            result["direction"] = "BEARISH"
            result["sweep_level"] = prev_h
            result["sweep_high"] = current_high
            result["sweep_low"] = current_low
            # The Break Closing Level is the lower of previous close or open
            result["break_closing_level"] = min(prev_o, prev_c)
            result["status"] = "SWEEP_DETECTED"
            
            # Mode B check (if 4H candle has fully closed)
            if sweep_mode == "CONFIRMED_SWEEP" and current_price < prev_h:
                result["sweep_confirmed"] = True
                result["status"] = "SWEEP_CONFIRMED"
            elif sweep_mode == "LIVE_SWEEP":
                result["status"] = "SWEEP_DETECTED"
            return result

    # Bullish CRT candidate: current candle pushed below previous 4H low
    if current_low < prev_l:
        if current_price >= prev_l or (current_price - current_low) > (prev_l - current_low) * 0.5:
            result["sweep_detected"] = True
            result["direction"] = "BULLISH"
            result["sweep_level"] = prev_l
            result["sweep_high"] = current_high
            result["sweep_low"] = current_low
            result["break_closing_level"] = max(prev_o, prev_c)
            result["status"] = "SWEEP_DETECTED"
            
            if sweep_mode == "CONFIRMED_SWEEP" and current_price > prev_l:
                result["sweep_confirmed"] = True
                result["status"] = "SWEEP_CONFIRMED"
            elif sweep_mode == "LIVE_SWEEP":
                result["status"] = "SWEEP_DETECTED"
            return result

    return result

def check_po3_15m_framework(
    df_15m: pd.DataFrame,
    daily_open: float,
    current_price: float
) -> Dict[str, Any]:
    """
    Power of Three (PO3) AMD cycle on 15M timeframe:
    - Daily Open: benchmark price at 9:15 AM IST
    - Accumulation: Range established in first 1-2 candles (09:15-09:30 or 09:45 IST)
    - Manipulation: Judas swing pushing above daily open (bearish) or below daily open (bullish)
    - Distribution: Reversal breaking past the daily open in the true trend direction
    """
    res = {
        "daily_open": daily_open,
        "accumulation_high": daily_open,
        "accumulation_low": daily_open,
        "phase": "ACCUMULATION",
        "bias": "NEUTRAL"
    }
    if df_15m is None or len(df_15m) < 2 or daily_open <= 0:
        return res

    accum_bars = df_15m.iloc[0:min(3, len(df_15m))]
    accum_high = float(accum_bars["High"].max())
    accum_low = float(accum_bars["Low"].min())
    res["accumulation_high"] = accum_high
    res["accumulation_low"] = accum_low

    if len(df_15m) <= 2:
        res["phase"] = "ACCUMULATION"
        return res

    later_bars = df_15m.iloc[2:]
    session_high = float(later_bars["High"].max())
    session_low = float(later_bars["Low"].min())

    # Bearish PO3: Manipulated above accumulation high, now trading below daily open
    if session_high > accum_high and current_price < daily_open:
        res["phase"] = "DISTRIBUTION"
        res["bias"] = "BEARISH"
    # Bullish PO3: Manipulated below accumulation low, now trading above daily open
    elif session_low < accum_low and current_price > daily_open:
        res["phase"] = "DISTRIBUTION"
        res["bias"] = "BULLISH"
    elif session_high > accum_high or session_low < accum_low:
        res["phase"] = "MANIPULATION"
        res["bias"] = "BEARISH" if session_high > accum_high else "BULLISH"
    else:
        res["phase"] = "ACCUMULATION"
        res["bias"] = "NEUTRAL"

    return res

def detect_mathematical_mss_5m(
    df_5m: pd.DataFrame,
    swings_high: List[Dict[str, Any]],
    swings_low: List[Dict[str, Any]],
    sweep_direction: str
) -> Tuple[bool, Optional[int], float]:
    """
    Mathematical 5M Market Structure Shift (MSS) with displacement:
    - Bearish: Candle CLOSE strictly below the most recent confirmed swing low.
    - Bullish: Candle CLOSE strictly above the most recent confirmed swing high.
    Displacement required: candle body > 1.5x rolling body standard deviation.
    """
    if df_5m is None or len(df_5m) < 5 or sweep_direction not in ["BEARISH", "BULLISH"]:
        return False, None, 0.0

    closes = df_5m["Close"].values
    n = len(df_5m)

    if sweep_direction == "BEARISH" and swings_low:
        # Most recent confirmed swing low
        confirmed_lows = [s for s in swings_low if s["index"] < n - 1]
        if not confirmed_lows:
            return False, None, 0.0
        level_to_break = confirmed_lows[-1]["price"]

        # Check recent 5 completed candles for a strict close below this level
        for idx in range(max(0, n - 6), n):
            if closes[idx] < level_to_break:
                if detect_displacement(df_5m, idx):
                    return True, idx, level_to_break

    elif sweep_direction == "BULLISH" and swings_high:
        confirmed_highs = [s for s in swings_high if s["index"] < n - 1]
        if not confirmed_highs:
            return False, None, 0.0
        level_to_break = confirmed_highs[-1]["price"]

        for idx in range(max(0, n - 6), n):
            if closes[idx] > level_to_break:
                if detect_displacement(df_5m, idx):
                    return True, idx, level_to_break

    return False, None, 0.0

def detect_1m_retest_and_confirmation(
    df_1m: pd.DataFrame,
    direction: str,
    retest_level: float,
    fvg_zone: Optional[Dict[str, Any]] = None,
    lookback_candles: int = 15
) -> Tuple[bool, float, str]:
    """
    1-Minute Micro Retest and Rejection Confirmation Gate:
    After MSS, price must retrace into the FVG or Break Closing Level zone,
    and a 1M candle must confirm the rejection in the trade direction.
    """
    if df_1m is None or len(df_1m) < 3 or retest_level <= 0.0:
        return False, 0.0, "Insufficient 1M data"

    n = len(df_1m)
    recent_slice = df_1m.iloc[max(0, n - lookback_candles):]

    zone_top = retest_level * 1.002
    zone_bottom = retest_level * 0.998
    if fvg_zone:
        zone_top = max(zone_top, fvg_zone.get("top", zone_top))
        zone_bottom = min(zone_bottom, fvg_zone.get("bottom", zone_bottom))

    retested = False
    retest_price = 0.0

    for idx in range(len(recent_slice)):
        row = recent_slice.iloc[idx]
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])
        o = float(row["Open"])

        # Check if candle wicks into the zone
        if direction == "BEARISH":
            # For SHORT, price rallies up into zone
            if h >= zone_bottom and l <= zone_top:
                # Rejection confirmation: closes red or with upper wick
                if c < o or (h - max(c, o)) > (max(c, o) - l):
                    retested = True
                    retest_price = c
        elif direction == "BULLISH":
            # For LONG, price dips down into zone
            if l <= zone_top and h >= zone_bottom:
                if c > o or (min(c, o) - l) > (h - min(c, o)):
                    retested = True
                    retest_price = c

    if retested:
        return True, retest_price, "1M Retest and confirmation candle verified"
    return False, 0.0, "No 1M retest confirmation inside zone"
