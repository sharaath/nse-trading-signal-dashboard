import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "SIMULATION"

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from bot.main import is_authorized
from worker.main import monitor_active_trades_tick
from api.main import lifespan as api_lifespan

def test_telegram_bot_authorization_whitelist():
    # Mock Update object
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 12345

    # Case 1: Matching whitelist
    os.environ["TELEGRAM_ALLOWED_USERS"] = "12345, 67890"
    assert is_authorized(mock_update) is True

    # Case 2: Non-matching whitelist
    mock_unauth = MagicMock()
    mock_unauth.effective_user.id = 99999
    mock_unauth.effective_chat.id = 99999
    assert is_authorized(mock_unauth) is False

    # Case 3: Fallback to TELEGRAM_CHAT_ID when TELEGRAM_ALLOWED_USERS is empty
    os.environ["TELEGRAM_ALLOWED_USERS"] = ""
    os.environ["TELEGRAM_CHAT_ID"] = "12345"
    assert is_authorized(mock_update) is True
    assert is_authorized(mock_unauth) is False

    # Case 4: No restrictions configured
    os.environ["TELEGRAM_ALLOWED_USERS"] = ""
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    assert is_authorized(mock_unauth) is True

def test_sub_minute_monitor_active_trades():
    # Calling monitor_active_trades_tick should run cleanly without throwing exceptions
    monitor_active_trades_tick()

@pytest.mark.anyio
async def test_api_service_separation():
    # Test API lifespan with delegated worker mode
    os.environ["ENABLE_API_SCANNER"] = "false"
    os.environ["ENABLE_TELEGRAM_IN_API"] = "false"
    
    app = FastAPI()
    # Running under pytest sys.modules still sets scheduler for backwards-compat tests,
    # but tg_app should remain None when ENABLE_TELEGRAM_IN_API is false
    async with api_lifespan(app):
        assert app.state.tg_app is None
