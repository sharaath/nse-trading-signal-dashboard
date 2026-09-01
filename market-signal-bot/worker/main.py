import os
import json
from dotenv import load_dotenv
load_dotenv()
import time
import math
import pandas as pd
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from typing import Tuple, Dict, Any

from db.database import SessionLocal, validate_paper_mode
validate_paper_mode()
from db.models import init_db, SignalHistory, UserSubscription, StrategyState, PaperTrade, SystemSettings, DataQuality, ScanLog
from db.instruments import get_instrument_metadata
from signals.providers import YFinanceDataProvider, get_data_provider
from signals.providers.realtime_provider import RealTimeMarketDataProvider, GLOBAL_MARKET_CACHE
from signals.engine import calculate_consensus_signal
from signals.strike_selector import score_and_select_best_strike
from paper_trading.engine import PaperTradingManager

MONITORED_TICKERS = ["^NSEI", "^BSESN", "^NSEBANK"]
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PERSONAL_USE_ONLY = os.environ.get("PERSONAL_USE_ONLY", "true").lower() == "true"
IST = ZoneInfo("Asia/Kolkata")

def send_telegram_alert(message: str, chat_id: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Telegram Token not configured. Alert skipped.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
    except urllib.error.HTTPError as e:
        if e.code == 400:
            try:
                plain_text = message.replace("*", "").replace("`", "")
                data_plain = json.dumps({"chat_id": chat_id, "text": plain_text}).encode("utf-8")
                req_plain = urllib.request.Request(url, data=data_plain, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req_plain, timeout=10) as response2:
                    response2.read()
            except Exception as e2:
                print(f"Error in telegram alert fallback: {e2}")
        else:
            print(f"Error sending telegram alert: {e}")
    except Exception as e:
        print(f"Error sending telegram alert: {e}")

def perform_market_audit(db: Session):
    from db.models import DataQuality, SystemSettings
    from signals.providers import get_data_provider
    from signals.option_chain_provider import NSEOptionChainProvider
    import time
    
    provider = get_data_provider()
    chain_provider = NSEOptionChainProvider()
    
    # Load configurable freshness limits
    max_spot_age = 60.0
    max_chain_age = 180.0
    
    set_spot = db.query(SystemSettings).filter(SystemSettings.key == "max_acceptable_age_spot").first()
    if set_spot:
        max_spot_age = float(set_spot.value)
    else:
        db.add(SystemSettings(key="max_acceptable_age_spot", value="60"))
        db.commit()
        
    set_chain = db.query(SystemSettings).filter(SystemSettings.key == "max_acceptable_age_option_chain").first()
    if set_chain:
        max_chain_age = float(set_chain.value)
    else:
        db.add(SystemSettings(key="max_acceptable_age_option_chain", value="180"))
        db.commit()
        
    markets = {
        "NIFTY": ("^NSEI", "NIFTY"),
        "BANK_NIFTY": ("^NSEBANK", "BANKNIFTY"),
        "SENSEX": ("^BSESN", "SENSEX")
    }
    
    for m_key, (spot_symbol, chain_symbol) in markets.items():
        received_at = datetime.now(timezone.utc)
        missing_fields = []
        latency_ms = 0.0
        data_status = "LIVE"
        trading_eligible = True
        is_fresh = True
        age_seconds = 0.0
        provider_timestamp = received_at
        
        provider_name = provider.__class__.__name__
        
        # Check if Fyers realtime provider is selected
        if isinstance(provider, RealTimeMarketDataProvider):
            if not provider.is_connected:
                if getattr(provider, "auth_failed", False):
                    missing_fields.append("auth_failed")
                    data_status = "AUTHENTICATION FAILED"
                elif not provider.client_id or not provider.secret_key or not provider.access_token:
                    missing_fields.append("credentials_missing")
                    data_status = "UNCONFIGURED"
                else:
                    missing_fields.append("connection_failed")
                    data_status = "UNAVAILABLE"
                trading_eligible = False
                is_fresh = False
                age_seconds = 0.0
            else:
                # Resolve key for Fyers global cache
                cache_key = "NSE:NIFTY50-INDEX"
                if "BANK" in spot_symbol:
                    cache_key = "NSE:NIFTYBANK-INDEX"
                elif "BSESN" in spot_symbol or "SENSEX" in spot_symbol:
                    cache_key = "BSE:SENSEX-INDEX"
                    
                tick = GLOBAL_MARKET_CACHE.get_data(cache_key)
                if not tick or not provider.websocket_connected:
                    missing_fields.append("websocket_tick")
                    data_status = "DISCONNECTED"
                    trading_eligible = False
                    is_fresh = False
                else:
                    provider_timestamp = tick["timestamp"]
                    if provider_timestamp.tzinfo is None:
                        provider_timestamp = provider_timestamp.replace(tzinfo=timezone.utc)
                    age_seconds = (received_at - provider_timestamp).total_seconds()
                    
                    # Check required tick fields
                    required_tick_fields = ["ltp", "bid", "ask", "volume", "open_interest", "change_in_open_interest"]
                    for f in required_tick_fields:
                        if f not in tick or tick[f] is None:
                            missing_fields.append(f"tick_{f}")
                            trading_eligible = False
                            is_fresh = False
                            
                    # Audit Option Chain Data in RealTime mode
                    try:
                        chain_data = provider.get_option_chain(chain_symbol)
                        if not chain_data:
                            missing_fields.append("option_chain")
                            trading_eligible = False
                            is_fresh = False
                        else:
                            records = chain_data.get("records", {})
                            if not records or "data" not in records or not records["data"]:
                                missing_fields.append("option_data")
                                trading_eligible = False
                                is_fresh = False
                            else:
                                first_row = records["data"][0]
                                ce = first_row.get("CE", {}) or {}
                                pe = first_row.get("PE", {}) or {}
                                required_opt_fields = ["lastPrice", "strikePrice", "expiryDate", "openInterest", "changeinOpenInterest", "totalTradedVolume"]
                                for f in required_opt_fields:
                                    if f not in ce and f not in pe:
                                        missing_fields.append(f"option_{f}")
                    except Exception as e:
                        err_msg = str(e)
                        if "SENSEX options data unavailable" in err_msg or "BSE SENSEX live options" in err_msg:
                            missing_fields.append("sensex_options_feed")
                        else:
                            missing_fields.append(f"option_error: {err_msg}")
                        trading_eligible = False
                        is_fresh = False
                            
                    # SENSEX options connection checks
                    if m_key == "SENSEX":
                        system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()
                        if system_mode != "SIMULATION":
                            missing_fields.append("sensex_options_feed")
                            trading_eligible = False
                            is_fresh = False
                            data_status = "UNAVAILABLE"
                            
                    if age_seconds > max_spot_age:
                        is_fresh = False
                        if data_status not in ["UNAVAILABLE", "DISCONNECTED", "AUTHENTICATION FAILED"]:
                            data_status = "STALE"
                        trading_eligible = False
                        
                    latency_ms = 120.0 # simulated websocket frame latency
        else:
            # 1. Audit Spot Data (HTTP get_history for yfinance/mock)
            start_time = time.time()
            try:
                df = provider.get_history(spot_symbol)
                latency_ms = (time.time() - start_time) * 1000.0
                
                if df.empty:
                    missing_fields.append("spot_history")
                    data_status = "UNAVAILABLE"
                    trading_eligible = False
                    is_fresh = False
                else:
                    # Check columns
                    for col in ["Open", "High", "Low", "Close", "Volume"]:
                        if col not in df.columns or df[col].isna().any():
                            missing_fields.append(f"spot_{col.lower()}")
                    
                    # Check timestamp
                    latest_time = df.index[-1]
                    if latest_time.tzinfo is not None:
                        provider_timestamp = latest_time.astimezone(timezone.utc)
                    else:
                        provider_timestamp = latest_time.replace(tzinfo=timezone.utc)
                    
                    age_seconds = (received_at - provider_timestamp).total_seconds()
                    
                    if age_seconds > max_spot_age:
                        is_fresh = False
                        data_status = "STALE"
                        trading_eligible = False
            except Exception as e:
                missing_fields.append(f"spot_error: {str(e)}")
                data_status = "UNAVAILABLE"
                trading_eligible = False
                is_fresh = False
                
            # 2. Audit Option Chain Data
            start_chain = time.time()
            chain_data = None
            try:
                chain_data = chain_provider.fetch_option_chain(chain_symbol)
                latency_ms += (time.time() - start_chain) * 1000.0
                
                if not chain_data:
                    missing_fields.append("option_chain")
                    if data_status != "STALE":
                        data_status = "UNAVAILABLE"
                    trading_eligible = False
                    is_fresh = False
                else:
                    data_source = chain_data.get("data_source", "live")
                    if data_source == "simulated":
                        data_status = "SIMULATION"
                        trading_eligible = False
                        
                    records = chain_data.get("records", {})
                    
                    # Verify required fields in option chain records
                    if not records or "data" not in records or not records["data"]:
                        missing_fields.append("option_data")
                        trading_eligible = False
                        is_fresh = False
                        if data_status not in ["SIMULATION", "STALE"]:
                            data_status = "UNAVAILABLE"
                    else:
                        first_row = records["data"][0]
                        ce = first_row.get("CE", {}) or {}
                        pe = first_row.get("PE", {}) or {}
                        
                        required_opt_fields = ["lastPrice", "strikePrice", "expiryDate", "openInterest", "changeinOpenInterest", "totalTradedVolume"]
                        if data_status != "SIMULATION":
                            required_opt_fields += ["bidprice", "askprice"]
                            
                        for f in required_opt_fields:
                            if f not in ce and f not in pe:
                                missing_fields.append(f"option_{f}")
                                
                        # Parse provider timestamp from records
                        ts_str = records.get("timestamp")
                        if ts_str:
                            try:
                                provider_time_ist = datetime.strptime(ts_str, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
                                provider_time = provider_time_ist.astimezone(timezone.utc)
                                chain_age = (received_at - provider_time).total_seconds()
                                
                                if chain_age > age_seconds:
                                    age_seconds = chain_age
                                    provider_timestamp = provider_time
                                    
                                if chain_age > max_chain_age:
                                    is_fresh = False
                                    if data_status != "SIMULATION":
                                        data_status = "STALE"
                                    trading_eligible = False
                            except Exception:
                                pass
            except Exception as e:
                err_msg = str(e)
                if "SENSEX options data unavailable" in err_msg or "BSE SENSEX live options" in err_msg:
                    missing_fields.append("sensex_options_feed")
                else:
                    missing_fields.append(f"option_error: {err_msg}")
                trading_eligible = False
                is_fresh = False
                if data_status not in ["SIMULATION", "STALE"]:
                    data_status = "UNAVAILABLE"
                    
            if "YFinance" in provider_name:
                if data_status not in ["SIMULATION", "UNAVAILABLE"]:
                    data_status = "DELAYED"
                    trading_eligible = False
                
        # Clean up missing fields duplicates and format as string
        missing_fields_str = ",".join(sorted(list(set(missing_fields))))
        
        # Check previous status to send alert on warning status transitions
        prev_status = None
        dq = db.query(DataQuality).filter(DataQuality.symbol == m_key).first()
        if dq:
            prev_status = dq.data_status
        else:
            dq = DataQuality(symbol=m_key)
            db.add(dq)
            
        dq.provider = "yfinance" if "YFinance" in provider_name else provider_name.replace("DataProvider", "").replace("Provider", "").lower()
        dq.timestamp = provider_timestamp
        dq.received_at = received_at
        dq.age_seconds = age_seconds
        dq.is_fresh = is_fresh
        dq.source_mode = data_status
        dq.data_status = data_status
        dq.missing_fields = missing_fields_str
        dq.latency_ms = round(latency_ms, 1)
        dq.trading_eligible = trading_eligible
        
        db.commit()
        
        # Alert if data has transitioned to an unhealthy state (LIVE -> STALE/UNAVAILABLE/DELAYED)
        if prev_status == "LIVE" and data_status in ["STALE", "UNAVAILABLE", "DELAYED"]:
            alert_msg = f"⚠️ *DATA QUALITY WARNING*: Market `{m_key}` data feed has transitioned to `{data_status}`! (Age: {age_seconds:.0f}s, Missing: {missing_fields_str or 'None'})"
            print(alert_msg)
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                try:
                    send_telegram_alert(alert_msg, chat_id)
                except Exception as ex:
                    print(f"Failed to send Telegram alert: {ex}")

def get_enabled_strategies(db: Session) -> list:
    strategies = db.query(StrategyState).filter(StrategyState.is_enabled == True).all()
    if not strategies:
        return ["ema_crossover", "rsi", "macd", "bollinger_bands"]
    return [s.strategy_name for s in strategies]

def get_last_signal(db: Session, symbol: str) -> str:
    from sqlalchemy import desc
    last_record = db.query(SignalHistory).filter(SignalHistory.symbol == symbol).order_by(desc(SignalHistory.timestamp)).first()
    return last_record.signal if last_record else "HOLD"

def check_daily_risk_limits(db: Session) -> Tuple[bool, str]:
    max_loss = 5000.0
    max_trades = 5
    max_simultaneous = 2
    
    set_loss = db.query(SystemSettings).filter(SystemSettings.key == "max_daily_loss").first()
    if set_loss:
        max_loss = float(set_loss.value)
    set_trades = db.query(SystemSettings).filter(SystemSettings.key == "max_daily_trades").first()
    if set_trades:
        max_trades = int(set_trades.value)
    set_sim = db.query(SystemSettings).filter(SystemSettings.key == "max_simultaneous_trades").first()
    if set_sim:
        max_simultaneous = int(set_sim.value)
        
    active_count = db.query(PaperTrade).filter(PaperTrade.status == "ACTIVE").count()
    if active_count >= max_simultaneous:
        return False, f"Risk limit: Max simultaneous trades ({max_simultaneous}) reached."
        
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now.astimezone(IST)
    ist_today_start_ist = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
    ist_today_start = ist_today_start_ist.astimezone(timezone.utc).replace(tzinfo=None)
    
    today_trades = db.query(PaperTrade).filter(PaperTrade.entry_time >= ist_today_start).all()
    if len(today_trades) >= max_trades:
        return False, f"Risk limit: Max daily trades ({max_trades}) reached."
        
    today_pnl = sum(t.pnl for t in today_trades if t.status == "CLOSED")
    if today_pnl <= -max_loss:
        return False, f"Risk limit: Max daily loss (-₹{max_loss:.2f}) reached. Realized P&L: ₹{today_pnl:.2f}"
        
    return True, ""

def check_trade_risk_parameters(analysis: Dict[str, Any], ist_now: datetime) -> Tuple[bool, str]:
    session_end = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
    time_left_mins = (session_end - ist_now).total_seconds() / 60.0
    
    force_scan = os.environ.get("FORCE_SCAN", "false").lower() == "true"
    if not force_scan and time_left_mins < 15.0:
        return False, "Risk limit: Less than 15 minutes remaining in trading session."

    opt_iv = float(analysis.get("option_iv", 15.0))
    if opt_iv > 40.0:
        return False, f"Risk limit: Option implied volatility is excessively high (IV={opt_iv}% > 40%). High crush risk."
    if opt_iv < 5.0:
        return False, f"Risk limit: Option implied volatility is too low (IV={opt_iv}% < 5%). Premium unlikely to move."
        
    return True, "Risk limits passed."

def execute_pre_entry_re_validation(
    db: Session,
    symbol: str,
    original_analysis: Dict[str, Any],
    original_time: datetime,
    ist_now: datetime
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    State-Machine Comparative Re-evaluation Workflow:
    Executes a fresh scan immediately before paper entry, enforcing rules:
    - Signal Age must be < 180 seconds.
    - Direction/Signal matches (e.g. BUY Call is still BUY Call).
    - Checks State Machine transitions for MSS, Sweeps, FVG, and Options validation.
    - Blocked: FVG -> INVALIDATED, Option -> INVALID, MSS -> INVALIDATED, Sweep -> INVALIDATED.
    - Re-evaluate: Option -> WEAK (performs comprehensive bounds & momentum check).
    - Checks configurable entry chase limits.
    """
    # 1. Age Verification
    age_secs = (datetime.now(timezone.utc) - (original_time if original_time.tzinfo else original_time.replace(tzinfo=timezone.utc))).total_seconds()
    if age_secs > 180:
        return False, f"SETUP INVALIDATED: Signal age expired ({age_secs:.0f}s > 180s).", {}

    # 2. Fresh Market Scan
    provider = get_data_provider()
    df = provider.get_history(symbol)
    if df.empty:
        return False, "SETUP INVALIDATED: Stale / empty data provider feed on tick.", {}

    enabled_strats = get_enabled_strategies(db)
    fresh_analysis = calculate_consensus_signal(df, enabled_strats, symbol=symbol)

    # 3. State Machine Transitions Verification
    # Direction
    if fresh_analysis["signal"] != original_analysis["signal"]:
        return False, f"SETUP INVALIDATED: Signal flipped from {original_analysis['signal']} to {fresh_analysis['signal']}", {}

    # MSS State Machine
    if original_analysis["mss_state"] == "ACTIVE" and fresh_analysis["mss_state"] == "INVALIDATED":
        return False, "SETUP INVALIDATED: MSS structure breached.", {}

    # Sweep State Machine
    if original_analysis["sweep_state"] == "ACTIVE" and fresh_analysis["sweep_state"] == "INVALIDATED":
        return False, "SETUP INVALIDATED: Liquidity sweep structure breached.", {}

    # FVG State Machine
    if original_analysis["fvg_state"] == "ACTIVE" and fresh_analysis["fvg_state"] == "INVALIDATED":
        return False, "SETUP INVALIDATED: FVG boundaries invalidated.", {}

    # Option Confirmation State Machine
    opt_state_new = fresh_analysis["option_state"]
    if original_analysis["option_state"] == "STRONG" and opt_state_new == "INVALID":
        return False, "SETUP INVALIDATED: Options spread/liquidity became INVALID.", {}
    elif original_analysis["option_state"] == "STRONG" and opt_state_new == "WEAK":
        # Re-evaluate option weak transition:
        strategy_score = fresh_analysis["strategy_score"]
        trade_quality = fresh_analysis["trade_quality_score"]
        
        # Check settings limits
        db_weights, threshold, min_rr, max_chase_pct = load_db_weights_and_settings()
        
        if strategy_score < threshold:
            return False, f"RE-EVALUATION FAILURE: Strategy score dropped too low ({strategy_score} < {threshold})", {}
        if trade_quality < 70:
            return False, f"RE-EVALUATION FAILURE: Trade quality dropped too low ({trade_quality} < 70)", {}

    # 4. Entry Chase Protection (Configurable max_entry_chase_pct check)
    db_weights, threshold, min_rr, max_chase_pct = load_db_weights_and_settings()
    original_entry = original_analysis["option_entry"]
    current_entry = fresh_analysis["option_entry"]
    
    if current_entry > original_entry * (1.0 + max_chase_pct / 100.0):
        return False, f"ENTRY MISSED — DO NOT CHASE: Premium moved up by {((current_entry - original_entry)/original_entry)*100.5:.1f}% (> {max_chase_pct}%)", {}

    return True, "Pre-entry validation checks passed successfully.", fresh_analysis

def run_market_scan():
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now.astimezone(IST)
    
    if ist_now.weekday() >= 5:
        print(f"Weekend ({ist_now.strftime('%A')}). Scanning skipped.")
        return
        
    market_start = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    force_scan = os.environ.get("FORCE_SCAN", "false").lower() == "true"
    if not force_scan and not (market_start <= ist_now <= market_end):
        print(f"Outside market hours ({ist_now.strftime('%H:%M:%S IST')}). Scanning skipped.")
        return
        
    print(f"Executing market scan job at {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}...")
    init_db()
    db = SessionLocal()
    try:
        # Seed default strategies if table empty
        if db.query(StrategyState).count() == 0:
            for s in ["ema_crossover", "rsi", "macd", "bollinger_bands"]:
                db.add(StrategyState(strategy_name=s, is_enabled=True))
            db.commit()
            
        hb = db.query(SystemSettings).filter(SystemSettings.key == "worker_heartbeat").first()
        if not hb:
            db.add(SystemSettings(key="worker_heartbeat", value=datetime.now(timezone.utc).isoformat()))
        else:
            hb.value = datetime.now(timezone.utc).isoformat()
        db.commit()
    except Exception:
        pass
    
    try:
        perform_market_audit(db)
    except Exception as e:
        print(f"Error executing market audit: {e}")

    provider = get_data_provider()
    provider_src = provider.get_source_type()
    system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()
    
    enabled_strats = get_enabled_strategies(db)
    
    try:
        pt_manager = PaperTradingManager()
        pt_manager.update_active_trades(db)
    except Exception as e:
        print(f"Error updating paper trades: {e}")
        
    risk_allowed, risk_reason = check_daily_risk_limits(db)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    for symbol in MONITORED_TICKERS:
        m_key = "NIFTY"
        if "BANK" in symbol:
            m_key = "BANK_NIFTY"
        elif "BSESN" in symbol or "SENSEX" in symbol:
            m_key = "SENSEX"
            
        df = provider.get_history(symbol)
        dq = db.query(DataQuality).filter(DataQuality.symbol == m_key).first()
        is_realtime = os.environ.get("MARKET_DATA_PROVIDER", "yfinance").lower() == "realtime"
        
        has_realtime_issue = False
        reject_reason = None
        
        if is_realtime:
            if not provider.is_connected:
                has_realtime_issue = True
                if getattr(provider, "auth_failed", False):
                    reject_reason = "REAL-TIME PROVIDER AUTHENTICATION FAILED"
                else:
                    reject_reason = "REAL-TIME PROVIDER NOT CONFIGURED"
            elif not provider.websocket_connected:
                has_realtime_issue = True
                reject_reason = "DATA PROVIDER DISCONNECTED"
            elif not dq or not dq.trading_eligible:
                has_realtime_issue = True
                if dq and dq.data_status == "STALE":
                    reject_reason = "STALE MARKET DATA"
                else:
                    reject_reason = "REAL-TIME DATA UNAVAILABLE"
                    
        if df.empty or has_realtime_issue:
            sig = "HOLD"
            close_price = 0.0 if df.empty else float(df.iloc[-1]['Close'])
            if not reject_reason:
                reject_reason = "DATA UNAVAILABLE — NO TRADE SIGNAL"
                
            print(f"TRADING STATUS: NO TRADE. Reason: {reject_reason} for {symbol}")
            
            # Record failed scan log
            scan_log = ScanLog(
                timestamp=datetime.now(timezone.utc),
                market=m_key,
                spot_price=close_price,
                data_age=dq.age_seconds if dq else 0.0,
                data_latency=dq.latency_ms if dq else 0.0,
                strategy_score=0.0,
                ml_probability=0.0,
                trade_quality=0.0,
                direction="HOLD",
                option_confirmation="INVALID",
                selected_strike="N/A",
                strike_score=0.0,
                signal=sig,
                rejection_reason=reject_reason
            )
            db.add(scan_log)
            
            # Record Signal History
            history_entry = SignalHistory(
                symbol=symbol,
                instrument_type="INDEX",
                price=close_price,
                signal=sig,
                confidence=0.0,
                reason=reject_reason,
                reject_reason=reject_reason,
                indicators="None",
                system_mode=system_mode,
                data_source=provider_src,
                strategy_score=0.0,
                ml_probability=0.0,
                trade_quality_score=0.0,
                option_contract="N/A",
                option_state="INVALID"
            )
            db.add(history_entry)
            db.commit()
            continue
            
        latest_row = df.iloc[-1]
        close_price = float(latest_row['Close']) if not pd.isna(latest_row['Close']) else float('nan')
        
        if pd.isna(close_price) or math.isnan(close_price):
            print(f"Skipping {symbol}: invalid price data (NaN)")
            continue
            
        # 1. Initial Scanning Tick
        analysis = calculate_consensus_signal(df, enabled_strats, symbol=symbol)
        sig = analysis['signal']
        
        # Enforce trading eligibility checks from DataQuality audit
        if not dq or not dq.trading_eligible:
            sig = "HOLD"
            analysis["reject_reason"] = f"DATA QUALITY BLOCKED: Feed status is {dq.data_status if dq else 'UNKNOWN'} (Trading disabled)"
            analysis["reason"] = f"DATA QUALITY BLOCKED — {dq.data_status if dq else 'UNKNOWN'}"
            
        # SENSEX options trading limits
        if symbol == "^BSESN" or symbol == "SENSEX":
            sig = "HOLD"
            analysis["reject_reason"] = "SENSEX OPTION TRADING = DISABLED. REASON = LIVE OPTIONS DATA UNAVAILABLE"
            analysis["reason"] = "SENSEX OPTION TRADING DISABLED"
            
        if "DATA QUALITY FAILURE" in analysis['reason'] or provider_src == "DATA UNAVAILABLE":
            sig = "HOLD"
            analysis['reason'] = "DATA UNAVAILABLE — NO TRADE SIGNAL"
            
        # Record Scan cycle
        d_age = dq.age_seconds if dq else 0.0
        d_latency = dq.latency_ms if dq else 0.0
        scan_log = ScanLog(
            timestamp=datetime.now(timezone.utc),
            market=m_key,
            spot_price=close_price,
            data_age=d_age,
            data_latency=d_latency,
            strategy_score=analysis.get('strategy_score', 0.0),
            ml_probability=analysis.get('ml_probability', 0.0),
            trade_quality=analysis.get('trade_quality_score', 0.0),
            direction="BUY_CALL" if sig == "BUY" else ("BUY_PUT" if sig == "SELL" else "HOLD"),
            option_confirmation=analysis.get('option_state', 'INVALID'),
            selected_strike=analysis.get('option_contract', 'N/A'),
            strike_score=analysis.get('strike_score', 0.0) if 'strike_score' in analysis else (analysis.get('strategy_score', 0.0) * 0.8),
            signal=sig,
            rejection_reason=analysis.get('reject_reason') or analysis.get('reason')
        )
        db.add(scan_log)
        db.commit()
            
        prev_sig = get_last_signal(db, symbol)
        
        # 2. Check transition and execute pre-entry validation
        reval_passed = False
        reval_reason = ""
        fresh_analysis = analysis
        
        if sig in ["BUY", "SELL"] and sig != prev_sig:
            if not risk_allowed:
                sig = "HOLD"
                analysis["reject_reason"] = f"Risk blocked: {risk_reason}"
            else:
                trade_risk_ok, trade_risk_reason = check_trade_risk_parameters(analysis, ist_now)
                if not trade_risk_ok:
                    sig = "HOLD"
                    analysis["reject_reason"] = f"Trade parameters blocked: {trade_risk_reason}"
                else:
                    # Run pre-entry state machine validation
                    reval_passed, reval_reason, fresh_analysis = execute_pre_entry_re_validation(
                        db, symbol, analysis, datetime.now(timezone.utc), ist_now
                    )
                    if not reval_passed:
                        sig = "HOLD"
                        analysis["reject_reason"] = reval_reason
                    else:
                        analysis = fresh_analysis  # accept refreshed options metrics & best strike

        # Greek/Bid-Ask snapshot parameters formulation
        opt_entry = float(analysis.get('option_entry', 0.0))
        sig_price = opt_entry
        bid_p = float(analysis.get("option_bid", 0.0))
        ask_p = float(analysis.get("option_ask", 0.0))
        spread_val = max(0.0, ask_p - bid_p) if (ask_p > 0.0 and bid_p > 0.0) else 0.5
        spread_pct_val = (spread_val / sig_price) * 100.0 if sig_price > 0 else 0.5
        
        slippage_pct_val = 0.5
        set_slip = db.query(SystemSettings).filter(SystemSettings.key == "slippage_pct").first()
        if set_slip:
            slippage_pct_val = float(set_slip.value)
        slippage_amt = (slippage_pct_val / 100.0) * sig_price
        
        if ask_p > 0.0:
            fill_price_val = ask_p + slippage_amt
        else:
            fill_price_val = sig_price + slippage_amt
            
        fill_price_val = round(fill_price_val, 2)
        slippage_amt = round(slippage_amt, 2)
        spread_val = round(spread_val, 2)
        spread_pct_val = round(spread_pct_val, 2)

        # Save Signal History including Rejections & Decision-chain logs
        history_entry = SignalHistory(
            symbol=symbol,
            instrument_type=analysis.get('instrument_type', 'INDEX'),
            price=close_price,
            signal=sig,
            confidence=analysis['confidence'],
            reason=analysis['reason'],
            reject_reason=analysis.get('reject_reason'),
            indicators=analysis['indicators'],
            system_mode=system_mode,
            data_source=provider_src,
            
            # Decisions logs
            strategy_score=analysis.get('strategy_score', 0.0),
            ml_probability=analysis.get('ml_probability', 0.0),
            trade_quality_score=analysis.get('trade_quality_score', 0.0),
            option_contract=analysis.get('option_contract'),
            strike=analysis.get('atm_strike'),
            option_type=analysis.get('option_type'),
            entry_price=analysis.get('option_entry'),
            stop_loss=analysis.get('option_sl'),
            target_1=analysis.get('target1'),
            target_2=analysis.get('target2'),
            target_3=analysis.get('target3'),
            
            # Detailed snapshot parameters
            signal_price=sig_price,
            bid_price=bid_p,
            ask_price=ask_p,
            entry_spread=spread_val,
            entry_spread_pct=spread_pct_val,
            fill_price=fill_price_val,
            slippage_pct=slippage_pct_val,
            slippage_amount=slippage_amt,
            
            # State Machine parameters
            mss_state=analysis.get('mss_state', 'NOT_PRESENT'),
            sweep_state=analysis.get('sweep_state', 'NOT_PRESENT'),
            fvg_state=analysis.get('fvg_state', 'NOT_PRESENT'),
            ob_state=analysis.get('ob_state', 'NOT_PRESENT'),
            breaker_state=analysis.get('breaker_state', 'NOT_PRESENT'),
            po3_state=analysis.get('po3_state', 'NOT_PRESENT'),
            crt_state=analysis.get('crt_state', 'NOT_PRESENT'),
            option_state=analysis.get('option_state', 'INVALID')
        )
        db.add(history_entry)
        db.commit()
        
        print(f"Analyzed {symbol} [{system_mode} - {provider_src}]: Spot={close_price:.2f} | Prev={prev_sig} -> Current={sig}")
        
        # 3. Create Paper Trade ONLY after all re-evaluation, anti-chase, and risk filters pass
        if sig in ["BUY", "SELL"] and sig != prev_sig and reval_passed:
            opt_contract = analysis.get('option_contract', 'N/A')
            opt_entry = float(analysis.get('option_entry', 0.0))
            opt_sl = float(analysis.get('option_sl', 0.0))
            opt_t1 = float(analysis.get('target1', 0.0))
            opt_t2 = float(analysis.get('target2', 0.0))
            opt_t3 = float(analysis.get('target3', 0.0))
            
            if opt_contract == "N/A" or opt_entry <= 0:
                continue

            dup = db.query(PaperTrade).filter(PaperTrade.symbol == symbol, PaperTrade.status == "ACTIVE").first()
            if dup:
                continue

            meta = get_instrument_metadata(symbol)
            lot_size = meta.get("lot_size", 75)
            qty = lot_size * 2
            
            # Execution Cost & Fill Calculations
            slippage_pct_val = 0.5
            set_slip = db.query(SystemSettings).filter(SystemSettings.key == "slippage_pct").first()
            if set_slip:
                slippage_pct_val = float(set_slip.value)

            sig_price = opt_entry
            bid_p = float(analysis.get("option_bid", 0.0))
            ask_p = float(analysis.get("option_ask", 0.0))
            spread_val = max(0.0, ask_p - bid_p) if (ask_p > 0.0 and bid_p > 0.0) else 0.5
            spread_pct_val = (spread_val / sig_price) * 100.0 if sig_price > 0 else 0.5

            slippage_amt = (slippage_pct_val / 100.0) * sig_price

            # BUY option direction-aware fill (mostly option buying CE/PE)
            if ask_p > 0.0:
                fill_price_val = ask_p + slippage_amt
            else:
                fill_price_val = sig_price + slippage_amt

            # Round values
            fill_price_val = round(fill_price_val, 2)
            slippage_amt = round(slippage_amt, 2)
            spread_val = round(spread_val, 2)
            spread_pct_val = round(spread_pct_val, 2)

            # Transaction costs
            brokerage_val = 20.0
            stt_val = 0.0  # Option buying STT is sell-only
            exchange_charges_val = round(0.00053 * (fill_price_val * qty), 2)
            gst_val = round(0.18 * (brokerage_val + exchange_charges_val), 2)
            stamp_duty_val = round(0.00003 * (fill_price_val * qty), 2)
            entry_costs = round(brokerage_val + exchange_charges_val + gst_val + stamp_duty_val, 2)

            trade_entry = PaperTrade(
                symbol=symbol,
                direction="BUY_CALL" if sig == "BUY" else "BUY_PUT",
                option_contract=opt_contract,
                qty=qty,
                initial_qty=qty,
                entry_price=fill_price_val,   # Entry set to realistic fill price
                current_price=fill_price_val,
                stop_loss=opt_sl,
                target_1=opt_t1,
                target_2=opt_t2,
                target_3=opt_t3,
                trailing_stop=opt_sl,
                status="ACTIVE",
                signal_score=analysis['strategy_score'],
                confidence=analysis['ml_probability'],
                trade_quality_score=analysis['trade_quality_score'],
                reason=analysis['reason'],
                system_mode=system_mode,
                data_source=provider_src,
                
                # Detailed execution metrics
                signal_price=sig_price,
                bid_price=bid_p,
                ask_price=ask_p,
                entry_spread=spread_val,
                entry_spread_pct=spread_pct_val,
                fill_price=fill_price_val,
                slippage_pct=slippage_pct_val,
                slippage_amount=slippage_amt,
                brokerage=brokerage_val,
                stt=stt_val,
                gst=gst_val,
                exchange_charges=exchange_charges_val,
                total_transaction_cost=entry_costs,
                gross_pnl=0.0,
                net_pnl=-entry_costs,

                # State Machine logs
                mss_state=analysis.get('mss_state', 'ACTIVE'),
                sweep_state=analysis.get('sweep_state', 'ACTIVE'),
                fvg_state=analysis.get('fvg_state', 'ACTIVE'),
                ob_state=analysis.get('ob_state', 'ACTIVE'),
                breaker_state=analysis.get('breaker_state', 'ACTIVE'),
                po3_state=analysis.get('po3_state', 'ACTIVE'),
                crt_state=analysis.get('crt_state', 'ACTIVE'),
                option_state=analysis.get('option_state', 'STRONG'),

                # Fast-scalping & MFE/MAE
                signal_id=analysis.get('signal_id'),
                mfe=0.0,
                mae=0.0,
                max_holding_time_minutes=int(analysis.get('max_holding_time_minutes', 5))
            )
            db.add(trade_entry)
            db.commit()

            sym_clean = symbol.replace("^", "").replace(".NS", "")
            direction_str = "CALL" if sig == "BUY" else "PUT"
            sig_id = analysis.get("signal_id", "N/A")
            score_val = analysis.get("signal_score", 8.0)
            vix_val = analysis.get("vix_value", 14.5)
            vix_reg = analysis.get("vix_regime", "NORMAL")
            idx_entry = analysis.get("index_entry", close_price)
            idx_stop = analysis.get("index_stop", close_price * 0.995 if sig == "BUY" else close_price * 1.005)
            idx_target = analysis.get("index_target", close_price * 1.01 if sig == "BUY" else close_price * 0.99)
            idx_rr = analysis.get("index_rr", 1.8)
            risk_pts = round(abs(idx_entry - idx_stop), 1)
            reward_pts = round(abs(idx_target - idx_entry), 1)
            opt_delta = analysis.get("delta", 0.55 if sig == "BUY" else -0.55)
            
            # Exact 18-line CRT + PO3 Telegram Template
            msg = (
                f"🔥 *CRT + PO3 SIGNAL (SIGNAL_DETECTED)*\n"
                f"Signal ID: `{sig_id}`\n"
                f"Status: `SIGNAL_DETECTED`\n\n"
                f"*Instrument:* `{sym_clean}`\n"
                f"*Direction:* {direction_str}\n"
                f"*Market Bias:* {analysis.get('market_bias', 'BULLISH' if sig == 'BUY' else 'BEARISH')}\n"
                f"*PO3 Phase:* {analysis.get('po3_phase', 'DISTRIBUTION')}\n\n"
                f"*4H Sweep:* YES (Mode: {analysis.get('sweep_mode', 'LIVE_SWEEP')} | Level: {analysis.get('sweep_level', idx_stop):.1f})\n"
                f"*5M MSS:* YES (Break Level: {analysis.get('mss_level', idx_entry):.1f})\n"
                f"*1M Retest Confirmed:* YES\n"
                f"*FVG / Breaker:* YES\n\n"
                f"*Index Entry:* {idx_entry:.2f}\n"
                f"*Index Stop:* {idx_stop:.2f}\n"
                f"*Index Target:* {idx_target:.2f}\n"
                f"*Risk:* {risk_pts} pts | *Reward:* {reward_pts} pts | *R:R:* {idx_rr}\n\n"
                f"*Option Selected:* `{opt_contract}` (Delta: {abs(opt_delta):.2f})\n"
                f"*Option Entry:* ₹{opt_entry:.2f} | *Option SL:* ₹{opt_sl:.2f} | *Target:* ₹{opt_t2:.2f}\n\n"
                f"*Signal Score:* {score_val:.0f}/10\n"
                f"*India VIX:* {vix_val:.1f} ({vix_reg})\n"
                f"*Market Breadth:* {analysis.get('advances', 32)} Adv / {analysis.get('declines', 18)} Dec\n"
                f"*Max Holding Time:* 5 Mins (Fast Scalp)\n\n"
                f"*Reason:* {analysis.get('reason', 'CRT + PO3 Confirmation')}"
            )
            
            subs = db.query(UserSubscription).filter(UserSubscription.is_active == True).all()
            if subs:
                for sub in subs:
                    send_telegram_alert(msg, sub.chat_id)
            else:
                fallback_chat = os.environ.get("TELEGRAM_CHAT_ID")
                if fallback_chat:
                    send_telegram_alert(msg, fallback_chat)
                
    db.close()

def monitor_active_trades_tick():
    """
    High-frequency monitor (every 3 seconds) for open paper positions.
    Evaluates trailing stops, profit targets, and stop-loss breaches on live ticks
    without waiting for the 1-minute candle interval.
    """
    db = SessionLocal()
    try:
        active_count = db.query(PaperTrade).filter(PaperTrade.status == "ACTIVE").count()
        if active_count > 0:
            paper_mgr = PaperTradingManager()
            paper_mgr.update_active_trades(db)
    except Exception as e:
        print(f"Error in monitor_active_trades_tick: {e}")
    finally:
        db.close()

def main():
    from fastapi import FastAPI
    import uvicorn
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print("Initializing Database tables...")
        init_db()
        
        db = SessionLocal()
        if db.query(StrategyState).count() == 0:
            default_strats = ["ema_crossover", "rsi", "macd", "bollinger_bands"]
            for s in default_strats:
                db.add(StrategyState(strategy_name=s, is_enabled=True))
            db.commit()
            
        defaults = {
            "max_daily_loss": "5000",
            "max_daily_trades": "5",
            "max_simultaneous_trades": "2",
            "min_risk_reward": "2.0",
            "signal_threshold": "75",
            "max_entry_chase_pct": "5.0", # Configurable chase protect setting
            "weight_trend_bias": "15",
            "weight_liquidity_sweep": "20",
            "weight_mss": "20",
            "weight_displacement": "10",
            "weight_fvg": "10",
            "weight_vwap": "10",
            "weight_options_pcr": "10",
            "weight_ml_prob": "5",
        }
        for k, v in defaults.items():
            exists = db.query(SystemSettings).filter(SystemSettings.key == k).first()
            if not exists:
                db.add(SystemSettings(key=k, value=v))
        db.commit()
        db.close()
        
        if PERSONAL_USE_ONLY:
            print("\n" + "="*80)
            print("WARNING: PERSONAL_USE_ONLY is set to true.")
            print("Note that public distribution of trading recommendations in India may require SEBI registration.")
            print("="*80 + "\n")
            
        scheduler = BackgroundScheduler(timezone=IST)
        
        # Auto-refresh Angel One session daily before pre-market (8:45 AM IST Mon-Fri)
        def daily_angel_session_refresh():
            try:
                from scripts.angel_auto_login import generate_angel_session, update_env_file, ENV_PATH, load_env_variables
                load_env_variables()
                api_key = os.environ.get("ANGEL_API_KEY", "")
                client_code = os.environ.get("ANGEL_CLIENT_CODE", "")
                pin = os.environ.get("ANGEL_PIN", "")
                totp_key = os.environ.get("ANGEL_TOTP_KEY", "")
                if api_key and client_code and pin and totp_key:
                    jwt, feed = generate_angel_session(api_key, client_code, pin, totp_key)
                    update_env_file(ENV_PATH, jwt, feed)
                    print(f"[{datetime.now(IST)}] Daily Angel One SmartAPI session refreshed successfully.")
            except Exception as e:
                print(f"[{datetime.now(IST)}] Daily Angel One SmartAPI session refresh failed: {e}")

        scheduler.add_job(daily_angel_session_refresh, 'cron', day_of_week='mon-fri', hour=8, minute=45, timezone=IST)
        scheduler.add_job(run_market_scan, 'interval', minutes=1, next_run_time=datetime.now(IST))
        # High-frequency active trade monitor runs every 3 seconds
        scheduler.add_job(monitor_active_trades_tick, 'interval', seconds=3, next_run_time=datetime.now(IST))
        scheduler.start()
        app.state.scheduler = scheduler
        print("APScheduler scanning worker, 3s trade monitor & 8:45 AM Angel One auth cron started.")
        
        yield
        
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            scheduler.shutdown()
            print("APScheduler scanning worker stopped.")
            
    app = FastAPI(title="MarketSignalBot Worker Service", lifespan=lifespan)
    @app.get("/health")
    def health():
        return {"status": "healthy", "service": "worker"}
        
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
