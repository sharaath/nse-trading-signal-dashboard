import requests
import time
import random
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nseindia.com"
OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/option-chain",
}

class NSEOptionChainProvider:
    def __init__(self):
        self.session: Optional[requests.Session] = None
        self._init_session()

    def _init_session(self) -> bool:
        """Initializes session by hitting homepage to capture required cookies."""
        try:
            self.session = requests.Session()
            self.session.headers.update(HEADERS)
            res = self.session.get(BASE_URL, timeout=10)
            if res.status_code == 200:
                logger.info("NSE Session cookies initialized successfully.")
                return True
            else:
                logger.warning(f"NSE homepage returned status code {res.status_code}")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize NSE session: {e}")
            return False

    def fetch_option_chain(self, symbol: str = "NIFTY", retries: int = 3) -> Dict[str, Any]:
        """
        Fetches live option chain JSON for NIFTY or BANKNIFTY from NSE API.
        Falls back to simulated fallback payload if rate-limited or blocked.
        """
        symbol = symbol.upper().replace("^", "")
        if symbol == "NSEI":
            symbol = "NIFTY"
        elif symbol == "NSEBANK":
            symbol = "BANKNIFTY"

        url = OPTION_CHAIN_URL.format(symbol=symbol)

        for attempt in range(retries):
            if not self.session:
                self._init_session()

            try:
                response = self.session.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "filtered" in data or "records" in data:
                        data["data_source"] = "live"
                        return data
                elif response.status_code in [401, 403, 429]:
                    logger.warning(f"NSE API returned {response.status_code}. Re-initializing session (Attempt {attempt+1}/{retries})...")
                    time.sleep(1.0)
                    self._init_session()
            except Exception as e:
                logger.warning(f"Error fetching NSE option chain ({symbol}): {e}")
                time.sleep(1.0)

        logger.info(f"Using simulated option chain payload for {symbol} (NSE live API fallback).")
        return self._generate_fallback_option_chain(symbol)

    def _generate_fallback_option_chain(self, symbol: str) -> Dict[str, Any]:
        """Generates realistic option chain snapshot for testing and offline fallback."""
        spot_price = 24200.0 if symbol == "NIFTY" else 52000.0
        step = 50 if symbol == "NIFTY" else 100
        atm_strike = int(round(spot_price / step) * step)

        strikes = [atm_strike + i * step for i in range(-5, 6)]
        records_data = []

        for k in strikes:
            # Call option simulation
            ce_ltp = max(5.0, (spot_price - k) + 150.0 if spot_price > k else 150.0 * (0.8 ** ((k - spot_price)/step)))
            pe_ltp = max(5.0, (k - spot_price) + 150.0 if k > spot_price else 150.0 * (0.8 ** ((spot_price - k)/step)))

            records_data.append({
                "strikePrice": k,
                "CE": {
                    "strikePrice": k,
                    "underlying": spot_price,
                    "lastPrice": round(ce_ltp, 2),
                    "change": round(random.uniform(-5.0, 15.0), 2),
                    "pChange": round(random.uniform(-2.0, 12.0), 2),
                    "openInterest": int(random.uniform(50000, 200000)),
                    "changeinOpenInterest": int(random.uniform(2000, 15000)),
                    "totalTradedVolume": int(random.uniform(100000, 500000)),
                    "impliedVolatility": 14.5
                },
                "PE": {
                    "strikePrice": k,
                    "underlying": spot_price,
                    "lastPrice": round(pe_ltp, 2),
                    "change": round(random.uniform(-5.0, 15.0), 2),
                    "pChange": round(random.uniform(-2.0, 12.0), 2),
                    "openInterest": int(random.uniform(50000, 200000)),
                    "changeinOpenInterest": int(random.uniform(2000, 15000)),
                    "totalTradedVolume": int(random.uniform(100000, 500000)),
                    "impliedVolatility": 14.8
                }
            })

        return {
            "data_source": "simulated",
            "records": {
                "underlyingValue": spot_price,
                "data": records_data
            },
            "filtered": {
                "data": records_data
            }
        }
