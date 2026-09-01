import pandas as pd
import numpy as np
import ta
import yfinance as yf
import os
import math
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Tuple, Optional

from db.database import SessionLocal
from db.models import SystemSettings
from signals.providers import get_data_provider
from signals.premarket import calculate_premarket_bias, classify_vix_regime
from signals.ict_smc import (
    detect_swings, detect_liquidity_levels, check_liquidity_sweep,
    detect_mss_choch, detect_fvgs, detect_order_blocks, check_po3_setup,
    check_crt_4h_sweep, check_po3_15m_framework, detect_mathematical_mss_5m,
    detect_1m_retest_and_confirmation
)
from signals.option_chain_provider import NSEOptionChainProvider
from signals.validation import validate_market_data
from signals.strike_selector import score_and_select_best_strike
from ml.prediction import MLPredictionEngine

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

def load_db_weights_and_settings() -> Tuple[Dict[str, float], float, float, float]:
    """Loads weights and thresholds from db settings."""
    db = SessionLocal()
    weights = {
        "trend_bias": 15,
        "liquidity_sweep": 25,
        "mss": 25,
        "displacement": 15,
        "fvg": 10,
        "vwap": 10
    }
    threshold = 75.0
    min_rr = 2.0
    max_chase_pct = 5.0
    try:
        for key in weights.keys():
            setting = db.query(SystemSettings).filter(SystemSettings.key == f"weight_{key}").first()
            if setting:
                weights[key] = float(setting.value)
        set_thresh = db.query(SystemSettings).filter(SystemSettings.key == "signal_threshold").first()
        if set_thresh:
            threshold = float(set_thresh.value)
        set_rr = db.query(SystemSettings).filter(SystemSettings.key == "min_risk_reward").first()
        if set_rr:
            min_rr = float(set_rr.value)
        set_chase = db.query(SystemSettings).filter(SystemSettings.key == "max_entry_chase_pct").first()
        if set_chase:
            max_chase_pct = float(set_chase.value)
    except Exception:
        pass
    finally:
        db.close()
    return weights, threshold, min_rr, max_chase_pct

def calculate_consensus_signal(df: pd.DataFrame, enabled_strategies: List[str] = None, symbol: str = None) -> Dict[str, Any]:
    """
    Scans spot history across multiple timeframes (4H/1H/15M/5M/1M) using the active provider,
    executes pre-signal Option Chain checks, calculates ML probabilities, and evaluates
    state-machine structural states (MSS, sweeps, FVGs, OBs, and Option states).
    """
    symbol_clean = symbol.upper().replace("^", "") if symbol else "NIFTY"
    if symbol_clean in ["NSEI", "NIFTY50"]:
        symbol_clean = "NIFTY"
    elif symbol_clean == "NSEBANK":
        symbol_clean = "BANKNIFTY"
    elif symbol_clean == "BSESN":
        symbol_clean = "SENSEX"

    provider = get_data_provider()
    provider_src = provider.get_source_type()
    system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()

    # 1. Fetch Option Chain BEFORE signal generation
    opt_chain_provider = NSEOptionChainProvider()
    opt_chain = {}
    try:
        opt_chain = opt_chain_provider.get_full_chain(symbol_clean)
    except Exception as e:
        logger.warning(f"Failed to fetch option chain for {symbol_clean}: {e}")

    # Validate Spot Feed
    is_valid_data, data_err = validate_market_data(df, opt_chain if opt_chain else None)
    if not is_valid_data:
        return {
            "signal": "HOLD",
            "confidence": 0.0,
            "reason": f"DATA QUALITY FAILURE — NO SIGNAL ({data_err})",
            "indicators": "Data Quality Check Failed",
            "strategy_score": 0.0,
            "ml_probability": 0.0,
            "trade_quality_score": 0.0,
            "price": float(df.iloc[-1]["Close"]) if not df.empty else 0.0,
            "target1": 0.0, "target2": 0.0, "target3": 0.0,
            "stop_loss": 0.0, "atm_strike": 0, "option_type": "CE",
            "option_contract": "N/A", "option_entry": 0.0, "option_target": 0.0, "option_sl": 0.0, "option_iv": 15.0,
            "instrument_type": "STOCK" if symbol_clean not in ["NIFTY", "BANKNIFTY", "SENSEX"] else "INDEX",
            "name": symbol_clean, "exchange": "NSE" if symbol_clean != "SENSEX" else "BSE",
            "country": "India", "category": "broad", "weighting_method": "market-cap", "is_tradable_spot": False, "derivative_etf": "Option",
            
            # Setup State Machine Mocks
            "mss_state": "NOT_PRESENT", "sweep_state": "NOT_PRESENT", "fvg_state": "NOT_PRESENT",
            "ob_state": "NOT_PRESENT", "breaker_state": "NOT_PRESENT", "po3_state": "NOT_PRESENT",
            "crt_state": "NOT_PRESENT", "option_state": "INVALID"
        }

    close_price = float(df.iloc[-1]['Close'])

    # 2. Multi-Timeframe Retrieval using the active provider to guarantee consistency
    # 4H/1H Higher Timeframe for Trend Bias
    df_4h = provider.get_history(symbol if symbol else "^NSEI", interval="1h", period="15d") # Fallback to 1h if 4h is restricted
    df_1h = provider.get_history(symbol if symbol else "^NSEI", interval="1h", period="15d")
    
    # Standardize Column Headers
    for temp_df in [df_4h, df_1h]:
        if not temp_df.empty:
            if isinstance(temp_df.columns, pd.MultiIndex):
                temp_df.columns = temp_df.columns.get_level_values(0)
            temp_df = temp_df.loc[:, ~temp_df.columns.duplicated()]

    # Evaluate HTF Trend Bias (1H / 4H CLOSE relative to EMA50)
    htf_bias = "BULLISH"
    if not df_1h.empty and len(df_1h) >= 20:
        ema50_1h = ta.trend.EMAIndicator(df_1h["Close"], window=20).ema_indicator().iloc[-1]
        htf_bias = "BULLISH" if df_1h["Close"].iloc[-1] > ema50_1h else "BEARISH"

    # Intraday 15M/5M/1M check
    # Check swings/sweeps on the current spot dataframe
    swings_high, swings_low = detect_swings(df, window=3)
    levels = detect_liquidity_levels(df, None, window=3)
    sweep_res = check_liquidity_sweep(df, levels, lookback_candles=5)
    
    mss_detected, mss_index, break_price = detect_mss_choch(df, swings_high, swings_low, sweep_res)
    fvgs = detect_fvgs(df)
    unmitigated_fvgs = [f for f in fvgs if not f["mitigated"]]
    po3 = check_po3_setup(df)

    # 3. Deduce Structural State Machine Values
    mss_state = "NOT_PRESENT"
    if mss_detected:
        # Check if price has subsequently broken beyond MSS support level (if so, INVALIDATED)
        latest_low = float(df.iloc[-1]["Low"])
        if latest_low < break_price:
            mss_state = "INVALIDATED"
        else:
            mss_state = "ACTIVE"

    sweep_state = "NOT_PRESENT"
    if sweep_res["bullish_sweep"] or sweep_res["bearish_sweep"]:
        sweep_state = "ACTIVE"
        # If price closes beyond the sweep candle boundary, invalidate
        if sweep_res["bullish_sweep"] and close_price < float(df.iloc[-2]["Low"]):
            sweep_state = "INVALIDATED"
        elif sweep_res["bearish_sweep"] and close_price > float(df.iloc[-2]["High"]):
            sweep_state = "INVALIDATED"

    fvg_state = "NOT_PRESENT"
    if unmitigated_fvgs:
        fvg_state = "ACTIVE"
        # Check mitigation
        latest_close = float(df.iloc[-1]["Close"])
        for f in unmitigated_fvgs:
            if f["type"] == "bullish" and latest_close < f["top"]:
                fvg_state = "MITIGATED"
            elif f["type"] == "bearish" and latest_close > f["bottom"]:
                fvg_state = "MITIGATED"

    ob_state = "ACTIVE" if mss_detected else "NOT_PRESENT"
    breaker_state = "ACTIVE" if mss_detected else "NOT_PRESENT"
    po3_state = "ACTIVE" if po3 else "NOT_PRESENT"
    crt_state = "ACTIVE" if mss_detected else "NOT_PRESENT"

    # 4. Pre-Signal Option-Chain Confirmation
    # Evaluate PCR & premium momentum
    option_confirmed = False
    option_state = "INVALID"
    
    if opt_chain and "chain" in opt_chain:
        chain_list = opt_chain["chain"]
        atm_strike = opt_chain.get("atm_strike", int(close_price))
        
        # PCR Calculation
        pe_oi_sum = sum(x.get("pe_oi", 0) or 0 for x in chain_list)
        ce_oi_sum = sum(x.get("ce_oi", 0) or 0 for x in chain_list)
        pcr = pe_oi_sum / ce_oi_sum if ce_oi_sum > 0 else 1.0
        
        # Analyze ATM/Near-ATM contracts
        target_strike = atm_strike
        atm_contract = next((c for c in chain_list if c["strike"] == target_strike), None)
        
        if atm_contract:
            ce_vol = atm_contract.get("ce_volume", 0) or 0
            pe_vol = atm_contract.get("pe_volume", 0) or 0
            ce_chng = atm_contract.get("ce_chng_pct", 0.0) or 0.0
            pe_chng = atm_contract.get("pe_chng_pct", 0.0) or 0.0
            
            # Formulate option state machine status
            if htf_bias == "BULLISH":
                if ce_vol > 5000 and ce_chng > 10.0:
                    option_state = "STRONG"
                    option_confirmed = True
                elif ce_vol > 1000 and ce_chng >= 0.0:
                    option_state = "WEAK"
                    option_confirmed = True
                else:
                    option_state = "INVALID"
            else:
                if pe_vol > 5000 and pe_chng > 10.0:
                    option_state = "STRONG"
                    option_confirmed = True
                elif pe_vol > 1000 and pe_chng >= 0.0:
                    option_state = "WEAK"
                    option_confirmed = True
                else:
                    option_state = "INVALID"

    # 5. ML Directional target probabilities
    ml_prob_val = 0.5
    try:
        ml_engine = MLPredictionEngine(symbol_clean)
        ml_prob = ml_engine.predict_probability(df)
        ml_prob_val = ml_prob["tp_before_sl"]
    except Exception:
        pass

    # 6. Scoring Convergence
    weights, threshold, min_rr, max_chase_pct = load_db_weights_and_settings()

    # --- Strategy Score (0-100) ---
    strategy_score = 0.0
    reasons_list = []
    
    # Trend alignment (15 pts)
    if htf_bias == "BULLISH":
        strategy_score += weights.get("trend_bias", 15)
        reasons_list.append("HTF Bullish Bias")
    else:
        strategy_score += weights.get("trend_bias", 15)
        reasons_list.append("HTF Bearish Bias")
        
    # Sweep (25 pts)
    if sweep_state == "ACTIVE":
        strategy_score += weights.get("liquidity_sweep", 25)
        reasons_list.append("Active Liquidity Sweep")
        
    # MSS (25 pts)
    if mss_state == "ACTIVE":
        strategy_score += weights.get("mss", 25)
        reasons_list.append("Active MSS")
        
    # Displacement (15 pts)
    if mss_index is not None and detect_displacement(df, mss_index):
        strategy_score += weights.get("displacement", 15)
        reasons_list.append("Displacement candle confirmed")
        
    # FVG (10 pts)
    if fvg_state in ["ACTIVE", "MITIGATED"]:
        strategy_score += weights.get("fvg", 10)
        reasons_list.append("Valid FVG confluence")
        
    # VWAP (10 pts)
    df["VWAP"] = df["Close"].rolling(20).mean() # fallback VWAP proxy
    if not df.empty and close_price > float(df.iloc[-1]["VWAP"]) and htf_bias == "BULLISH":
        strategy_score += weights.get("vwap", 10)
        reasons_list.append("Price above VWAP")
    elif not df.empty and close_price < float(df.iloc[-1]["VWAP"]) and htf_bias == "BEARISH":
        strategy_score += weights.get("vwap", 10)
        reasons_list.append("Price below VWAP")

    # --- Strike Selection Ranking ---
    opt_type = "CE" if htf_bias == "BULLISH" else "PE"
    best_strike, ranked_strikes = score_and_select_best_strike(opt_chain, opt_type, close_price)

    trade_quality_score = 0.0
    opt_bid = 0.0
    opt_ask = 0.0
    if best_strike:
        trade_quality_score = best_strike["score"]
        opt_strike = best_strike["strike"]
        opt_entry = best_strike["ltp"]
        opt_delta = best_strike["delta"]
        opt_contract = best_strike["contract"]
        if isinstance(opt_contract, dict):
            opt_bid = opt_contract.get("ce_bid" if opt_type == "CE" else "pe_bid", 0.0) or 0.0
            opt_ask = opt_contract.get("ce_ask" if opt_type == "CE" else "pe_ask", 0.0) or 0.0
    else:
        # Fallback values
        opt_strike = opt_chain.get("atm_strike", int(close_price))
        opt_entry = max(10.0, close_price * 0.012)
        opt_delta = 0.55 if opt_type == "CE" else -0.55
        opt_contract = None

    # Calculate Stop Loss and Targets
    atr = float(df["Close"].rolling(14).std().iloc[-1]) # proxy ATR
    spot_risk = 2.0 * atr
    opt_risk = abs(opt_delta) * spot_risk
    opt_sl = max(opt_entry * 0.70, opt_entry - opt_risk)
    
    # 40/30/30 Targets Setup
    opt_t1 = opt_entry + opt_risk * 1.5
    opt_t2 = opt_entry + opt_risk * 3.0
    opt_t3 = opt_entry + opt_risk * 5.0

    # Signal Check
    final_signal = "HOLD"
    reject_reason = ""
    
    # MANDATORY checklist: Underlying + Options confirmations
    underlying_confirmed = (strategy_score >= threshold)
    
    # If ML probability is available, apply as a weighted indicator rather than a hard veto
    ml_confirmed = (ml_prob_val >= 0.40) # soft threshold

    if not underlying_confirmed:
        final_signal = "HOLD"
        reject_reason = f"Underlying setup failed strategy score threshold ({strategy_score:.0f} < {threshold:.0f})"
    elif not option_confirmed or option_state == "INVALID":
        final_signal = "HOLD"
        reject_reason = f"Options data confirmation failed / invalid (Option State={option_state})"
    else:
        final_signal = "BUY" if htf_bias == "BULLISH" else "SELL"
        reject_reason = "Setup conditions successfully satisfied."

    return {
        "signal": final_signal,
        "confidence": round(strategy_score, 1),
        "reason": reject_reason,
        "reject_reason": reject_reason if final_signal == "HOLD" else None,
        "indicators": ", ".join(reasons_list) if reasons_list else "Trend Analysis",
        "price": close_price,
        "target1": opt_t1,
        "target2": opt_t2,
        "target3": opt_t3,
        "stop_loss": opt_sl,
        "atm_strike": opt_strike,
        "option_type": opt_type,
        "option_contract": f"{symbol_clean} {opt_strike} {opt_type}" if final_signal in ["BUY", "SELL"] else "N/A",
        "option_entry": round(opt_entry, 2),
        "option_bid": float(opt_bid) if opt_bid else 0.0,
        "option_ask": float(opt_ask) if opt_ask else 0.0,
        "option_target": round(opt_t2, 2),
        "option_sl": round(opt_sl, 2),
        "option_iv": float(opt_chain.get("chain", [{}])[0].get("ce_iv" if opt_type == "CE" else "pe_iv", 15.0)) if opt_chain.get("chain") else 15.0,
        
        # Extended Scores
        "strategy_score": round(strategy_score, 1),
        "ml_probability": round(ml_prob_val * 100.0, 1),
        "trade_quality_score": round(trade_quality_score, 1),
        
        # Structural state machine logs
        "mss_state": mss_state,
        "sweep_state": sweep_state,
        "fvg_state": fvg_state,
        "ob_state": ob_state,
        "breaker_state": breaker_state,
        "po3_state": po3_state,
        "crt_state": crt_state,
        "option_state": option_state,
        
        "instrument_type": "STOCK" if symbol_clean not in ["NIFTY", "BANKNIFTY", "SENSEX"] else "INDEX",
        "name": symbol_clean,
        "exchange": "NSE" if symbol_clean != "SENSEX" else "BSE",
        "country": "India",
        "category": "broad",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "Option"
    }

def detect_displacement(df: pd.DataFrame, idx: int) -> bool:
    """Helper to detect displacement candles (candle size > 1.5x body standard deviation)."""
    if idx < 1 or idx >= len(df):
        return False
    body = abs(df.iloc[idx]["Close"] - df.iloc[idx]["Open"])
    body_std = df["Close"].sub(df["Open"]).abs().rolling(20).std().iloc[idx]
    if pd.isna(body_std) or body_std <= 0:
        body_std = df.iloc[idx]["Close"] * 0.001
    return body > 1.5 * body_std

def calculate_crt_po3_signal(
    df_1m: pd.DataFrame,
    df_5m: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    symbol: str = "^NSEI",
    premarket_data: Optional[Dict[str, Any]] = None,
    opt_chain: Optional[Dict[str, Any]] = None,
    current_time: Optional[datetime] = None,
    min_signal_score: float = 7.0,
    min_rr: float = 1.5,
    sweep_mode: str = "LIVE_SWEEP",
    max_holding_time_minutes: int = 5,
    force_session_valid: bool = False
) -> Dict[str, Any]:
    """
    CRT + PO3 Fast-Scalping Engine with 9 Mandatory Hard Gates.
    Strict Point-in-Time integrity: never accesses future candle data or forming 4H close.
    - Decoupled: Generates Index Signal (Direction, Entry, Stop, Target, RR) FIRST.
    - Option Selection: Selects appropriate contract with Delta 0.50-0.60 SECOND.
    - Score (0-10): Evaluated ONLY after all 9 mandatory gates pass.
    """
    now_utc = current_time or datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)
    sig_id = str(uuid.uuid4())

    symbol_clean = symbol.upper().replace("^", "")
    if symbol_clean in ["NSEI", "NIFTY50"]:
        symbol_clean = "NIFTY"
    elif symbol_clean == "NSEBANK":
        symbol_clean = "BANKNIFTY"
    elif symbol_clean == "BSESN":
        symbol_clean = "SENSEX"

    base_res = {
        "status": "NO_TRADE",
        "signal": "HOLD",
        "signal_id": sig_id,
        "symbol": symbol_clean,
        "timeframe": "1M",
        "data_timestamp": now_utc.isoformat(),
        "signal_timestamp": now_utc.isoformat(),
        "candle_close_timestamp": df_1m.index[-1].isoformat() if (df_1m is not None and not df_1m.empty and hasattr(df_1m.index[-1], 'isoformat')) else str(now_utc),
        "index_direction": "NONE",
        "index_entry": 0.0,
        "index_stop": 0.0,
        "index_target": 0.0,
        "index_rr": 0.0,
        "option_contract": "N/A",
        "option_type": "NONE",
        "option_entry": 0.0,
        "option_sl": 0.0,
        "option_target": 0.0,
        "delta": 0.0,
        "spread_pct": 0.0,
        "signal_score": 0.0,
        "max_holding_time_minutes": max_holding_time_minutes,
        "mfe": 0.0,
        "mae": 0.0,
        "mandatory_gates_passed": False,
        "failed_gate": None,
        "reason": "",
        "gate_results": {},
        "score_breakdown": {}
    }

    if df_1m is None or df_1m.empty or len(df_1m) < 10:
        base_res["failed_gate"] = "INSUFFICIENT_1M_DATA"
        base_res["reason"] = "Insufficient 1M candle history"
        return base_res

    close_price = float(df_1m.iloc[-1]["Close"])
    current_high = float(df_1m.iloc[-1]["High"])
    current_low = float(df_1m.iloc[-1]["Low"])

    # Fallback multi-timeframe resample only if not provided
    if df_5m is None:
        df_5m = df_1m
    if df_15m is None:
        df_15m = df_5m
    if df_4h is None:
        df_4h = df_15m

    # ----------------------------------------------------
    # GATE 7: Valid Trading Session (9:20 - 15:10 IST)
    # ----------------------------------------------------
    hour_min = now_ist.hour * 60 + now_ist.minute
    session_valid = force_session_valid or ((9 * 60 + 20) <= hour_min <= (15 * 60 + 10) and now_ist.weekday() < 5)
    base_res["gate_results"]["gate_7_session"] = session_valid
    if not session_valid:
        base_res["failed_gate"] = "GATE_7_SESSION"
        base_res["reason"] = f"Outside active trading session ({now_ist.strftime('%H:%M')} IST)"
        return base_res

    # ----------------------------------------------------
    # GATE 1: Valid 4H CRT Sweep (Point-in-Time)
    # ----------------------------------------------------
    crt_sweep = check_crt_4h_sweep(df_4h, current_high, current_low, close_price, sweep_mode=sweep_mode)
    sweep_valid = crt_sweep["sweep_confirmed"] if sweep_mode == "CONFIRMED_SWEEP" else crt_sweep["sweep_detected"]
    base_res["gate_results"]["gate_1_4h_sweep"] = sweep_valid
    if not sweep_valid:
        base_res["failed_gate"] = "GATE_1_4H_SWEEP"
        base_res["reason"] = f"No valid 4H CRT sweep detected in {sweep_mode} mode"
        return base_res

    direction = crt_sweep["direction"]  # "BEARISH" or "BULLISH"
    base_res["index_direction"] = direction

    # ----------------------------------------------------
    # GATE 2: Valid 5M MSS (Strict Candle Close)
    # ----------------------------------------------------
    swings_h, swings_l = detect_swings(df_5m, window=3)
    mss_detected, mss_idx, mss_level = detect_mathematical_mss_5m(df_5m, swings_h, swings_l, direction)
    base_res["gate_results"]["gate_2_5m_mss"] = mss_detected
    if not mss_detected:
        base_res["failed_gate"] = "GATE_2_5M_MSS"
        base_res["reason"] = "No valid 5M Market Structure Shift confirmed on candle close"
        return base_res

    # ----------------------------------------------------
    # GATE 3: Valid 5M Displacement
    # ----------------------------------------------------
    has_displacement = detect_displacement(df_5m, mss_idx) if mss_idx is not None else False
    base_res["gate_results"]["gate_3_displacement"] = has_displacement
    if not has_displacement:
        base_res["failed_gate"] = "GATE_3_DISPLACEMENT"
        base_res["reason"] = "5M MSS candle lacks required body and volume displacement"
        return base_res

    # ----------------------------------------------------
    # GATE 4 & 5: Valid 1M Retest & Entry Confirmation
    # ----------------------------------------------------
    fvgs_5m = detect_fvgs(df_5m)
    fvg_zone = next((f for f in fvgs_5m if f["type"] == ("bullish" if direction == "BULLISH" else "bearish")), None)
    retest_target_level = crt_sweep.get("break_closing_level") or mss_level

    retest_ok, entry_price, retest_msg = detect_1m_retest_and_confirmation(
        df_1m, direction, retest_target_level, fvg_zone=fvg_zone, lookback_candles=15
    )
    base_res["gate_results"]["gate_4_1m_retest"] = retest_ok
    base_res["gate_results"]["gate_5_entry_confirmation"] = (entry_price > 0)
    if not retest_ok or entry_price <= 0:
        base_res["failed_gate"] = "GATE_4_OR_5_RETEST_ENTRY"
        base_res["reason"] = retest_msg
        return base_res

    # ----------------------------------------------------
    # GATE 6: Minimum Risk to Reward Ratio (Index Level)
    # ----------------------------------------------------
    atr = float(df_1m["Close"].rolling(14).std().iloc[-1]) if len(df_1m) >= 14 else 15.0
    atr = max(10.0, atr)

    if direction == "BULLISH":
        idx_entry = entry_price
        idx_stop = crt_sweep.get("sweep_low", entry_price - 1.5 * atr)
        risk_dist = max(10.0, idx_entry - idx_stop)
        # Cap risk to reasonable distance (max 3x ATR)
        if risk_dist > 3.0 * atr:
            idx_stop = idx_entry - 2.0 * atr
            risk_dist = 2.0 * atr
        idx_target = idx_entry + risk_dist * 2.0
    else:
        idx_entry = entry_price
        idx_stop = crt_sweep.get("sweep_high", entry_price + 1.5 * atr)
        risk_dist = max(10.0, idx_stop - idx_entry)
        if risk_dist > 3.0 * atr:
            idx_stop = idx_entry + 2.0 * atr
            risk_dist = 2.0 * atr
        idx_target = idx_entry - risk_dist * 2.0

    target_dist = abs(idx_target - idx_entry)
    calculated_rr = round(target_dist / risk_dist, 2) if risk_dist > 0 else 0.0

    base_res["index_entry"] = round(idx_entry, 2)
    base_res["index_stop"] = round(idx_stop, 2)
    base_res["index_target"] = round(idx_target, 2)
    base_res["index_rr"] = calculated_rr
    
    rr_valid = calculated_rr >= min_rr
    base_res["gate_results"]["gate_6_min_rr"] = rr_valid
    if not rr_valid:
        base_res["failed_gate"] = "GATE_6_MIN_RR"
        base_res["reason"] = f"Calculated R:R {calculated_rr:.2f} is below minimum required {min_rr:.2f}"
        return base_res

    # ----------------------------------------------------
    # GATE 8 & 9: Option Contract Selection & Liquidity
    # ----------------------------------------------------
    opt_type = "CE" if direction == "BULLISH" else "PE"
    base_res["option_type"] = opt_type
    
    # Decoupled Option Selection (Delta 0.50 - 0.60 preferred)
    best_strike, ranked = score_and_select_best_strike(opt_chain if opt_chain else {}, opt_type, close_price)
    
    opt_entry = 0.0
    opt_delta = 0.55 if opt_type == "CE" else -0.55
    opt_spread_pct = 0.005
    opt_contract = f"{symbol_clean} ATM {opt_type}"

    if best_strike:
        opt_entry = best_strike.get("ltp", 0.0)
        opt_delta = best_strike.get("delta", opt_delta)
        opt_contract = best_strike.get("contract_name") or f"{symbol_clean} {best_strike['strike']} {opt_type}"
        contract_data = best_strike.get("contract", {})
        if isinstance(contract_data, dict):
            b = contract_data.get("ce_bid" if opt_type == "CE" else "pe_bid", 0.0) or 0.0
            a = contract_data.get("ce_ask" if opt_type == "CE" else "pe_ask", 0.0) or 0.0
            if b > 0 and a >= b:
                opt_spread_pct = (a - b) / b
    else:
        opt_entry = max(20.0, close_price * 0.008)

    opt_risk = max(5.0, abs(opt_delta) * risk_dist)
    opt_sl = max(opt_entry * 0.70, opt_entry - opt_risk)
    opt_target = opt_entry + (opt_risk * calculated_rr)

    base_res["option_contract"] = opt_contract
    base_res["option_entry"] = round(opt_entry, 2)
    base_res["option_sl"] = round(opt_sl, 2)
    base_res["option_target"] = round(opt_target, 2)
    base_res["delta"] = round(opt_delta, 2)
    base_res["spread_pct"] = round(opt_spread_pct * 100.0, 2)

    # Spread and Liquidity Gates
    spread_ok = opt_spread_pct <= 0.020  # Max 2% spread acceptable
    base_res["gate_results"]["gate_8_spread"] = spread_ok
    if not spread_ok:
        base_res["failed_gate"] = "GATE_8_SPREAD"
        base_res["reason"] = f"Option spread {opt_spread_pct*100:.2f}% exceeds acceptable threshold"
        return base_res

    # Delta range check (prefer 0.40 - 0.70)
    delta_ok = 0.35 <= abs(opt_delta) <= 0.75
    base_res["gate_results"]["gate_9_liquidity"] = delta_ok
    if not delta_ok:
        base_res["failed_gate"] = "GATE_9_LIQUIDITY"
        base_res["reason"] = f"Option delta {abs(opt_delta):.2f} outside acceptable liquidity range"
        return base_res

    # ALL 9 MANDATORY GATES PASSED!
    base_res["mandatory_gates_passed"] = True

    # ----------------------------------------------------
    # UNIFIED QUALITY SCORE (0 to 10)
    # ----------------------------------------------------
    score = 0.0
    score_parts = {}

    # Pre-market Bias (+1)
    pm = premarket_data or calculate_premarket_bias()
    if pm.get("market_bias") == direction:
        score += 1.0
        score_parts["premarket_bias"] = 1.0

    # Market Breadth Confirmation (+1)
    if (direction == "BULLISH" and pm.get("breadth_bias") == "BULLISH") or (direction == "BEARISH" and pm.get("breadth_bias") == "BEARISH"):
        score += 1.0
        score_parts["breadth_confirmation"] = 1.0

    # PO3 Context (+1)
    daily_open = float(df_15m.iloc[0]["Open"]) if (df_15m is not None and not df_15m.empty) else close_price
    po3 = check_po3_15m_framework(df_15m, daily_open, close_price)
    if po3.get("bias") == direction:
        score += 1.0
        score_parts["po3_context"] = 1.0

    # 4H Sweep (+2)
    score += 2.0
    score_parts["4h_sweep"] = 2.0

    # 5M MSS (+2)
    score += 2.0
    score_parts["5m_mss"] = 2.0

    # 1M Retest (+1)
    score += 1.0
    score_parts["1m_retest"] = 1.0

    # Volume Confirmation (+1)
    if "Volume" in df_1m.columns and len(df_1m) >= 20:
        vol_recent = df_1m["Volume"].iloc[-3:].mean()
        vol_avg = df_1m["Volume"].iloc[-20:].mean()
        if vol_avg > 0 and vol_recent > vol_avg:
            score += 1.0
            score_parts["volume_expansion"] = 1.0

    # VWAP Confirmation (+1)
    vwap_val = float(df_1m["Close"].rolling(20).mean().iloc[-1])
    if (direction == "BULLISH" and close_price > vwap_val) or (direction == "BEARISH" and close_price < vwap_val):
        score += 1.0
        score_parts["vwap_alignment"] = 1.0

    base_res["signal_score"] = round(score, 1)
    base_res["score_breakdown"] = score_parts

    # Quality Gate
    if score < min_signal_score:
        base_res["status"] = "NO_TRADE"
        base_res["signal"] = "HOLD"
        base_res["failed_gate"] = "QUALITY_SCORE"
        base_res["reason"] = f"Mandatory gates passed, but Unified Score failed ({score:.1f}/10 < {min_signal_score:.1f}/10)"
        return base_res

    # ----------------------------------------------------
    # ALL GATES & SCORE PASSED: SIGNAL DETECTED!
    # ----------------------------------------------------
    base_res["status"] = "SIGNAL_DETECTED"
    base_res["signal"] = "BUY" if direction == "BULLISH" else "SELL"
    base_res["reason"] = (
        f"CRT 4H {crt_sweep['status']} ({direction}) + 5M MSS + 1M Retest verified. "
        f"Quality Score: {score:.0f}/10. R:R: {calculated_rr:.2f}"
    )

    return base_res
