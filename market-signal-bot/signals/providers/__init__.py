import os
from signals.providers.base import MarketDataProvider
from signals.providers.yfinance_provider import YFinanceDataProvider
from signals.providers.mock_provider import MockDataProvider
from signals.providers.realtime_provider import RealTimeMarketDataProvider

def get_data_provider() -> MarketDataProvider:
    """Factory method to load the active provider via environment configuration."""
    provider_type = os.environ.get("MARKET_DATA_PROVIDER", "yfinance").lower()
    
    if provider_type == "yfinance":
        return YFinanceDataProvider()
    elif provider_type == "mock":
        return MockDataProvider()
    elif provider_type == "realtime":
        return RealTimeMarketDataProvider()
    elif provider_type in ["angelone", "angel", "smartapi"]:
        from signals.providers.angelone_provider import AngelOneMarketDataProvider
        return AngelOneMarketDataProvider()
    else:
        # Backward compatibility for old env variables
        old_val = os.environ.get("DATA_PROVIDER", "yfinance").lower()
        if old_val == "mock":
            return MockDataProvider()
        elif old_val in ["realtime", "broker", "licensed"]:
            return RealTimeMarketDataProvider()
        elif old_val in ["angelone", "angel", "smartapi"]:
            from signals.providers.angelone_provider import AngelOneMarketDataProvider
            return AngelOneMarketDataProvider()
        return YFinanceDataProvider()
