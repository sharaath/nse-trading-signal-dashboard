import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "SIMULATION"

import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI
from api.main import SignalResponse, OptionMomentumResponse, IST
from bot.main import lifespan as bot_lifespan
from api.main import lifespan as api_lifespan

def test_pydantic_v2_config():
    # Verify Pydantic V2 model ConfigDict compliance
    assert SignalResponse.model_config.get("from_attributes") is True
    assert OptionMomentumResponse.model_config.get("from_attributes") is True

    # Test serialization/validation
    now = datetime.now(timezone.utc)
    sig_data = {
        "id": 1,
        "symbol": "^NSEI",
        "instrument_type": "INDEX",
        "price": 24200.0,
        "signal": "BUY",
        "confidence": 85.0,
        "reason": "Technical indicators alignment",
        "indicators": "RSI, MACD",
        "strategy_score": 90.0,
        "ml_probability": 72.0,
        "trade_quality_score": 85.0,
        "system_mode": "PAPER",
        "data_source": "yfinance",
        "timestamp": now
    }
    obj = SignalResponse(**sig_data)
    assert obj.id == 1
    assert obj.symbol == "^NSEI"
    assert obj.timestamp == now

def test_timezone_ist_conversions():
    # Verify that ZoneInfo Asia/Kolkata maps to exactly UTC+5:30
    utc_dt = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    ist_dt = utc_dt.astimezone(IST)
    
    assert ist_dt.tzinfo.key == "Asia/Kolkata"
    assert ist_dt.hour == 17
    assert ist_dt.minute == 30
    
    # Verify naive roundtrip conversion behavior used in database queries
    ist_today_start_ist = ist_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    ist_today_start_utc = ist_today_start_ist.astimezone(timezone.utc).replace(tzinfo=None)
    
    # 12:00 UTC = 17:30 IST. The start of the day in IST is 00:00 IST, which is 18:30 UTC of previous day.
    assert ist_today_start_utc.hour == 18
    assert ist_today_start_utc.minute == 30

def test_market_session_hours():
    # Test session logic constraints (9:15 AM - 3:30 PM IST)
    # 1. Mon Aug 24, 2026 10:00 AM IST (Inside session)
    dt_inside = datetime(2026, 8, 24, 10, 0, 0, tzinfo=IST)
    start_time = dt_inside.replace(hour=9, minute=15, second=0, microsecond=0)
    end_time = dt_inside.replace(hour=15, minute=30, second=0, microsecond=0)
    assert start_time <= dt_inside <= end_time
    assert dt_inside.weekday() < 5
    
    # 2. Mon Aug 24, 2026 8:00 AM IST (Outside session - early)
    dt_early = datetime(2026, 8, 24, 8, 0, 0, tzinfo=IST)
    assert not (start_time <= dt_early <= end_time)
    
    # 3. Sat Aug 22, 2026 12:00 PM IST (Outside session - weekend)
    dt_weekend = datetime(2026, 8, 22, 12, 0, 0, tzinfo=IST)
    assert dt_weekend.weekday() >= 5

@pytest.mark.anyio
async def test_fastapi_lifespan_handlers():
    # Test API and Bot lifespan instantiation
    app_api = FastAPI()
    app_bot = FastAPI()
    
    # Verify they execute without throwing errors
    async with api_lifespan(app_api):
        assert app_api.state.scheduler is not None
        
    async with bot_lifespan(app_bot):
        # Bot token is not configured in simulation environment, check safe skip or init
        pass
