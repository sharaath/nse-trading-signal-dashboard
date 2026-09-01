import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "SIMULATION"

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from scripts.fyers_auto_login import update_env_file, generate_fyers_token
from signals.providers.realtime_provider import RealTimeMarketDataProvider, GLOBAL_MARKET_CACHE

def test_update_env_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        # Initial write
        env_file.write_text("SOME_VAR=hello\nFYERS_ACCESS_TOKEN=old_token\nOTHER_VAR=world\n", encoding="utf-8")
        
        success = update_env_file(env_file, "new_fresh_token_123")
        assert success is True
        
        content = env_file.read_text(encoding="utf-8")
        assert "FYERS_ACCESS_TOKEN=new_fresh_token_123\n" in content
        assert "SOME_VAR=hello\n" in content
        assert "OTHER_VAR=world\n" in content
        assert "old_token" not in content

def test_generate_fyers_token_mock():
    token = generate_fyers_token(
        client_id="test_id",
        secret_key="test_secret",
        pin="1234",
        totp_key="JBSWY3DPEHPK3PXP",
        mock_token="mock_access_token_999"
    )
    assert token == "mock_access_token_999"

def test_generate_fyers_token_validation():
    with pytest.raises(ValueError):
        generate_fyers_token("", "secret", "1234", "TOTPKEY")
        
    with pytest.raises(ValueError):
        generate_fyers_token("client", "secret", "1234", "")

def test_realtime_provider_switching_and_history():
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "test", "FYERS_SECRET_KEY": "test", "FYERS_ACCESS_TOKEN": "test", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        assert provider._should_connect_live_fyers() is False
        assert provider.websocket_connected is True
        
        # Test get_history with fallback
        df = provider.get_history("NIFTY")
        assert not df.empty
        assert len(df) == 50
        assert "Close" in df.columns

def test_realtime_provider_live_history_mock():
    with patch.dict(os.environ, {"FYERS_CLIENT_ID": "test", "FYERS_SECRET_KEY": "test", "FYERS_ACCESS_TOKEN": "test", "SYSTEM_MODE": "PAPER"}):
        provider = RealTimeMarketDataProvider()
        # Mock a connected fyers_client
        mock_client = MagicMock()
        mock_client.history.return_value = {
            "s": "ok",
            "candles": [
                [1700000000, 24000.0, 24050.0, 23950.0, 24020.0, 50000],
                [1700000900, 24020.0, 24080.0, 24010.0, 24070.0, 60000]
            ]
        }
        provider.fyers_client = mock_client
        df = provider.get_history("NIFTY")
        assert len(df) == 2
        assert df.iloc[-1]["Close"] == 24070.0
