import os
import requests
import time
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from signals.greeks import calculate_greeks, find_implied_volatility

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
        Enforces strict system mode checks. SENSEX simulation is blocked in LIVE/PAPER.
        """
        symbol = symbol.upper().replace("^", "")
        if symbol == "NSEI" or symbol == "NIFTY50":
            symbol = "NIFTY"
        elif symbol == "NSEBANK":
            symbol = "BANKNIFTY"
        elif symbol in ["BSESN", "SENSEX"]:
            symbol = "SENSEX"

        system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()

        if symbol == "SENSEX":
            if system_mode == "SIMULATION":
                logger.info("Routing BSE SENSEX query to simulated option chain provider.")
                return self._generate_fallback_option_chain(symbol)
            else:
                logger.warning("BSE SENSEX live options data is unavailable (unauthorized / no feed connected).")
                raise ValueError("SENSEX options data unavailable. Legitimate BSE/broker options feed required.")

        if system_mode == "SIMULATION":
            return self._generate_fallback_option_chain(symbol)

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

        # In LIVE or PAPER mode, do not fallback to simulation unless explicitly requested
        is_realtime = os.environ.get("MARKET_DATA_PROVIDER", "yfinance").lower() == "realtime"
        allow_fallback = os.environ.get("ALLOW_FALLBACK_SIMULATION", "false").lower() == "true" and not is_realtime
        if allow_fallback:
            logger.info(f"Using simulated option chain payload for {symbol} (NSE live API fallback).")
            return self._generate_fallback_option_chain(symbol)
        
        raise ValueError(f"Market options data feed for {symbol} is currently unavailable.")

    def get_full_chain(self, symbol: str = "NIFTY") -> Dict[str, Any]:
        """
        Parses full option chain (all strikes) for NIFTY, BANKNIFTY, or SENSEX with
        CE/PE LTP, Chng%, OI, Volume, spot_price, atm_strike, and computed Greeks.
        """
        symbol = symbol.upper().replace("^", "")
        if symbol == "NSEI":
            symbol = "NIFTY"
        elif symbol == "NSEBANK":
            symbol = "BANKNIFTY"
        elif symbol == "BSESN":
            symbol = "SENSEX"

        raw_data = self.fetch_option_chain(symbol)
        data_source = raw_data.get("data_source", "live")
        records = raw_data.get("records", {})
        spot_price = float(records.get("underlyingValue", 0.0) or (24200.0 if symbol == "NIFTY" else (52000.0 if symbol == "BANKNIFTY" else 79000.0)))

        if "NIFTY" in symbol and "BANK" not in symbol:
            step = 50
        elif "SENSEX" in symbol:
            step = 100
        else:
            step = 100

        atm_strike = int(round(spot_price / step) * step)

        expiry_dates = records.get("expiryDates", [])
        expiry_str = expiry_dates[0] if expiry_dates else ""
        
        # Calculate time to expiry in years
        rate = 0.07  # 7% Indian risk-free rate
        now = datetime.now(timezone.utc)
        
        try:
            if expiry_str:
                # e.g., "27-Aug-2026"
                expiry_dt = datetime.strptime(expiry_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
                # Expiry at 3:30 PM IST (10:00 AM UTC)
                expiry_dt = expiry_dt.replace(hour=10, minute=0, second=0)
            else:
                expiry_dt = now + timedelta(days=4)
        except Exception:
            expiry_dt = now + timedelta(days=4)
            
        time_to_expiry_years = max(1e-5, (expiry_dt - now).total_seconds() / (365.25 * 24.0 * 3600.0))

        rows = records.get("data", [])
        formatted_chain = []

        for row in rows:
            strike = row.get("strikePrice")
            if not strike:
                continue

            ce = row.get("CE", {}) or {}
            pe = row.get("PE", {}) or {}

            ce_ltp = float(ce.get("lastPrice", 0.0) or 0.0)
            pe_ltp = float(pe.get("lastPrice", 0.0) or 0.0)

            ce_bid = float(ce.get("bidprice", 0.0) or 0.0)
            ce_ask = float(ce.get("askprice", 0.0) or 0.0)
            ce_oi_change = int(ce.get("changeinOpenInterest", 0) or 0)

            pe_bid = float(pe.get("bidprice", 0.0) or 0.0)
            pe_ask = float(pe.get("askprice", 0.0) or 0.0)
            pe_oi_change = int(pe.get("changeinOpenInterest", 0) or 0)

            # Calculate Greeks for Calls
            ce_iv = 0.15
            ce_delta = 0.0
            ce_gamma = 0.0
            ce_theta = 0.0
            ce_vega = 0.0
            
            if ce_ltp > 0:
                ce_iv = find_implied_volatility(ce_ltp, spot_price, strike, time_to_expiry_years, rate, "CE")
                greeks = calculate_greeks(spot_price, strike, time_to_expiry_years, rate, ce_iv, "CE")
                ce_delta = greeks["delta"]
                ce_gamma = greeks["gamma"]
                ce_theta = greeks["theta"]
                ce_vega = greeks["vega"]

            # Calculate Greeks for Puts
            pe_iv = 0.15
            pe_delta = 0.0
            pe_gamma = 0.0
            pe_theta = 0.0
            pe_vega = 0.0
            
            if pe_ltp > 0:
                pe_iv = find_implied_volatility(pe_ltp, spot_price, strike, time_to_expiry_years, rate, "PE")
                greeks = calculate_greeks(spot_price, strike, time_to_expiry_years, rate, pe_iv, "PE")
                pe_delta = greeks["delta"]
                pe_gamma = greeks["gamma"]
                pe_theta = greeks["theta"]
                pe_vega = greeks["vega"]

            formatted_chain.append({
                "strike": int(strike),
                "ce_ltp": ce_ltp,
                "ce_bid": ce_bid,
                "ce_ask": ce_ask,
                "ce_oi_change": ce_oi_change,
                "ce_chng_pct": float(ce.get("pChange", 0.0) or ce.get("change", 0.0) or 0.0),
                "ce_oi": int(ce.get("openInterest", 0) or 0),
                "ce_volume": int(ce.get("totalTradedVolume", 0) or 0),
                "ce_iv": round(ce_iv * 100.0, 1),
                "ce_delta": round(ce_delta, 3),
                "ce_gamma": round(ce_gamma, 5),
                "ce_theta": round(ce_theta, 2),
                "ce_vega": round(ce_vega, 3),
                "pe_ltp": pe_ltp,
                "pe_bid": pe_bid,
                "pe_ask": pe_ask,
                "pe_oi_change": pe_oi_change,
                "pe_chng_pct": float(pe.get("pChange", 0.0) or pe.get("change", 0.0) or 0.0),
                "pe_oi": int(pe.get("openInterest", 0) or 0),
                "pe_volume": int(pe.get("totalTradedVolume", 0) or 0),
                "pe_iv": round(pe_iv * 100.0, 1),
                "pe_delta": round(pe_delta, 3),
                "pe_gamma": round(pe_gamma, 5),
                "pe_theta": round(pe_theta, 2),
                "pe_vega": round(pe_vega, 3),
                "data_source": data_source
            })

        # Sort strikes ascending
        formatted_chain.sort(key=lambda x: x["strike"])

        return {
            "symbol": symbol.upper(),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "expiry_date": expiry_str or (now + timedelta(days=4)).strftime("%d-%b-%Y"),
            "data_source": data_source,
            "chain": formatted_chain
        }

    def _generate_fallback_option_chain(self, symbol: str) -> Dict[str, Any]:
        """Generates realistic evolving option chain snapshots for testing and offline fallback."""
        if symbol == "NIFTY":
            spot_price = 24200.0
            step = 50
        elif symbol == "SENSEX":
            spot_price = 79000.0
            step = 100
        else:
            spot_price = 52000.0
            step = 100

        atm_strike = int(round(spot_price / step) * step)
        strikes = [atm_strike + i * step for i in range(-5, 6)]

        # Initialize persistent fallback state for this symbol if first poll
        if symbol not in self._fallback_state:
            self._fallback_state[symbol] = {}
            for k in strikes:
                ce_init = max(10.0, (spot_price - k) + 150.0 if spot_price > k else 150.0 * (0.8 ** ((k - spot_price)/step)))
                pe_init = max(10.0, (k - spot_price) + 150.0 if k > spot_price else 150.0 * (0.8 ** ((spot_price - k)/step)))
                ce_bid = round(ce_init * 0.9975, 2)
                ce_ask = round(ce_init * 1.0025, 2)
                pe_bid = round(pe_init * 0.9975, 2)
                pe_ask = round(pe_init * 1.0025, 2)
                self._fallback_state[symbol][k] = {
                    "CE": {
                        "lastPrice": round(ce_init, 2),
                        "bidprice": ce_bid,
                        "askprice": ce_ask,
                        "openInterest": int(random.uniform(50000, 200000)),
                        "changeinOpenInterest": int(random.uniform(1000, 5000)),
                        "totalTradedVolume": int(random.uniform(100000, 300000))
                    },
                    "PE": {
                        "lastPrice": round(pe_init, 2),
                        "bidprice": pe_bid,
                        "askprice": pe_ask,
                        "openInterest": int(random.uniform(50000, 200000)),
                        "changeinOpenInterest": int(random.uniform(1000, 5000)),
                        "totalTradedVolume": int(random.uniform(100000, 300000))
                    }
                }
        else:
            # Evolve state via random walk across polls
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
                        curr["bidprice"] = round(new_price * 0.9975, 2)
                        curr["askprice"] = round(new_price * 1.0025, 2)
                        curr["changeinOpenInterest"] = random.randint(5000, 15000)
                        curr["openInterest"] += curr["changeinOpenInterest"]
                        curr["totalTradedVolume"] += random.randint(20000, 80000)
                    else:
                        # Normal random drift (-3% to +4%)
                        pct = random.uniform(-0.03, 0.04)
                        new_price = max(5.0, round(old_price * (1 + pct), 2))
                        curr["lastPrice"] = new_price
                        curr["bidprice"] = round(new_price * 0.9975, 2)
                        curr["askprice"] = round(new_price * 1.0025, 2)
                        curr["changeinOpenInterest"] = random.randint(-2000, 3000)
                        curr["openInterest"] = max(1000, curr["openInterest"] + curr["changeinOpenInterest"])
                        curr["totalTradedVolume"] += random.randint(1000, 5000)

        # Expiry date is next Thursday
        today = datetime.now(timezone.utc)
        days_to_thursday = (3 - today.weekday()) % 7
        if days_to_thursday == 0:
            days_to_thursday = 7
        expiry_dt = today + timedelta(days=days_to_thursday)
        expiry_str = expiry_dt.strftime("%d-%b-%Y")

        records_data = []
        for k in strikes:
            st_state = self._fallback_state[symbol][k]
            records_data.append({
                "strikePrice": k,
                "CE": {
                    "strikePrice": k,
                    "underlying": spot_price,
                    "lastPrice": st_state["CE"]["lastPrice"],
                    "bidprice": st_state["CE"]["bidprice"],
                    "askprice": st_state["CE"]["askprice"],
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
                    "bidprice": st_state["PE"]["bidprice"],
                    "askprice": st_state["PE"]["askprice"],
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
                "expiryDates": [expiry_str],
                "data": records_data
            },
            "filtered": {
                "data": records_data
            }
        }
