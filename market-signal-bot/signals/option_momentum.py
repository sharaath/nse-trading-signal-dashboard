import math
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class OptionMomentumDetector:
    def __init__(self, min_pct_change: float = 8.0, strikes_around_atm: int = 3):
        self.min_pct_change = min_pct_change
        self.strikes_around_atm = strikes_around_atm
        # Store snapshots as: { symbol: { "24200_CE": { lastPrice, oiChange, volume, timestamp }, ... } }
        self.previous_snapshots: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def detect_momentum(self, option_chain: Dict[str, Any], symbol: str = "NIFTY") -> List[Dict[str, Any]]:
        """
        Processes option chain payload and returns list of fast-moving option momentum alerts.
        """
        symbol = symbol.upper().replace("^", "")
        if symbol == "NSEI":
            symbol = "NIFTY"
        elif symbol == "NSEBANK":
            symbol = "BANKNIFTY"

        records = option_chain.get("records", {})
        data_rows = records.get("data", [])
        spot_price = float(records.get("underlyingValue", 0.0))

        if not data_rows or spot_price <= 0:
            filtered = option_chain.get("filtered", {})
            data_rows = filtered.get("data", [])
            if data_rows and spot_price <= 0:
                first_item = data_rows[0]
                ce_item = first_item.get("CE", {}) or first_item.get("PE", {})
                spot_price = float(ce_item.get("underlying", 24200.0))

        if spot_price <= 0:
            logger.warning(f"Invalid spot price for {symbol} in option momentum scan.")
            return []

        step = 50 if "NIFTY" in symbol and "BANK" not in symbol else 100
        atm_strike = int(round(spot_price / step) * step)

        min_strike = atm_strike - (self.strikes_around_atm * step)
        max_strike = atm_strike + (self.strikes_around_atm * step)

        current_contracts: Dict[str, Dict[str, Any]] = {}
        detected_alerts: List[Dict[str, Any]] = []

        prev_snapshot = self.previous_snapshots.get(symbol, {})

        data_source = option_chain.get("data_source", "live")

        for row in data_rows:
            strike = row.get("strikePrice")
            if not strike or strike < min_strike or strike > max_strike:
                continue

            for opt_type in ["CE", "PE"]:
                opt_data = row.get(opt_type)
                if not opt_data or not isinstance(opt_data, dict):
                    continue

                last_price = float(opt_data.get("lastPrice", 0.0))
                oi_change = int(opt_data.get("changeinOpenInterest", 0))
                volume = int(opt_data.get("totalTradedVolume", 0))

                if last_price <= 0:
                    continue

                key = f"{strike}_{opt_type}"
                current_contracts[key] = {
                    "strike": strike,
                    "option_type": opt_type,
                    "lastPrice": last_price,
                    "oiChange": oi_change,
                    "volume": volume,
                }

                # Check momentum against previous poll snapshot
                if key in prev_snapshot:
                    prev_item = prev_snapshot[key]
                    old_price = float(prev_item.get("lastPrice", 0.0))

                    if old_price > 0:
                        pct_change = ((last_price - old_price) / old_price) * 100.0

                        # Fast-moving condition:
                        # 1. Premium jump >= min_pct_change (e.g. >= 8.0%)
                        # 2. Confirmed by positive OI buildup (> 0)
                        # 3. Confirmed by active trading volume (> 0)
                        if pct_change >= self.min_pct_change and oi_change > 0 and volume > 0:
                            alert = {
                                "symbol": symbol,
                                "strike": strike,
                                "option_type": opt_type,
                                "contract": f"{symbol} {strike} {opt_type}",
                                "old_premium": old_price,
                                "new_premium": last_price,
                                "pct_change": round(pct_change, 2),
                                "oi_change": oi_change,
                                "volume": volume,
                                "spot_price": spot_price,
                                "data_source": data_source,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                            detected_alerts.append(alert)

        # Update cache for next iteration comparison
        self.previous_snapshots[symbol] = current_contracts
        return detected_alerts
