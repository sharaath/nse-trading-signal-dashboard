from abc import ABC, abstractmethod
import yfinance as yf
import pandas as pd

class MarketDataProvider(ABC):
    @abstractmethod
    def get_history(self, symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        """Fetch historical price data as a Pandas DataFrame with OHLCV columns."""
        pass

class YFinanceDataProvider(MarketDataProvider):
    def get_history(self, symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        try:
            # yfinance tickers for indices have prefix '^' (e.g. ^NSEI)
            # Ensure correct format
            df = yf.download(symbol, period=period, interval=interval, progress=False)
            if df.empty:
                return pd.DataFrame()
            # Flatten columns if MultiIndex (common in yfinance download)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.loc[:, ~df.columns.duplicated()]
            return df
        except Exception:
            return pd.DataFrame()
