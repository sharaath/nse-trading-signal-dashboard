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
        self._fallback_state: Dict[str, Dict[int, Dict[str, Any]]] = {}
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
        """Generates realistic evolving option chain snapshots for testing and offline fallback."""
        spot_price = 24200.0 if symbol == "NIFTY" else 52000.0
        step = 50 if symbol == "NIFTY" else 100
        atm_strike = int(round(spot_price / step) * step)

        strikes = [atm_strike + i * step for i in range(-5, 6)]

        # Initialize persistent fallback state for this symbol if first poll
        if symbol not in self._fallback_state:
            self._fallback_state[symbol] = {}
            for k in strikes:
                ce_init = max(10.0, (spot_price - k) + 150.0 if spot_price > k else 150.0 * (0.8 ** ((k - spot_price)/step)))
                pe_init = max(10.0, (k - spot_price) + 150.0 if k > spot_price else 150.0 * (0.8 ** ((spot_price - k)/step)))
                self._fallback_state[symbol][k] = {
                    "CE": {
                        "lastPrice": round(ce_init, 2),
                        "openInterest": int(random.uniform(50000, 200000)),
                        "changeinOpenInterest": int(random.uniform(1000, 5000)),
                        "totalTradedVolume": int(random.uniform(100000, 300000))
                    },
                    "PE": {
                        "lastPrice": round(pe_init, 2),
                        "openInterest": int(random.uniform(50000, 200000)),
                        "changeinOpenInterest": int(random.uniform(1000, 5000)),
                        "totalTradedVolume": int(random.uniform(100000, 300000))
                    }
                }
        else:
            # Evolve state via random walk across polls
            # ~20% chance to force a fast-moving surge on 1 random strike/type for testing
            should_force_surge = random.random() < 0.20
            surge_strike = random.choice(strikes) if should_force_surge else None
            surge_opt_type = random.choice(["CE", "PE"]) if should_force_surge else None

            for k in strikes:
                if k not in self._fallback_state[symbol]:
                    continue
                for opt_type in ["CE", "PE"]:
                    curr = self._fallback_state[symbol][k][opt_type]
                    old_price = curr["lastPrice"]

                    if should_force_surge and k == surge_strike and opt_type == surge_opt_type:
                        # Spike premium by +10% to +20% with strong positive OI surge
                        pct = random.uniform(0.10, 0.20)
                        new_price = max(5.0, round(old_price * (1 + pct), 2))
                        curr["lastPrice"] = new_price
                        curr["changeinOpenInterest"] = random.randint(5000, 15000)
                        curr["openInterest"] += curr["changeinOpenInterest"]
                        curr["totalTradedVolume"] += random.randint(20000, 80000)
                    else:
                        # Normal random drift (-3% to +4%)
                        pct = random.uniform(-0.03, 0.04)
                        new_price = max(5.0, round(old_price * (1 + pct), 2))
                        curr["lastPrice"] = new_price
                        curr["changeinOpenInterest"] = random.randint(-2000, 3000)
                        curr["openInterest"] = max(1000, curr["openInterest"] + curr["changeinOpenInterest"])
                        curr["totalTradedVolume"] += random.randint(1000, 5000)

        records_data = []
        for k in strikes:
            st_state = self._fallback_state[symbol][k]
            records_data.append({
                "strikePrice": k,
                "CE": {
                    "strikePrice": k,
                    "underlying": spot_price,
                    "lastPrice": st_state["CE"]["lastPrice"],
                    "change": 1.5,
                    "pChange": 1.2,
                    "openInterest": st_state["CE"]["openInterest"],
                    "changeinOpenInterest": st_state["CE"]["changeinOpenInterest"],
                    "totalTradedVolume": st_state["CE"]["totalTradedVolume"],
                    "impliedVolatility": 14.5
                },
                "PE": {
                    "strikePrice": k,
                    "underlying": spot_price,
                    "lastPrice": st_state["PE"]["lastPrice"],
                    "change": -1.2,
                    "pChange": -1.0,
                    "openInterest": st_state["PE"]["openInterest"],
                    "changeinOpenInterest": st_state["PE"]["changeinOpenInterest"],
                    "totalTradedVolume": st_state["PE"]["totalTradedVolume"],
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
