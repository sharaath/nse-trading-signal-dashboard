from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import List, Optional

from db.database import get_db, SessionLocal
from db.models import SignalHistory, UserSubscription, StrategyState, init_db

app = FastAPI(title="MarketSignalBot API", version="1.0.0")

# Enable CORS for React Frontend dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup DB tables initialization
@app.on_event("startup")
def startup_event():
    init_db()

# Pydantic Schemas
class StrategyToggle(BaseModel):
    strategy_name: str
    is_enabled: bool

class SignalResponse(BaseModel):
    id: int
    symbol: str
    price: float
    signal: str
    confidence: float
    reason: str
    indicators: str
    timestamp: datetime

    class Config:
        from_attributes = True

# --- API ENDPOINTS ---

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database_connected": True
    }

@app.get("/signals/latest", response_model=List[SignalResponse])
def get_latest_signals(db: Session = Depends(get_db)):
    # Group by symbol and get the latest record
    symbols = ["^NSEI", "^BSESN", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"]
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
        # Create a new record if it doesn't exist
        strategy = StrategyState(strategy_name=payload.strategy_name, is_enabled=payload.is_enabled)
        db.add(strategy)
    else:
        strategy.is_enabled = payload.is_enabled
        
    db.commit()
    return {"status": "success", "strategy": payload.strategy_name, "is_enabled": payload.is_enabled}
