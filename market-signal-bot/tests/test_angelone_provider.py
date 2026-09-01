import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "SIMULATION"

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from signals.providers import get_data_provider
from signals.providers.angelone_provider import AngelOneMarketDataProvider
from scripts.angel_auto_login import update_env_file, generate_angel_session

def test_angelone_provider_unconfigured():
    with patch.dict(os.environ, {
        "ANGEL_API_KEY": "",
        "ANGEL_CLIENT_CODE": "",
        "ANGEL_JWT_TOKEN": "",
        "ANGEL_FEED_TOKEN": "",
        "ANGEL_PIN": "",
        "ANGEL_TOTP_KEY": ""
    }):
        provider = AngelOneMarketDataProvider()
        assert provider.is_connected is False
        assert provider.websocket_connected is False
        assert provider.get_source_type() == "DATA UNAVAILABLE"
        assert provider.get_history("NIFTY").empty
        assert provider.get_option_chain("NIFTY") == {}

def test_angelone_provider_mock_configured():
    with patch.dict(os.environ, {
        "ANGEL_API_KEY": "test_api_key",
        "ANGEL_CLIENT_CODE": "A12345",
        "ANGEL_JWT_TOKEN": "test_jwt",
        "ANGEL_FEED_TOKEN": "test_feed"
    }):
        provider = AngelOneMarketDataProvider()
        assert provider.is_connected is True
        assert provider.websocket_connected is True
        assert provider.get_source_type() == "LIVE"
        
        # Test get_history in fallback/simulation mode
        df = provider.get_history("NIFTY")
        assert not df.empty
        assert len(df) == 50
        assert "Close" in df.columns

def test_angelone_provider_factory_resolution():
    with patch.dict(os.environ, {"MARKET_DATA_PROVIDER": "angelone", "ANGEL_API_KEY": "test"}):
        provider = get_data_provider()
        assert isinstance(provider, AngelOneMarketDataProvider)

def test_angelone_provider_live_candle_mock():
    with patch.dict(os.environ, {
        "ANGEL_API_KEY": "test_api_key",
        "ANGEL_CLIENT_CODE": "A12345",
        "ANGEL_JWT_TOKEN": "test_jwt",
        "ANGEL_FEED_TOKEN": "test_feed"
    }):
        provider = AngelOneMarketDataProvider()
        mock_smart = MagicMock()
        mock_smart.getCandleData.return_value = {
            "status": True,
            "data": [
                ["2026-08-31T09:15:00+05:30", 24200.0, 24250.0, 24190.0, 24230.0, 15000],
                ["2026-08-31T09:30:00+05:30", 24230.0, 24280.0, 24210.0, 24260.0, 18000]
            ]
        }
        provider.smart_client = mock_smart
        df = provider.get_history("NIFTY")
        assert len(df) == 2
        assert df.iloc[-1]["Close"] == 24260.0

def test_angel_auto_login_env_update():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        env_file.write_text("MARKET_DATA_PROVIDER=angelone\nANGEL_JWT_TOKEN=old_jwt\n", encoding="utf-8")
        
        success = update_env_file(env_file, "new_jwt_abc", "new_feed_xyz")
        assert success is True
        
        content = env_file.read_text(encoding="utf-8")
        assert "ANGEL_JWT_TOKEN=new_jwt_abc\n" in content
        assert "ANGEL_FEED_TOKEN=new_feed_xyz\n" in content
        assert "old_jwt" not in content

def test_angel_generate_session_mock():
    jwt, feed = generate_angel_session(
        api_key="key",
        client_code="code",
        pin="1234",
        totp_key="JBSWY3DPEHPK3PXP",
        mock_jwt="mock_jwt_123",
        mock_feed="mock_feed_456"
    )
    assert jwt == "mock_jwt_123"
    assert feed == "mock_feed_456"

def test_angel_generate_session_validation():
    with pytest.raises(ValueError):
        generate_angel_session("", "code", "1234", "TOTPKEY")
        
    with pytest.raises(ValueError):
        generate_angel_session("key", "code", "", "TOTPKEY")
