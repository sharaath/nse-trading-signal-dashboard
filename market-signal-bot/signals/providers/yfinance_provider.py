import yfinance as yf
import pandas as pd
from typing import Dict, Any
from signals.providers.base import MarketDataProvider

class YFinanceDataProvider(MarketDataProvider):
    """Yahoo Finance provider - categorized as PAPER/MOCK or LIVE depending on env config."""
    def get_history(self, symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        try:
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.loc[:, ~df.columns.duplicated()]
            return df
        except Exception:
            return pd.DataFrame()

    def get_option_chain(self, symbol: str) -> Dict[str, Any]:
        # Handled in option_chain_provider.py via YFinance/NSE fallbacks
        from signals.option_chain_provider import NSEOptionChainProvider
        provider = NSEOptionChainProvider()
        return provider.fetch_option_chain(symbol)

    def get_source_type(self) -> str:
        # Categorized as PAPER/MOCK since yfinance can be delayed and is not a licensed direct broker feed
        return "PAPER/MOCK"
