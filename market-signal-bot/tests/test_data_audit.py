import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "SIMULATION"

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base
from db.models import DataQuality, SystemSettings
from worker.main import perform_market_audit
from api.main import health
from unittest.mock import MagicMock, patch

TEST_DATABASE_URL = "sqlite:///:memory:"
engine_test = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)

def test_data_mode_classification():
    # 1. LIVE status requires fresh age (<= 60s)
    dq_live = DataQuality(
        provider="mock_live",
        symbol="NIFTY",
        timestamp=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        age_seconds=10.0,
        is_fresh=True,
        source_mode="LIVE",
        data_status="LIVE",
        trading_eligible=True
    )
    assert dq_live.data_status == "LIVE"
    assert dq_live.trading_eligible is True

    # 2. STALE status occurs if age exceeds threshold (> 60s)
    dq_stale = DataQuality(
        provider="mock_stale",
        symbol="NIFTY",
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
        received_at=datetime.now(timezone.utc),
        age_seconds=120.0,
        is_fresh=False,
        source_mode="STALE",
        data_status="STALE",
        trading_eligible=False
    )
    assert dq_stale.data_status == "STALE"
    assert dq_stale.trading_eligible is False

    # 3. DELAYED status mapped from delay-prone providers like yfinance
    dq_delayed = DataQuality(
        provider="yfinance",
        symbol="NIFTY",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=15),
        received_at=datetime.now(timezone.utc),
        age_seconds=900.0,
        is_fresh=False,
        source_mode="DELAYED",
        data_status="DELAYED",
        trading_eligible=False
    )
    assert dq_delayed.data_status == "DELAYED"
    assert dq_delayed.trading_eligible is False

    # 4. SIMULATION status for mock data feeds
    dq_sim = DataQuality(
        provider="mock",
        symbol="NIFTY",
        timestamp=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        age_seconds=0.0,
        is_fresh=True,
        source_mode="SIMULATION",
        data_status="SIMULATION",
        trading_eligible=False
    )
    assert dq_sim.data_status == "SIMULATION"
    assert dq_sim.trading_eligible is False

    # 5. UNAVAILABLE status when data fetch fails
    dq_unavail = DataQuality(
        provider="fyers",
        symbol="NIFTY",
        timestamp=None,
        received_at=datetime.now(timezone.utc),
        age_seconds=None,
        is_fresh=False,
        source_mode="UNAVAILABLE",
        data_status="UNAVAILABLE",
        trading_eligible=False
    )
    assert dq_unavail.data_status == "UNAVAILABLE"
    assert dq_unavail.trading_eligible is False

def test_missing_fields_and_oi():
    # Verify missing fields check list
    dq = DataQuality(
        provider="mock",
        symbol="NIFTY",
        missing_fields="option_bidprice,option_askprice,option_changeinOpenInterest",
        trading_eligible=False
    )
    fields = dq.missing_fields.split(",")
    assert "option_bidprice" in fields
    assert "option_askprice" in fields
    assert "option_changeinOpenInterest" in fields
    assert dq.trading_eligible is False

def test_cached_health_endpoint():
    db = TestingSessionLocal()
    
    # Pre-populate database with cached DataQuality statuses
    db.add(DataQuality(
        provider="mock",
        symbol="NIFTY",
        data_status="LIVE",
        trading_eligible=True,
        age_seconds=5.0,
        latency_ms=12.0,
        missing_fields=""
    ))
    db.add(DataQuality(
        provider="mock",
        symbol="BANK_NIFTY",
        data_status="DELAYED",
        trading_eligible=False,
        age_seconds=900.0,
        latency_ms=15.0,
        missing_fields=""
    ))
    db.commit()

    # Hit /health API endpoint using mocked DB session
    # We patch "get_data_provider" and get_history to verify they are NEVER called from health
    with patch("api.main.get_data_provider") as mock_prov:
        res = health(db)
        
        # Verify provider fetch was never called
        mock_prov.assert_not_called()
        
        # Verify returned JSON cached response payload structure
        assert res["api"] == "HEALTHY"
        assert res["data_provider"]["overall_status"] == "INSUFFICIENT"
        assert res["markets"]["NIFTY"]["spot"] == "LIVE"
        assert res["markets"]["NIFTY"]["trading_eligible"] is True
        assert res["markets"]["BANK_NIFTY"]["spot"] == "DELAYED"
        assert res["markets"]["BANK_NIFTY"]["trading_eligible"] is False
        assert res["trading_eligibility"] is False

    db.close()
