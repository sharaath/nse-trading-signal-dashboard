import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "PAPER"

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock, patch

from db.database import Base
from db.models import PaperTrade, SignalHistory, DataQuality, SystemSettings, ScanLog
from worker.main import run_market_scan, perform_market_audit, check_daily_risk_limits
from paper_trading.engine import PaperTradingManager

TEST_DATABASE_URL = "sqlite:///:memory:"
engine_test = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)

def test_paper_session_data_stale_and_restore_block():
    db = TestingSessionLocal()
    
    # 1. Stale Data quality record
    db.add(DataQuality(
        provider="fyers",
        symbol="NIFTY",
        data_status="STALE",
        trading_eligible=False,
        age_seconds=120.0
    ))
    db.commit()
    
    # Check that new entries are blocked due to stale data
    dq = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
    assert dq.trading_eligible is False

    # 2. Restore data freshness
    dq.data_status = "LIVE"
    dq.trading_eligible = True
    db.commit()
    
    dq_restore = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
    assert dq_restore.trading_eligible is True
    db.close()

def test_daily_risk_limits():
    db = TestingSessionLocal()
    
    # Test Max Daily Trades parameter block (Limit 3)
    db.add(SystemSettings(key="max_daily_trades", value="3"))
    db.commit()
    
    # Seed 3 closed trades
    for i in range(3):
        db.add(PaperTrade(
            symbol="NIFTY",
            qty=75,
            entry_price=100.0,
            pnl=100.0,
            status="CLOSED",
            entry_time=datetime.now(timezone.utc)
        ))
    db.commit()
    
    allowed, reason = check_daily_risk_limits(db)
    assert allowed is False
    assert "Max daily trades" in reason
    db.close()

def test_sensex_options_disabled():
    db = TestingSessionLocal()
    
    # SENSEX audit should set trading_eligible=False in LIVE/PAPER modes
    with patch("worker.main.get_data_provider") as mock_prov:
        prov = MagicMock()
        prov.__class__.__name__ = "RealTimeMarketDataProvider"
        prov.is_connected = True
        prov.websocket_connected = True
        mock_prov.return_value = prov
        
        perform_market_audit(db)
        
        dq_sensex = db.query(DataQuality).filter(DataQuality.symbol == "SENSEX").first()
        assert dq_sensex is not None
        assert dq_sensex.trading_eligible is False
    db.close()

def test_scan_logs_writing():
    db = TestingSessionLocal()
    
    db.add(ScanLog(
        market="NIFTY",
        spot_price=24200.0,
        data_age=2.0,
        data_latency=120.0,
        strategy_score=85.0,
        ml_probability=75.0,
        trade_quality=90.0,
        direction="BUY_CALL",
        option_confirmation="STRONG",
        selected_strike="NIFTY 24200 CE",
        strike_score=80.0,
        signal="BUY"
    ))
    db.commit()
    
    log = db.query(ScanLog).first()
    assert log is not None
    assert log.market == "NIFTY"
    assert log.signal == "BUY"
    db.close()
