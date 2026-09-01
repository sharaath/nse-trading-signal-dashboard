import pandas as pd
import random
from typing import Dict, Any
from signals.providers.base import MarketDataProvider

class MockDataProvider(MarketDataProvider):
    """Simulated/Static provider for localized developments and testing."""
    def get_history(self, symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        # Generates static Mock data
        # Convert interval string for pandas date_range compatibility
        freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
        freq_val = freq_map.get(interval, interval)
        if freq_val.endswith("m"):
            freq_val = freq_val.replace("m", "min")
        dates = pd.date_range(end="2026-08-20", periods=50, freq=freq_val)
        prices = [100.0 + i * 0.5 for i in range(50)]
        df = pd.DataFrame({
            "Open": prices,
            "High": [p * 1.002 for p in prices],
            "Low": [p * 0.998 for p in prices],
            "Close": prices,
            "Volume": [10000] * 50
        }, index=dates)
        return df

    def get_option_chain(self, symbol: str) -> Dict[str, Any]:
        from signals.option_chain_provider import NSEOptionChainProvider
        provider = NSEOptionChainProvider()
        return provider._generate_fallback_option_chain(symbol)

    def get_source_type(self) -> str:
        return "PAPER/MOCK"
