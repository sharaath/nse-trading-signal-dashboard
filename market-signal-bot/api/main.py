import os
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

from db.database import get_db, SessionLocal
from db.models import SignalHistory, UserSubscription, StrategyState, init_db, OptionMomentumHistory
from db.instruments import INSTRUMENTS_REGISTRY, get_grouped_instruments, get_instrument_metadata
from signals.option_chain_provider import NSEOptionChainProvider
from worker.main import run_market_scan, TELEGRAM_BOT_TOKEN, PERSONAL_USE_ONLY

app = FastAPI(title="MarketSignalBot API", version="1.0.0")
chain_provider = NSEOptionChainProvider()

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

# Startup Lifespan Management
@app.on_event("startup")
async def startup_event():
    print("Initializing Database tables...")
    init_db()
    
    # Initialize default strategies if table is empty
    db = SessionLocal()
    if db.query(StrategyState).count() == 0:
        default_strats = ["ema_crossover", "rsi", "macd", "bollinger_bands"]
        for s in default_strats:
            db.add(StrategyState(strategy_name=s, is_enabled=True))
        db.commit()
    db.close()
    
    if PERSONAL_USE_ONLY:
        print("\n" + "="*80)
        print("WARNING: PERSONAL_USE_ONLY is set to true.")
        print("Note that public distribution of trading recommendations in India may require SEBI registration.")
        print("="*80 + "\n")

    # 1. Start APScheduler Background Polling
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_market_scan, 'interval', minutes=15, next_run_time=datetime.now())
    scheduler.start()
    app.state.scheduler = scheduler
    print("Consolidated: Background scanning scheduler started.")
    
    # 2. Start Telegram Bot Async Polling
    if TELEGRAM_BOT_TOKEN:
        tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        tg_app.add_handler(CommandHandler("start", start_cmd))
        tg_app.add_handler(CommandHandler("subscribe", subscribe_cmd))
        tg_app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
        
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        app.state.tg_app = tg_app
        print("Consolidated: Telegram Bot async listener loop started.")

@app.on_event("shutdown")
async def shutdown_event():
    # Stop scheduler
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown()
        print("Consolidated: Background scanner stopped.")
        
    # Stop Telegram Bot
    tg_app = getattr(app.state, "tg_app", None)
    if tg_app:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()
        print("Consolidated: Telegram Bot stopped.")

from db.instruments import get_grouped_instruments, get_instrument_metadata, INSTRUMENTS_REGISTRY

# Pydantic Schemas
class StrategyToggle(BaseModel):
    strategy_name: str
    is_enabled: bool

class SignalResponse(BaseModel):
    id: int
    symbol: str
    instrument_type: str = "STOCK"
    price: float
    signal: str
    confidence: float
    reason: str
    indicators: str
    timestamp: datetime

    class Config:
        from_attributes = True

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

    class Config:
        from_attributes = True

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

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database_connected": True
    }

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
    
    return chain_provider.get_full_chain(sym_clean)

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
        query = query.filter(OptionMomentumHistory.symbol == sym_clean)
        
    records = query.order_by(desc(OptionMomentumHistory.timestamp)).limit(limit).all()
    return records

@app.get("/signals/latest", response_model=List[SignalResponse])
def get_latest_signals(db: Session = Depends(get_db)):
    symbols = list(INSTRUMENTS_REGISTRY.keys())
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
    cutoff = datetime.utcnow() - timedelta(days=days)
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
