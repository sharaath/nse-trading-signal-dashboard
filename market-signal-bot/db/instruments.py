from enum import Enum
from typing import Dict, Any, List

class InstrumentType(str, Enum):
    STOCK = "STOCK"
    INDEX = "INDEX"

INSTRUMENTS_REGISTRY: Dict[str, Dict[str, Any]] = {
    # --- INDICES ---
    "^NSEI": {
        "symbol": "^NSEI",
        "clean_symbol": "NIFTY",
        "name": "NIFTY 50",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "NSE",
        "country": "India",
        "category": "broad",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "NIFTY Options / Futures / NIFTYBEES ETF",
        "lot_size": 75
    },
    "^BSESN": {
        "symbol": "^BSESN",
        "clean_symbol": "SENSEX",
        "name": "SENSEX",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "BSE",
        "country": "India",
        "category": "broad",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "SENSEX Options / Futures / SENSEXBEES ETF",
        "lot_size": 10
    },
    "^NSEBANK": {
        "symbol": "^NSEBANK",
        "clean_symbol": "BANKNIFTY",
        "name": "BANKNIFTY",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "NSE",
        "country": "India",
        "category": "sectoral",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "BANKNIFTY Options / Futures / BANKBEES ETF",
        "lot_size": 15
    },
    "^CNXIT": {
        "symbol": "^CNXIT",
        "clean_symbol": "NIFTY IT",
        "name": "NIFTY IT",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "NSE",
        "country": "India",
        "category": "sectoral",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "NIFTY IT Options / Futures / ITBEES ETF",
        "lot_size": 25
    },
    "^GSPC": {
        "symbol": "^GSPC",
        "clean_symbol": "S&P 500",
        "name": "S&P 500",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "NYSE/NASDAQ",
        "country": "US",
        "category": "broad",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "S&P 500 E-mini Futures / SPY ETF / VOO",
        "lot_size": 50
    },
    "^DJI": {
        "symbol": "^DJI",
        "clean_symbol": "Dow Jones",
        "name": "Dow Jones (DJIA)",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "NYSE",
        "country": "US",
        "category": "broad",
        "weighting_method": "price-weighted",
        "is_tradable_spot": False,
        "derivative_etf": "Dow Futures / DIA ETF",
        "lot_size": 10
    },
    "^NDX": {
        "symbol": "^NDX",
        "clean_symbol": "Nasdaq 100",
        "name": "Nasdaq 100",
        "instrument_type": InstrumentType.INDEX.value,
        "exchange": "NASDAQ",
        "country": "US",
        "category": "broad",
        "weighting_method": "market-cap",
        "is_tradable_spot": False,
        "derivative_etf": "Nasdaq 100 E-mini Futures / QQQ ETF / MON100 ETF",
        "lot_size": 20
    }
}

def get_instrument_metadata(symbol: str) -> Dict[str, Any]:
    """Retrieves metadata for a symbol or returns default stock fallback."""
    if symbol in INSTRUMENTS_REGISTRY:
        return INSTRUMENTS_REGISTRY[symbol]
    
    # Check normalized symbols
    sym_clean = symbol.replace("^", "").replace(".NS", "").replace(".BO", "")
    for k, meta in INSTRUMENTS_REGISTRY.items():
        if meta["clean_symbol"] == sym_clean:
            return meta

    is_index = symbol.startswith("^") or symbol in ["NIFTY", "SENSEX", "BANKNIFTY", "NIFTYIT", "SPX", "DJIA", "NDX"]
    return {
        "symbol": symbol,
        "clean_symbol": sym_clean,
        "name": sym_clean,
        "instrument_type": InstrumentType.INDEX.value if is_index else InstrumentType.STOCK.value,
        "exchange": "NSE" if ".NS" in symbol or is_index else "NYSE",
        "country": "India" if ".NS" in symbol or is_index else "US",
        "category": "broad" if is_index else "equity",
        "weighting_method": "market-cap" if is_index else "N/A",
        "is_tradable_spot": not is_index,
        "derivative_etf": "Options / Futures / ETF" if is_index else "Spot Shares"
    }

def get_grouped_instruments() -> Dict[str, List[Dict[str, Any]]]:
    """Returns all instruments grouped by type: Indices vs Stocks."""
    indices = []
    stocks = []
    for meta in INSTRUMENTS_REGISTRY.values():
        if meta["instrument_type"] == InstrumentType.INDEX.value:
            indices.append(meta)
        else:
            stocks.append(meta)
    return {"indices": indices, "stocks": stocks}
