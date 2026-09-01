import os
import asyncio
import numpy as np
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from signals.providers import get_data_provider
from signals.providers.realtime_provider import RealTimeMarketDataProvider

from db.database import get_db, SessionLocal, validate_paper_mode
validate_paper_mode()
from db.models import SignalHistory, UserSubscription, StrategyState, init_db, OptionMomentumHistory, PaperTrade, SystemSettings, DataQuality
from db.instruments import INSTRUMENTS_REGISTRY, get_grouped_instruments, get_instrument_metadata
from signals.option_chain_provider import NSEOptionChainProvider
from worker.main import run_market_scan, TELEGRAM_BOT_TOKEN, PERSONAL_USE_ONLY

app = FastAPI(title="MarketSignalBot API", version="1.0.0")
chain_provider = NSEOptionChainProvider()
IST = ZoneInfo("Asia/Kolkata")

# Enable CORS for React Frontend dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Telegram Bot Handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 *Welcome to MarketSignalBot!*\n\n"
        "Use `/subscribe` to register for live technical entry/exit signals.\n"
        "Use `/unsubscribe` to opt-out of alerts."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    
    db = SessionLocal()
    try:
        sub = db.query(UserSubscription).filter(UserSubscription.chat_id == chat_id).first()
        if not sub:
            sub = UserSubscription(chat_id=chat_id, username=username, is_active=True)
            db.add(sub)
            db.commit()
            msg = "🚀 *Subscribed!* You will now receive live confirmation signals."
        elif not sub.is_active:
            sub.is_active = True
            db.commit()
            msg = "✅ *Resubscribed!* Alerts have been reactivated for your account."
        else:
            msg = "ℹ️ You are already subscribed to live alerts."
    except Exception as e:
        db.rollback()
        msg = f"❌ *Subscription failed*: {e}"
    finally:
        db.close()
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    
    db = SessionLocal()
    try:
        sub = db.query(UserSubscription).filter(UserSubscription.chat_id == chat_id).first()
        if sub and sub.is_active:
            sub.is_active = False
            db.commit()
            msg = "🛑 *Unsubscribed!* Alerts deactivated. You will no longer receive signal updates."
        else:
            msg = "ℹ️ You are not registered for signal alerts."
    except Exception as e:
        db.rollback()
        msg = f"❌ *Failed to unsubscribe*: {e}"
    finally:
        db.close()
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def test_alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Verification label required by prompt
    prefix = "🧪 *TEST ALERT — PAPER MODE*\n*REAL ORDERS: DISABLED*\n\n_This is only to verify Telegram messaging and must never execute a real trade._\n\n"
    
    messages = {
        "buy_ce": prefix + (
            "🟢 *BUY CE — PAPER SIGNAL*\n\n"
            "📊 *INDEX:* NIFTY 50\n"
            "💹 *SPOT:* 24,850.25\n\n"
            "🎯 *OPTION:*\n"
            "NIFTY 24,900 CE\n"
            "Expiry: Nearest Weekly\n"
            "LTP: ₹142.50\n\n"
            "📈 *SIGNAL:*\n"
            "Direction: BULLISH\n"
            "Strategy Score: 87/100\n"
            "Trade Quality: 82/100\n"
            "ML Probability: 76%\n\n"
            "🧠 *SETUP:*\n"
            "✅ Liquidity Sweep\n"
            "✅ Bullish MSS\n"
            "✅ Bullish FVG\n"
            "✅ VWAP Support\n"
            "✅ EMA Alignment\n"
            "✅ Option Premium Momentum\n"
            "✅ OI Confirmation\n\n"
            "🎯 *PAPER ENTRY:* ₹142.50\n"
            "🛑 *STOP LOSS:* ₹125.00\n"
            "🎯 *TARGET 1:* ₹155.00\n"
            "🎯 *TARGET 2:* ₹170.00\n"
            "🎯 *TARGET 3:* ₹190.00\n\n"
            "📊 *RISK/REWARD:* 1:2.7\n"
            "🔥 *Strike Score:* 91/100\n\n"
            "⚠️ *PAPER TRADE*\n"
            "REAL ORDER: DISABLED\n\n"
            "🕐 Time: 10:25:15 IST"
        ),
        "buy_pe": prefix + (
            "🔴 *BUY PE — PAPER SIGNAL*\n\n"
            "📊 *INDEX:* BANK NIFTY\n"
            "💹 *SPOT:* 57,420.00\n\n"
            "🎯 *OPTION:*\n"
            "BANK NIFTY 57,400 PE\n"
            "LTP: ₹210.00\n\n"
            "📉 *SIGNAL:*\n"
            "Direction: BEARISH\n"
            "Strategy Score: 89/100\n"
            "Trade Quality: 85/100\n"
            "ML Probability: 79%\n\n"
            "🧠 *SETUP:*\n"
            "✅ Liquidity Sweep\n"
            "✅ Bearish MSS\n"
            "✅ Bearish FVG\n"
            "✅ VWAP Rejection\n"
            "✅ EMA Alignment\n"
            "✅ Premium Momentum\n"
            "✅ OI Confirmation\n\n"
            "🎯 *PAPER ENTRY:* ₹210.00\n"
            "🛑 *STOP LOSS:* ₹185.00\n"
            "🎯 *T1:* ₹230.00\n"
            "🎯 *T2:* ₹255.00\n"
            "🎯 *T3:* ₹290.00\n\n"
            "⚠️ *PAPER MODE*\n"
            "REAL ORDERS: DISABLED"
        ),
        "t1": prefix + (
            "🎯 *T1 HIT — PAPER TRADE*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Entry: ₹142.50\n"
            "Current: ₹155.00\n\n"
            "✅ *T1 TARGET HIT*\n\n"
            "Booked: 40%\n"
            "Remaining: 60%\n\n"
            "🛡️ *STOP LOSS MOVED TO BREAKEVEN*\n\n"
            "New SL: ₹142.50\n\n"
            "Current Paper P&L: +₹1,250.00\n\n"
            "REAL ORDER: DISABLED"
        ),
        "t2": prefix + (
            "🎯 *T2 HIT — PAPER TRADE*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Entry: ₹142.50\n"
            "Current: ₹170.00\n\n"
            "✅ *T2 TARGET HIT*\n\n"
            "Booked: Additional 30%\n"
            "Remaining: 30%\n\n"
            "🛡️ *TRAILING STOP ACTIVATED*\n\n"
            "ATR Trailing SL: ₹158.00\n\n"
            "Paper P&L: +₹2,100.00"
        ),
        "t3": prefix + (
            "🏆 *T3 HIT — PAPER TRADE CLOSED*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Entry: ₹142.50\n"
            "Exit: ₹190.00\n\n"
            "✅ *T3 HIT*\n\n"
            "Final Position: CLOSED\n"
            "Total Quantity: 100\n"
            "Profit: ₹4,750.00\n"
            "ROI: 33.3%\n\n"
            "Reason: T3 TARGET\n\n"
            "⚠️ *PAPER TRADE*\n"
            "REAL ORDERS: DISABLED"
        ),
        "sl": prefix + (
            "🛑 *STOP LOSS HIT — PAPER TRADE*\n\n"
            "📊 BANK NIFTY\n"
            "📉 BANK NIFTY 57,400 PE\n\n"
            "Entry: ₹210.00\n"
            "Exit: ₹185.00\n\n"
            "❌ *STOP LOSS HIT*\n\n"
            "Position: CLOSED\n"
            "Paper P&L: -₹1,875.00\n"
            "Reason: STOP LOSS\n\n"
            "REAL ORDER: DISABLED"
        ),
        "missed": prefix + (
            "⚠️ *ENTRY MISSED — DO NOT CHASE*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Calculated Entry: ₹142.50\n"
            "Current LTP: ₹151.00\n\n"
            "Price moved beyond:\n"
            "MAX_ENTRY_CHASE_PCT = 5%\n\n"
            "❌ *PAPER ENTRY CANCELLED*\n\n"
            "Reason:\n"
            "OPTION PRICE MOVED TOO FAR\n\n"
            "No trade was created."
        ),
        "invalidated": prefix + (
            "❌ *SETUP INVALIDATED — NO TRADE*\n\n"
            "📊 NIFTY 50\n\n"
            "Original Signal:\n"
            "BUY CE\n\n"
            "Re-validation:\n"
            "❌ MSS invalidated\n"
            "❌ Liquidity Sweep invalidated\n\n"
            "Option Confirmation:\n"
            "WEAK\n\n"
            "Decision:\n"
            "NO TRADE\n\n"
            "No paper position created."
        ),
        "data_fail": prefix + (
            "🚨 *MARKET DATA WARNING*\n\n"
            "Provider: FYERS\n"
            "WebSocket: DISCONNECTED\n\n"
            "Data Age: 8.4 seconds\n\n"
            "Trading Status:\n"
            "❌ NO TRADE\n\n"
            "Reason:\n"
            "REAL-TIME MARKET DATA UNAVAILABLE\n\n"
            "The bot must not generate a new trade signal until the feed becomes healthy again."
        ),
        "summary": prefix + (
            "📊 *DAILY PAPER TRADING SUMMARY*\n\n"
            "Date: 24-08-2026\n\n"
            "Trades: 8\n"
            "Wins: 5\n"
            "Losses: 3\n"
            "Win Rate: 62.5%\n\n"
            "Gross P&L: ₹8,125.00\n"
            "Net P&L: ₹7,850.00\n"
            "Max Drawdown: ₹1,500.00\n\n"
            "Best Index:\n"
            "NIFTY 50\n\n"
            "Best Setup:\n"
            "Liquidity Sweep + MSS + FVG\n\n"
            "⚠️ *PAPER TRADING*\n"
            "REAL ORDERS: DISABLED"
        )
    }

    args = context.args
    if args and args[0].lower() in messages:
        target = args[0].lower()
        await update.message.reply_text(messages[target], parse_mode="Markdown")
    else:
        await update.message.reply_text("🧪 *Starting Telegram alert templates test loop...*", parse_mode="Markdown")
        for key, msg in messages.items():
            try:
                await update.message.reply_text(msg, parse_mode="Markdown")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Telegram error in test alert loop: {e}")
        await update.message.reply_text("✅ *Telegram alert templates test completed successfully.*", parse_mode="Markdown")

# Startup Lifespan Management
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing Database tables...")
    init_db()
    
    # Initialize default strategies if table is empty
    db = SessionLocal()
    if db.query(StrategyState).count() == 0:
        default_strats = ["ema_crossover", "rsi", "macd", "bollinger_bands"]
        for s in default_strats:
            db.add(StrategyState(strategy_name=s, is_enabled=True))
        db.commit()
        
    # Seed initial DataQuality cache at startup
    try:
        from worker.main import perform_market_audit
        perform_market_audit(db)
    except Exception as e:
        print(f"Error seeding initial DataQuality cache: {e}")
        
    db.close()
    
    if PERSONAL_USE_ONLY:
        print("\n" + "="*80)
        print("WARNING: PERSONAL_USE_ONLY is set to true.")
        print("Note that public distribution of trading recommendations in India may require SEBI registration.")
        print("="*80 + "\n")

    import sys
    # 1. Start APScheduler Background Polling (Only if enabled or running in unit test)
    enable_api_scanner = os.environ.get("ENABLE_API_SCANNER", "false").lower() == "true" or "pytest" in sys.modules
    if enable_api_scanner:
        scheduler = BackgroundScheduler(timezone=IST)
        # Runs the unified scanner tick every 1 minute
        scheduler.add_job(run_market_scan, 'interval', minutes=1, next_run_time=datetime.now(IST))
        scheduler.start()
        app.state.scheduler = scheduler
        print("API Lifespan: Background scanning scheduler started.")
    else:
        app.state.scheduler = None
        print("API Lifespan: Background scanning delegated to worker service.")
    
    # 2. Start Telegram Bot Async Polling (Only if explicitly enabled, preventing conflicts with bot service)
    enable_telegram_in_api = os.environ.get("ENABLE_TELEGRAM_IN_API", "false").lower() == "true"
    if enable_telegram_in_api and TELEGRAM_BOT_TOKEN:
        tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        tg_app.add_handler(CommandHandler("start", start_cmd))
        tg_app.add_handler(CommandHandler("subscribe", subscribe_cmd))
        tg_app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
        tg_app.add_handler(CommandHandler("test_alert", test_alert_cmd))
        
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        app.state.tg_app = tg_app
        print("API Lifespan: Telegram Bot listener started in API process.")
    else:
        app.state.tg_app = None

    yield

    # Shutdown logic
    # Stop scheduler
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown()
        print("API Lifespan: Background scanner stopped.")
        
    # Stop Telegram Bot
    tg_app = getattr(app.state, "tg_app", None)
    if tg_app:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()
        print("API Lifespan: Telegram Bot stopped.")

app.router.lifespan_context = lifespan

# Pydantic Schemas
class StrategyToggle(BaseModel):
    strategy_name: str
    is_enabled: bool

class SettingUpdate(BaseModel):
    key: str
    value: str

class SignalResponse(BaseModel):
    id: int
    symbol: str
    instrument_type: str = "STOCK"
    price: float
    signal: str
    confidence: float
    reason: str
    reject_reason: Optional[str] = None
    indicators: str
    strategy_score: Optional[float] = 0.0
    ml_probability: Optional[float] = 0.0
    trade_quality_score: Optional[float] = 0.0
    system_mode: Optional[str] = "PAPER"
    data_source: Optional[str] = "yfinance"
    
    # State values
    mss_state: Optional[str] = "NOT_PRESENT"
    sweep_state: Optional[str] = "NOT_PRESENT"
    fvg_state: Optional[str] = "NOT_PRESENT"
    ob_state: Optional[str] = "NOT_PRESENT"
    breaker_state: Optional[str] = "NOT_PRESENT"
    po3_state: Optional[str] = "NOT_PRESENT"
    crt_state: Optional[str] = "NOT_PRESENT"
    option_state: Optional[str] = "INVALID"
    
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class OptionMomentumResponse(BaseModel):
    id: int
    symbol: str
    strike: int
    option_type: str
    contract: str
    old_premium: float
    new_premium: float
    pct_change: float
    oi_change: int
    volume: int
    spot_price: float
    data_source: str = "live"
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class OptionProfitRequest(BaseModel):
    symbol: str = "NIFTY"
    strike: int
    option_type: str = "CE"
    entry_premium: float
    target_premium: float
    quantity_lots: int = 1

class OptionProfitResponse(BaseModel):
    symbol: str
    strike: int
    option_type: str
    lot_size: int
    total_shares: int
    entry_premium: float
    target_premium: float
    profit_per_lot: float
    total_profit: float
    total_investment: float
    roi_pct: float

# --- API ENDPOINTS ---

@app.get("/instruments")
def get_instruments():
    """Returns all available instruments categorized into Indices vs Stocks with full metadata."""
    return get_grouped_instruments()

@app.get("/options/chain")
def get_option_chain(symbol: str = Query("NIFTY", description="Symbol e.g. NIFTY or BANKNIFTY")):
    """Returns the full option chain table across all strikes with spot_price and atm_strike."""
    sym_clean = symbol.upper().replace("^", "")
    if sym_clean == "NSEI":
        sym_clean = "NIFTY"
    elif sym_clean == "NSEBANK":
        sym_clean = "BANKNIFTY"
    elif sym_clean == "BSESN":
        sym_clean = "SENSEX"
    
    try:
        return chain_provider.get_full_chain(sym_clean)
    except Exception as e:
        return {
            "symbol": sym_clean,
            "data_source": "unavailable",
            "status": "UNAVAILABLE",
            "message": str(e),
            "spot_price": 0.0,
            "atm_strike": 0,
            "chain": []
        }

@app.post("/options/profit", response_model=OptionProfitResponse)
def calculate_option_profit(req: OptionProfitRequest):
    """Calculates lot size, total investment, profit per lot, total profit, and ROI %."""
    meta = get_instrument_metadata(req.symbol)
    lot_size = meta.get("lot_size", 75 if "NIFTY" in req.symbol.upper() and "BANK" not in req.symbol.upper() else 15)
    
    lots = max(1, req.quantity_lots)
    total_shares = lots * lot_size
    profit_per_lot = round((req.target_premium - req.entry_premium) * lot_size, 2)
    total_profit = round(profit_per_lot * lots, 2)
    total_investment = round(req.entry_premium * total_shares, 2)
    roi_pct = round(((req.target_premium - req.entry_premium) / req.entry_premium) * 100.0, 2) if req.entry_premium > 0 else 0.0

    return OptionProfitResponse(
        symbol=req.symbol.upper(),
        strike=req.strike,
        option_type=req.option_type.upper(),
        lot_size=lot_size,
        total_shares=total_shares,
        entry_premium=req.entry_premium,
        target_premium=req.target_premium,
        profit_per_lot=profit_per_lot,
        total_profit=total_profit,
        total_investment=total_investment,
        roi_pct=roi_pct
    )

@app.get("/options/momentum", response_model=List[OptionMomentumResponse])
def get_option_momentum_alerts(
    symbol: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Returns the latest fast-moving option momentum alerts detected by short-interval scanner."""
    query = db.query(OptionMomentumHistory)
    if symbol:
        sym_clean = symbol.upper().replace("^", "")
        if sym_clean == "NSEI":
            sym_clean = "NIFTY"
        elif sym_clean == "NSEBANK":
            sym_clean = "BANKNIFTY"
        elif sym_clean == "BSESN":
            sym_clean = "SENSEX"
        query = query.filter(OptionMomentumHistory.symbol == sym_clean)
        
    records = query.order_by(desc(OptionMomentumHistory.timestamp)).limit(limit).all()
    return records

@app.get("/signals/latest", response_model=List[SignalResponse])
def get_latest_signals(db: Session = Depends(get_db)):
    symbols = ["^NSEI", "^BSESN", "^NSEBANK"] # Focus indices
    latest_signals = []
    
    for sym in symbols:
        record = db.query(SignalHistory).filter(SignalHistory.symbol == sym).order_by(desc(SignalHistory.timestamp)).first()
        if record:
            latest_signals.append(record)
            
    return latest_signals

@app.get("/signals/history", response_model=List[SignalResponse])
def get_signals_history(
    symbol: str, 
    days: int = Query(7, ge=1, le=30), 
    db: Session = Depends(get_db)
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = db.query(SignalHistory).filter(
        SignalHistory.symbol == symbol,
        SignalHistory.timestamp >= cutoff
    ).order_by(desc(SignalHistory.timestamp)).all()
    
    return records

@app.post("/admin/strategy/toggle")
def toggle_strategy(payload: StrategyToggle, db: Session = Depends(get_db)):
    strategy = db.query(StrategyState).filter(StrategyState.strategy_name == payload.strategy_name).first()
    if not strategy:
        strategy = StrategyState(strategy_name=payload.strategy_name, is_enabled=payload.is_enabled)
        db.add(strategy)
    else:
        strategy.is_enabled = payload.is_enabled
        
    db.commit()
    return {"status": "success", "strategy": payload.strategy_name, "is_enabled": payload.is_enabled}

# --- NEW API ENDPOINTS ---

@app.get("/trades/active")
def get_active_trades(db: Session = Depends(get_db)):
    """Returns all active paper trading positions."""
    return db.query(PaperTrade).filter(PaperTrade.status == "ACTIVE").all()

@app.get("/trades/history")
def get_trades_history(db: Session = Depends(get_db)):
    """Returns all completed paper trading positions (Trade Journal Ledger)."""
    return db.query(PaperTrade).filter(PaperTrade.status == "CLOSED").order_by(desc(PaperTrade.exit_time)).all()

@app.get("/admin/settings")
def get_settings(db: Session = Depends(get_db)):
    """Returns all stored configuration settings."""
    settings = db.query(SystemSettings).all()
    return {s.key: s.value for s in settings}

@app.post("/admin/settings")
def update_setting(payload: SettingUpdate, db: Session = Depends(get_db)):
    """Updates or inserts a system setting configuration."""
    setting = db.query(SystemSettings).filter(SystemSettings.key == payload.key).first()
    if not setting:
        setting = SystemSettings(key=payload.key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    db.commit()
    return {"status": "success", "key": payload.key, "value": payload.value}

@app.get("/backtest/run")
def run_backtest_api(symbol: str = "NIFTY", days: int = 30):
    """Executes a historical option backtest on spot candles and returns metrics."""
    from backtesting.engine import HistoricalBacktester
    bt = HistoricalBacktester(symbol, days)
    return bt.run()

@app.post("/ml/train")
def train_ml_model(symbol: str = "NIFTY", days: int = 60):
    """Downloads historical data and trains/caches the RandomForest direction model."""
    from ml.prediction import MLPredictionEngine
    import yfinance as yf
    
    spot_ticker = "^NSEI"
    if symbol.upper() == "BANKNIFTY":
        spot_ticker = "^NSEBANK"
    elif symbol.upper() == "SENSEX":
        spot_ticker = "^BSESN"
        
    df = yf.download(spot_ticker, period=f"{days}d", interval="15m", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()]
    
    ml_engine = MLPredictionEngine(symbol)
    msg = ml_engine.train_model(df)
    return {"status": "success", "message": msg}

@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Health check returning services status information."""
    db_status = "HEALTHY"
    try:
        db.query(SystemSettings).first()
    except Exception:
        db_status = "UNHEALTHY"

    worker_status = "STOPPED"
    try:
        hb = db.query(SystemSettings).filter(SystemSettings.key == "worker_heartbeat").first()
        if hb:
            hb_time = datetime.fromisoformat(hb.value)
            if (datetime.now(timezone.utc) - hb_time.replace(tzinfo=timezone.utc)).total_seconds() < 180:
                worker_status = "RUNNING"
    except Exception:
        pass

    telegram_status = "CONNECTED" if TELEGRAM_BOT_TOKEN else "DISCONNECTED"
    system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()
    real_orders_enabled = os.environ.get("REAL_ORDERS_ENABLED", "false").lower() == "true"

    from signals.providers import get_data_provider
    provider = get_data_provider()
    is_realtime = isinstance(provider, RealTimeMarketDataProvider)
    connected = provider.is_connected if hasattr(provider, "is_connected") else False
    websocket = provider.websocket_connected if hasattr(provider, "websocket_connected") else False
    auth_failed = getattr(provider, "auth_failed", False)

    # Read cached DataQuality statuses
    dqs = db.query(DataQuality).all()
    markets_status = {}
    overall_eligible = True
    
    data_age = 0.0
    latency_ms = 0.0
    options_status = {}
    
    for dq in dqs:
        if dq.age_seconds > data_age:
            data_age = dq.age_seconds
        if dq.latency_ms > latency_ms:
            latency_ms = dq.latency_ms
            
        if not dq.trading_eligible:
            overall_eligible = False
            
        markets_status[dq.symbol] = {
            "spot": dq.data_status,
            "option_chain": "LIVE" if dq.data_status in ["LIVE", "SIMULATION"] and "option_chain" not in dq.missing_fields else "UNAVAILABLE",
            "overall": "GOOD" if dq.trading_eligible else "INSUFFICIENT",
            "trading_eligible": dq.trading_eligible,
            "age_seconds": dq.age_seconds,
            "latency_ms": dq.latency_ms,
            "missing_fields": dq.missing_fields.split(",") if dq.missing_fields else []
        }
        
    for m in ["NIFTY", "BANK_NIFTY", "SENSEX"]:
        if m not in markets_status:
            overall_eligible = False
            markets_status[m] = {
                "spot": "UNAVAILABLE",
                "option_chain": "UNAVAILABLE",
                "overall": "INSUFFICIENT",
                "trading_eligible": False,
                "age_seconds": 0.0,
                "latency_ms": 0.0,
                "missing_fields": ["not_audited"]
            }
            
    # Adjust for realtime provider issues
    if is_realtime:
        if not connected or not websocket:
            overall_eligible = False
            for m in markets_status:
                markets_status[m]["trading_eligible"] = False
                markets_status[m]["overall"] = "INSUFFICIENT"
                markets_status[m]["option_chain"] = "UNAVAILABLE"
                if auth_failed:
                    markets_status[m]["spot"] = "AUTHENTICATION FAILED"
                elif not provider.client_id or not provider.secret_key or not provider.access_token:
                    markets_status[m]["spot"] = "UNCONFIGURED"
                else:
                    markets_status[m]["spot"] = "DISCONNECTED"

    # Options status formulation
    for m in ["NIFTY", "BANK_NIFTY", "SENSEX"]:
        if m == "SENSEX":
            options_status[m] = "UNAVAILABLE"
        elif m in markets_status:
            options_status[m] = markets_status[m]["option_chain"]
        else:
            options_status[m] = "UNAVAILABLE"

    provider_type = os.environ.get("MARKET_DATA_PROVIDER", "yfinance").lower()
    provider_name_resolved = "fyers" if is_realtime else provider_type
    
    if is_realtime:
        connection_status = "CONNECTED" if connected else "DISCONNECTED"
        websocket_status = "CONNECTED" if websocket else "DISCONNECTED"
    else:
        websocket_status = "CONNECTED" if system_mode == "SIMULATION" else "DISCONNECTED"
        connection_status = "CONNECTED"

    return {
        "api": "HEALTHY",
        "database": db_status,
        "worker": worker_status,
        "data_provider": {
            "name": provider_name_resolved,
            "overall_status": "GOOD" if overall_eligible else "INSUFFICIENT"
        },
        "connection": connection_status,
        "websocket": websocket_status,
        "data_mode": "LIVE" if overall_eligible and system_mode != "SIMULATION" else ("SIMULATION" if system_mode == "SIMULATION" else "DELAYED"),
        "telegram": telegram_status,
        "mode": system_mode,
        "real_orders_enabled": real_orders_enabled,
        "markets": markets_status,
        "trading_eligibility": overall_eligible,
        
        # New health fields
        "provider": provider_name_resolved,
        "data_age": f"{data_age:.1f} sec",
        "latency": f"{latency_ms:.1f}ms",
        "options": options_status,
        "trading_eligible": overall_eligible and (not is_realtime or (connected and websocket)),
        "system_mode": system_mode
    }

@app.get("/analytics/performance")
def get_analytics_performance(db: Session = Depends(get_db)):
    """Calculates Gross vs Net metrics from Trade Journal logs."""
    trades = db.query(PaperTrade).filter(PaperTrade.status == "CLOSED").all()
    total_signals = db.query(SignalHistory).count()
    
    if not trades:
        total_no_trades = db.query(SignalHistory).filter(SignalHistory.signal == "HOLD").count()
        total_rejected = db.query(SignalHistory).filter(SignalHistory.reject_reason != None).count()
        return {
            "total_signals": total_signals,
            "total_trades": 0,
            "total_no_trades": total_no_trades,
            "total_rejected": total_rejected,
            "winning_trades": 0,
            "losing_trades": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "sample_status": "VERY LOW SAMPLE",
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "total_costs": 0.0,
            "win_rate_gross": 0.0,
            "win_rate_net": 0.0,
            "net_profit_factor": 0.0,
            "net_expectancy": 0.0,
            "net_max_drawdown": 0.0,
            "net_sharpe": 0.0,
            "net_sortino": 0.0,
            "t1_hit_rate": 0.0,
            "t2_hit_rate": 0.0,
            "t3_hit_rate": 0.0,
            "sl_hit_rate": 0.0,
            "avg_holding_time_mins": 0.0,
            "segment_markets": {},
            "segment_types": {}
        }

    total_trades = len(trades)
    
    # Sample Size Evaluation Rule
    if total_trades < 30:
        sample_status = "VERY LOW SAMPLE"
    elif total_trades < 100:
        sample_status = "INSUFFICIENT SAMPLE"
    elif total_trades < 200:
        sample_status = "EARLY SAMPLE"
    elif total_trades < 500:
        sample_status = "MEANINGFUL SAMPLE"
    else:
        sample_status = "STRONGER SAMPLE"

    gross_pnl = sum(t.gross_pnl for t in trades)
    net_pnl = sum(t.net_pnl for t in trades)
    total_costs = sum(t.total_transaction_cost for t in trades)

    # Wins vs Losses (Gross)
    wins_gross = [t for t in trades if t.gross_pnl > 0]
    losses_gross = [t for t in trades if t.gross_pnl <= 0]
    win_rate_gross = (len(wins_gross) / total_trades) * 100.0

    # Wins vs Losses (Net)
    wins_net = [t for t in trades if t.net_pnl > 0]
    losses_net = [t for t in trades if t.net_pnl <= 0]
    win_rate_net = (len(wins_net) / total_trades) * 100.0

    avg_net_profit = np.mean([t.net_pnl for t in wins_net]) if wins_net else 0.0
    avg_net_loss = np.mean([t.net_pnl for t in losses_net]) if losses_net else 0.0

    # Profit Factor (Net)
    sum_win_net = sum(t.net_pnl for t in wins_net)
    sum_loss_net = abs(sum(t.net_pnl for t in losses_net))
    net_profit_factor = sum_win_net / sum_loss_net if sum_loss_net > 0 else 999.0

    # Expectancy (Net)
    net_expectancy = (win_rate_net / 100.0 * avg_net_profit) + ((1.0 - win_rate_net / 100.0) * avg_net_loss)

    # Maximum Drawdown (Net)
    sorted_trades = sorted(trades, key=lambda x: (x.exit_time.replace(tzinfo=timezone.utc) if x.exit_time else datetime.now(timezone.utc)))
    cumulative_net = np.cumsum([t.net_pnl for t in sorted_trades])
    peak = np.maximum.accumulate(cumulative_net)
    drawdown = peak - cumulative_net
    max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    # Sharpe and Sortino ratios
    returns = np.array([t.net_pnl for t in sorted_trades])
    std_ret = np.std(returns)
    sharpe = (np.mean(returns) / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0

    downside = returns[returns < 0]
    std_down = np.std(downside)
    sortino = (np.mean(returns) / std_down) * np.sqrt(252) if (len(downside) > 0 and std_down > 0) else 0.0

    # Hit Rates
    t1_hits = sum(1 for t in trades if t.partial_exit_1)
    t2_hits = sum(1 for t in trades if t.partial_exit_2)
    t3_hits = sum(1 for t in trades if not t.partial_exit_2 and t.net_pnl > 0)
    sl_hits = sum(1 for t in trades if t.net_pnl <= 0)

    # Avg holding time
    holding_times = []
    for t in trades:
        if t.exit_time and t.entry_time:
            holding_times.append((t.exit_time - t.entry_time).total_seconds() / 60.0)
    avg_hold = np.mean(holding_times) if holding_times else 0.0

    # Segmentations
    segment_markets = {}
    for sym_label, patterns in [("NIFTY", ["NIFTY"]), ("BANK_NIFTY", ["BANKNIFTY", "BANK_NIFTY"]), ("SENSEX", ["SENSEX"])]:
        sym_trades = [t for t in trades if any(p in t.option_contract.upper().replace("_", "") for p in patterns) or any(p in t.symbol.upper().replace("_", "") for p in patterns)]
        if sym_trades:
            win_c = sum(1 for t in sym_trades if t.net_pnl > 0)
            loss_c = sum(1 for t in sym_trades if t.net_pnl <= 0)
            sum_win = sum(t.net_pnl for t in sym_trades if t.net_pnl > 0)
            sum_loss = abs(sum(t.net_pnl for t in sym_trades if t.net_pnl <= 0))
            
            segment_markets[sym_label] = {
                "count": len(sym_trades),
                "win_rate_net": round(win_c / len(sym_trades) * 100.0, 1),
                "net_pnl": round(sum(t.net_pnl for t in sym_trades), 2),
                "profit_factor": round(sum_win / sum_loss if sum_loss > 0 else 999.0, 2)
            }

    segment_types = {}
    for otype in ["CE", "PE"]:
        type_trades = [t for t in trades if otype in t.option_contract.upper() or (otype == "CE" and "CALL" in t.direction) or (otype == "PE" and "PUT" in t.direction)]
        if type_trades:
            segment_types[otype] = {
                "count": len(type_trades),
                "win_rate_net": round(sum(1 for t in type_trades if t.net_pnl > 0) / len(type_trades) * 100.0, 1),
                "net_pnl": round(sum(t.net_pnl for t in type_trades), 2)
            }

    total_no_trades = db.query(SignalHistory).filter(SignalHistory.signal == "HOLD").count()
    total_rejected = db.query(SignalHistory).filter(SignalHistory.reject_reason != None).count()

    return {
        "total_signals": total_signals,
        "total_trades": total_trades,
        "total_no_trades": total_no_trades,
        "total_rejected": total_rejected,
        "winning_trades": len(wins_net),
        "losing_trades": len(losses_net),
        "avg_win": round(avg_net_profit, 2),
        "avg_loss": round(avg_net_loss, 2),
        "sample_status": sample_status,
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "total_costs": round(total_costs, 2),
        "win_rate_gross": round(win_rate_gross, 1),
        "win_rate_net": round(win_rate_net, 1),
        "net_profit_factor": round(net_profit_factor, 2),
        "net_expectancy": round(net_expectancy, 2),
        "net_max_drawdown": round(max_drawdown, 2),
        "net_sharpe": round(sharpe, 2),
        "net_sortino": round(sortino, 2),
        "t1_hit_rate": round((t1_hits / total_trades) * 100.0, 1) if total_trades > 0 else 0.0,
        "t2_hit_rate": round((t2_hits / total_trades) * 100.0, 1) if total_trades > 0 else 0.0,
        "t3_hit_rate": round((t3_hits / total_trades) * 100.0, 1) if total_trades > 0 else 0.0,
        "sl_hit_rate": round((sl_hits / total_trades) * 100.0, 1) if total_trades > 0 else 0.0,
        "avg_holding_time_mins": round(avg_hold, 1),
        "segment_markets": segment_markets,
        "segment_types": segment_types
    }



@app.get("/analytics/breakdown")
def get_analytics_breakdown(db: Session = Depends(get_db)):
    """Provides strategy setup, signal score quality and time-of-day analytics breakdowns."""
    trades = db.query(PaperTrade).filter(PaperTrade.status == "CLOSED").all()
    if not trades:
        return {"setups": {}, "signal_quality": {}, "ml_probability": {}, "time_of_day": {}}

    # Strategy Setups Breakdown
    setup_breakdown = {}
    setup_names = {
        "Liquidity Sweep": "Sweep",
        "MSS": "MSS",
        "FVG": "FVG",
        "Order Block": "OB",
        "Breaker Block": "Breaker",
        "PO3": "PO3",
        "CRT": "CRT"
    }
    for label, pattern in setup_names.items():
        matched = [t for t in trades if pattern in t.reason]
        if matched:
            win_count = sum(1 for t in matched if t.net_pnl > 0)
            losses = [t for t in matched if t.net_pnl <= 0]
            sum_win = sum(t.net_pnl for t in matched if t.net_pnl > 0)
            sum_loss = abs(sum(t.net_pnl for t in losses))
            
            setup_breakdown[label] = {
                "count": len(matched),
                "win_rate": round(win_count / len(matched) * 100.0, 1),
                "profit_factor": round(sum_win / sum_loss if sum_loss > 0 else 999.0, 2),
                "net_pnl": round(sum(t.net_pnl for t in matched), 2)
            }
            
    # Combined Confluence (more than 2 patterns in reason)
    confluence_matched = []
    for t in trades:
        count = sum(1 for pat in setup_names.values() if pat in t.reason)
        if count >= 2:
            confluence_matched.append(t)
    if confluence_matched:
        win_count = sum(1 for t in confluence_matched if t.net_pnl > 0)
        losses = [t for t in confluence_matched if t.net_pnl <= 0]
        sum_win = sum(t.net_pnl for t in confluence_matched if t.net_pnl > 0)
        sum_loss = abs(sum(t.net_pnl for t in losses))
        setup_breakdown["Combined Confluence"] = {
            "count": len(confluence_matched),
            "win_rate": round(win_count / len(confluence_matched) * 100.0, 1),
            "profit_factor": round(sum_win / sum_loss if sum_loss > 0 else 999.0, 2),
            "net_pnl": round(sum(t.net_pnl for t in confluence_matched), 2)
        }

    # Signal Score buckets
    score_breakdown = {}
    score_buckets = [("70-79", 70, 79), ("80-89", 80, 89), ("90-100", 90, 100)]
    for name, low, high in score_buckets:
        matched = [t for t in trades if low <= (t.signal_score or 0.0) <= high]
        if matched:
            score_breakdown[name] = {
                "count": len(matched),
                "win_rate": round(sum(1 for t in matched if t.net_pnl > 0) / len(matched) * 100.0, 1),
                "net_pnl": round(sum(t.net_pnl for t in matched), 2)
            }

    # ML probability buckets
    ml_breakdown = {}
    ml_buckets = [("50-59", 50, 59), ("60-69", 60, 69), ("70-79", 70, 79), ("80-89", 80, 89), ("90-100", 90, 100)]
    for name, low, high in ml_buckets:
        matched = [t for t in trades if low <= (t.confidence or 0.0) <= high]
        if matched:
            ml_breakdown[name] = {
                "count": len(matched),
                "win_rate": round(sum(1 for t in matched if t.net_pnl > 0) / len(matched) * 100.0, 1),
                "net_pnl": round(sum(t.net_pnl for t in matched), 2)
            }

    # Time of Day (IST entry)
    time_breakdown = {}
    time_windows = [
        ("9:15-10:00", 9, 15, 10, 0),
        ("10:00-11:00", 10, 0, 11, 0),
        ("11:00-12:00", 11, 0, 12, 0),
        ("12:00-13:00", 12, 0, 13, 0),
        ("13:00-14:00", 13, 0, 14, 0),
        ("14:00-15:30", 14, 0, 15, 30)
    ]
    for name, sh, sm, eh, em in time_windows:
        matched = []
        for t in trades:
            ist_entry = t.entry_time.replace(tzinfo=timezone.utc).astimezone(IST)
            entry_min = ist_entry.hour * 60 + ist_entry.minute
            start_min = sh * 60 + sm
            end_min = eh * 60 + em
            if start_min <= entry_min < end_min:
                matched.append(t)
        if matched:
            win_count = sum(1 for t in matched if t.net_pnl > 0)
            time_breakdown[name] = {
                "count": len(matched),
                "win_rate": round(win_count / len(matched) * 100.0, 1),
                "net_pnl": round(sum(t.net_pnl for t in matched), 2)
            }

    return {
        "setups": setup_breakdown,
        "signal_quality": score_breakdown,
        "ml_probability": ml_breakdown,
        "time_of_day": time_breakdown
    }

@app.get("/analytics/report")
def get_analytics_report(db: Session = Depends(get_db)):
    """Generates an automated markdown report summarizing paper-trading session metrics."""
    perf = get_analytics_performance(db)
    breakdown = get_analytics_breakdown(db)
    
    rep = (
        f"# Automated Paper-Trading Validation Report\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"## Session Overview\n"
        f"- **Validation Status**: {perf['sample_status']}\n"
        f"- **Total Signals Scanned**: {perf['total_signals']}\n"
        f"- **Trades Executed (Paper)**: {perf['total_trades']}\n"
        f"- **Gross P&L**: ₹{perf['gross_pnl']:.2f}\n"
        f"- **Total Transaction Costs**: ₹{perf['total_costs']:.2f}\n"
        f"- **Net P&L**: ₹{perf['net_pnl']:.2f}\n"
        f"- **Net Win Rate**: {perf['win_rate_net']}%\n"
        f"- **Net Profit Factor**: {perf['net_profit_factor']:.2f}\n"
        f"- **Net Expectancy**: ₹{perf['net_expectancy']:.2f}\n"
        f"- **Max Drawdown (Net)**: ₹{perf['net_max_drawdown']:.2f}\n"
        f"- **Sharpe Ratio**: {perf['net_sharpe']:.2f}\n\n"
        f"## Market Segments\n"
    )
    for k, v in perf.get("segment_markets", {}).items():
        rep += f"- **{k}**: {v['count']} trades | Win Rate: {v['win_rate_net']}% | Net: ₹{v['net_pnl']:.2f}\n"
        
    rep += "\n## Best Setup Breakdowns\n"
    for k, v in breakdown.get("setups", {}).items():
        rep += f"- **{k}**: {v['count']} trades | Win Rate: {v['win_rate']}% | Net: ₹{v['net_pnl']:.2f}\n"
        
    return {"status": "success", "report": rep}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("API_PORT", os.environ.get("PORT", 8000)))
    print(f"Starting API server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
