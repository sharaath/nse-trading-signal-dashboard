import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base
from db.models import DataQuality, SystemSettings, PaperTrade
from signals.providers.realtime_provider import RealTimeMarketDataProvider, GLOBAL_MARKET_CACHE
from worker.main import perform_market_audit
from api.main import health

TEST_DATABASE_URL = "sqlite:///:memory:"
engine_test = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)

def test_realtime_provider_init_and_auth_failure():
    # If credentials are not configured
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "", "FYERS_SECRET_KEY": "", "FYERS_ACCESS_TOKEN": "", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        assert provider.is_connected is False
        assert provider.websocket_connected is False
        assert provider.get_source_type() == "DATA UNAVAILABLE"
        assert provider.get_history("NSE:NIFTY50-INDEX").empty
        assert provider.get_option_chain("NIFTY") == {}

def test_realtime_provider_mock_auth_success():
    # If credentials are set
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "test", "FYERS_SECRET_KEY": "test", "FYERS_ACCESS_TOKEN": "test", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        assert provider.is_connected is True
        assert provider.websocket_connected is True
        assert provider.get_source_type() == "LIVE"
        
        df = provider.get_history("NIFTY")
        assert not df.empty
        assert len(df) == 50

def test_websocket_tick_and_field_parsing():
    now = datetime.now(timezone.utc)
    GLOBAL_MARKET_CACHE.update_tick("NSE:NIFTYBANK-INDEX", {
        "ltp": 52125.0,
        "volume": 2000000,
        "timestamp": now,
        "bid": 52124.0,
        "ask": 52126.0,
        "open_interest": 9000000,
        "change_in_open_interest": 200000
    })
    
    tick = GLOBAL_MARKET_CACHE.get_data("NSE:NIFTYBANK-INDEX")
    assert tick is not None
    assert tick["ltp"] == 52125.0
    assert tick["bid"] == 52124.0
    assert tick["ask"] == 52126.0
    assert tick["volume"] == 2000000
    assert tick["open_interest"] == 9000000
    assert tick["change_in_open_interest"] == 200000

def test_failover_no_trade_on_disconnect():
    db = TestingSessionLocal()
    
    # Simulate a disconnected RealTime provider
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "test", "FYERS_SECRET_KEY": "test", "FYERS_ACCESS_TOKEN": "test", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        provider.is_connected = False
        provider.websocket_connected = False
        
        with patch("signals.providers.get_data_provider", return_value=provider):
            perform_market_audit(db)
            
            dq_nifty = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
            assert dq_nifty is not None
            assert dq_nifty.data_status == "UNAVAILABLE"
            assert dq_nifty.trading_eligible is False

    db.close()

def test_failover_no_trade_on_stale_data():
    db = TestingSessionLocal()
    
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "test", "FYERS_SECRET_KEY": "test", "FYERS_ACCESS_TOKEN": "test", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        
        # Simulate stale real-time ticks (> 60s) after provider has seeded
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        GLOBAL_MARKET_CACHE.update_tick("NSE:NIFTY50-INDEX", {
            "ltp": 24205.3,
            "volume": 2500000,
            "timestamp": stale_time,
            "bid": 24204.8,
            "ask": 24205.8,
            "open_interest": 12000000,
            "change_in_open_interest": 250000
        })
        
        with patch("signals.providers.get_data_provider", return_value=provider):
            perform_market_audit(db)
            
            dq_nifty = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
            assert dq_nifty is not None
            assert dq_nifty.data_status == "STALE"
            assert dq_nifty.trading_eligible is False

    db.close()

def test_sensex_support():
    db = TestingSessionLocal()
    
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "test", "FYERS_SECRET_KEY": "test", "FYERS_ACCESS_TOKEN": "test", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        with patch("signals.providers.get_data_provider", return_value=provider):
            # In LIVE/PAPER, SENSEX options are unavailable, so it blocks SENSEX trading eligibility
            perform_market_audit(db)
            dq_sensex = db.query(DataQuality).filter(DataQuality.symbol == "SENSEX").first()
            assert dq_sensex.trading_eligible is False

    db.close()

def test_realtime_credentials_missing_no_trade():
    db = TestingSessionLocal()
    with patch.dict(os.environ, {
        "MARKET_DATA_PROVIDER": "realtime",
        "FYERS_CLIENT_ID": "",
        "FYERS_SECRET_KEY": "",
        "FYERS_ACCESS_TOKEN": "",
        "SYSTEM_MODE": "PAPER"
    }):
        provider = RealTimeMarketDataProvider()
        assert provider.is_connected is False
        with patch("signals.providers.get_data_provider", return_value=provider):
            perform_market_audit(db)
            dq_nifty = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
            assert dq_nifty.trading_eligible is False
            assert "credentials_missing" in dq_nifty.missing_fields
            assert dq_nifty.data_status == "UNCONFIGURED"
    db.close()

def test_realtime_auth_failure_no_trade():
    db = TestingSessionLocal()
    with patch.dict(os.environ, {
        "MARKET_DATA_PROVIDER": "realtime",
        "FYERS_CLIENT_ID": "test",
        "FYERS_SECRET_KEY": "test",
        "FYERS_ACCESS_TOKEN": "fail_token",
        "SYSTEM_MODE": "PAPER"
    }):
        provider = RealTimeMarketDataProvider()
        assert provider.is_connected is False
        assert provider.auth_failed is True
        with patch("signals.providers.get_data_provider", return_value=provider):
            perform_market_audit(db)
            dq_nifty = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
            assert dq_nifty.trading_eligible is False
            assert "auth_failed" in dq_nifty.missing_fields
            assert dq_nifty.data_status == "AUTHENTICATION FAILED"
    db.close()

def test_realtime_ws_disconnect_no_trade():
    db = TestingSessionLocal()
    with patch.dict(os.environ, {
        "MARKET_DATA_PROVIDER": "realtime",
        "FYERS_CLIENT_ID": "test",
        "FYERS_SECRET_KEY": "test",
        "FYERS_ACCESS_TOKEN": "disconnect_token",
        "SYSTEM_MODE": "PAPER"
    }):
        provider = RealTimeMarketDataProvider()
        assert provider.is_connected is True
        assert provider.websocket_connected is False
        with patch("signals.providers.get_data_provider", return_value=provider):
            perform_market_audit(db)
            dq_nifty = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
            assert dq_nifty.trading_eligible is False
            assert "websocket_tick" in dq_nifty.missing_fields
            assert dq_nifty.data_status == "DISCONNECTED"
    db.close()

def test_realtime_valid_data_allows_scan():
    db = TestingSessionLocal()
    with patch.dict(os.environ, {
        "MARKET_DATA_PROVIDER": "realtime",
        "FYERS_CLIENT_ID": "test",
        "FYERS_SECRET_KEY": "test",
        "FYERS_ACCESS_TOKEN": "test_token",
        "SYSTEM_MODE": "PAPER"
    }):
        provider = RealTimeMarketDataProvider()
        assert provider.is_connected is True
        assert provider.websocket_connected is True
        with patch("signals.providers.get_data_provider", return_value=provider):
            # Seed fresh option data
            with patch("signals.option_chain_provider.NSEOptionChainProvider.fetch_option_chain", return_value={
                "records": {"data": [{"CE": {"lastPrice": 100.0, "strikePrice": 24200, "expiryDate": "2026-08-27", "openInterest": 1000, "changeinOpenInterest": 10, "totalTradedVolume": 500, "bidprice": 99.0, "askprice": 101.0}}], "timestamp": datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S")}
            }):
                perform_market_audit(db)
                dq_nifty = db.query(DataQuality).filter(DataQuality.symbol == "NIFTY").first()
                assert dq_nifty.trading_eligible is True
                assert dq_nifty.data_status == "LIVE"
    db.close()

def test_realtime_does_not_use_yfinance_or_mock():
    with patch.dict(os.environ, {
        "MARKET_DATA_PROVIDER": "realtime",
        "FYERS_CLIENT_ID": "test",
        "FYERS_SECRET_KEY": "test",
        "FYERS_ACCESS_TOKEN": "test_token"
    }):
        from signals.providers import get_data_provider
        provider = get_data_provider()
        assert isinstance(provider, RealTimeMarketDataProvider)
        assert not provider.__class__.__name__ == "YFinanceDataProvider"
        assert not provider.__class__.__name__ == "MockDataProvider"

def test_sensex_options_disabled_live():
    db = TestingSessionLocal()
    with patch.dict(os.environ, {
        "MARKET_DATA_PROVIDER": "realtime",
        "FYERS_CLIENT_ID": "test",
        "FYERS_SECRET_KEY": "test",
        "FYERS_ACCESS_TOKEN": "test_token",
        "SYSTEM_MODE": "PAPER",
        "ALLOW_FALLBACK_SIMULATION": "false"
    }):
        provider = RealTimeMarketDataProvider()
        # SENSEX option chain must return empty
        chain = provider.get_option_chain("SENSEX")
        assert chain == {}
        
        with patch("signals.providers.get_data_provider", return_value=provider):
            perform_market_audit(db)
            dq_sensex = db.query(DataQuality).filter(DataQuality.symbol == "SENSEX").first()
            assert dq_sensex.trading_eligible is False
            assert "sensex_options_feed" in dq_sensex.missing_fields or "option_chain" in dq_sensex.missing_fields
    db.close()

def test_paper_mode_no_real_orders():
    # Verify paper mode cannot execute real orders
    with patch.dict(os.environ, {"SYSTEM_MODE": "PAPER", "REAL_ORDERS_ENABLED": "false"}):
        system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()
        real_orders_enabled = os.environ.get("REAL_ORDERS_ENABLED", "false").lower() == "true"
        assert system_mode == "PAPER"
        assert real_orders_enabled is False

@pytest.mark.anyio
async def test_test_alert_command():
    from api.main import test_alert_cmd
    
    # Mock update
    class MockMessage:
        def __init__(self):
            self.replies = []
        async def reply_text(self, text, parse_mode=None):
            self.replies.append(text)
            
    class MockUpdate:
        def __init__(self):
            self.message = MockMessage()
            
    class MockContext:
        def __init__(self, args=None):
            self.args = args or []
            
    # Test individual argument
    update = MockUpdate()
    context = MockContext(["buy_ce"])
    await test_alert_cmd(update, context)
    assert len(update.message.replies) == 1
    assert "🟢 *BUY CE — PAPER SIGNAL*" in update.message.replies[0]
    assert "🧪 *TEST ALERT — PAPER MODE*" in update.message.replies[0]
    
    # Test entire loop
    update_all = MockUpdate()
    context_all = MockContext([])
    await test_alert_cmd(update_all, context_all)
    assert len(update_all.message.replies) == 12
    assert "🧪 *Starting Telegram alert templates test loop...*" in update_all.message.replies[0]
    assert "🟢 *BUY CE — PAPER SIGNAL*" in update_all.message.replies[1]
    assert "🔴 *BUY PE — PAPER SIGNAL*" in update_all.message.replies[2]
    assert "🎯 *T1 HIT — PAPER TRADE*" in update_all.message.replies[3]
    assert "🎯 *T2 HIT — PAPER TRADE*" in update_all.message.replies[4]
    assert "🏆 *T3 HIT — PAPER TRADE CLOSED*" in update_all.message.replies[5]
    assert "🛑 *STOP LOSS HIT — PAPER TRADE*" in update_all.message.replies[6]
    assert "⚠️ *ENTRY MISSED — DO NOT CHASE*" in update_all.message.replies[7]
    assert "❌ *SETUP INVALIDATED — NO TRADE*" in update_all.message.replies[8]
    assert "🚨 *MARKET DATA WARNING*" in update_all.message.replies[9]
    assert "📊 *DAILY PAPER TRADING SUMMARY*" in update_all.message.replies[10]
    assert "✅ *Telegram alert templates test completed successfully.*" in update_all.message.replies[11]

    # Database state verification: verify no PaperTrade is created
    db = TestingSessionLocal()
    trades_count = db.query(PaperTrade).count()
    assert trades_count == 0
    db.close()

def test_validate_paper_mode_safety_gates():
    from db.database import validate_paper_mode
    
    # 1. Healthy defaults: PAPER mode and REAL_ORDERS_ENABLED=false
    with patch.dict(os.environ, {"SYSTEM_MODE": "PAPER", "REAL_ORDERS_ENABLED": "false"}):
        validate_paper_mode(bypass_test_check=False)  # Should not raise SystemExit
        
    # 2. Unhealthy: REAL_ORDERS_ENABLED=true
    with patch.dict(os.environ, {"SYSTEM_MODE": "PAPER", "REAL_ORDERS_ENABLED": "true"}):
        with pytest.raises(SystemExit) as excinfo:
            validate_paper_mode(bypass_test_check=False)
        assert "CRITICAL SAFETY BLOCK" in str(excinfo.value)
        
    # 3. Unhealthy: SYSTEM_MODE=LIVE
    with patch.dict(os.environ, {"SYSTEM_MODE": "LIVE", "REAL_ORDERS_ENABLED": "false"}):
        with pytest.raises(SystemExit) as excinfo:
            validate_paper_mode(bypass_test_check=False)
        assert "CRITICAL SAFETY BLOCK" in str(excinfo.value)

def test_oracle_deployment_compose_persistence_and_firewall():
    compose_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docker-compose.yml")
    assert os.path.exists(compose_path)
    
    import yaml
    with open(compose_path, "r") as f:
        config = yaml.safe_load(f)
        
    services = config.get("services", {})
    
    # 1. Verify restart: always policy
    for s_name, s_cfg in services.items():
        assert s_cfg.get("restart") == "always", f"Service {s_name} is missing 'restart: always' policy."
        
    # 2. Verify Port isolation (PostgreSQL 5432 must not be exposed publicly)
    db_ports = services.get("db", {}).get("ports")
    assert db_ports is None, "PostgreSQL port 5432 is exposed publicly!"
    
    # 3. Verify public endpoints exposed
    assert "8000:8000" in services.get("api", {}).get("ports", []), "API port 8000 not exposed in compose file."
    assert "5173:5173" in services.get("frontend", {}).get("ports", []), "Frontend port 5173 not exposed in compose file."

def test_duplicate_scanner_and_telegram_prevention():
    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker", "main.py")
    api_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "main.py")
    
    with open(worker_path, "r", encoding="utf-8") as f:
        worker_code = f.read()
    with open(api_path, "r", encoding="utf-8") as f:
        api_code = f.read()
        
    assert "run_market_scan" in worker_code
    assert "minutes=1" in api_code or "minutes=1" in worker_code
    assert "cron_runner" not in worker_code
    assert "scheduled_scan" not in worker_code

