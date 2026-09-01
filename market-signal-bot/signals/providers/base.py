import pandas as pd
from abc import ABC, abstractmethod
from typing import Dict, Any

class MarketDataProvider(ABC):
    @abstractmethod
    def get_history(self, symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        """Fetch historical price data as a Pandas DataFrame with OHLCV columns."""
        pass

    @abstractmethod
    def get_option_chain(self, symbol: str) -> Dict[str, Any]:
        """Fetch option chain for a given symbol."""
        pass

    @abstractmethod
    def get_source_type(self) -> str:
        """Returns 'LIVE', 'PAPER/MOCK', or 'DATA UNAVAILABLE' depending on connection status."""
        pass
