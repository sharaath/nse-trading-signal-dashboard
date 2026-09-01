import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Configurable Thresholds
LOW_VIX_THRESHOLD = float(os.environ.get("LOW_VIX_THRESHOLD", 13.0))
HIGH_VIX_THRESHOLD = float(os.environ.get("HIGH_VIX_THRESHOLD", 18.0))
BREADTH_BULL_RATIO = float(os.environ.get("BREADTH_BULL_RATIO", 1.2))
BREADTH_BEAR_RATIO = float(os.environ.get("BREADTH_BEAR_RATIO", 0.8))

def classify_vix_regime(
    vix_value: float,
    low_thresh: float = LOW_VIX_THRESHOLD,
    high_thresh: float = HIGH_VIX_THRESHOLD
) -> str:
    """
    Classifies India VIX into Volatility Regimes:
    - LOW (< low_thresh): Rangebound / small expected moves
    - NORMAL (low_thresh <= vix <= high_thresh): Standard intraday volatility
    - HIGH (> high_thresh): Wide swings / expanded risk & targets
    """
    if vix_value <= 0.0:
        return "NORMAL"
    if vix_value < low_thresh:
        return "LOW"
    elif vix_value > high_thresh:
        return "HIGH"
    return "NORMAL"

def calculate_premarket_bias(
    gift_nifty_change_pct: float = 0.0,
    nasdaq_change_pct: float = 0.0,
    dow_change_pct: float = 0.0,
    vix_value: float = 14.5,
    advances: int = 25,
    declines: int = 25,
    as_of_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Evaluates pre-market macro inputs (9:00 - 9:15 AM IST) into an objective sentiment score.
    Does NOT assume GIFT Nifty green = BUY or red = SELL.
    If conditions are mixed, returns MARKET_BIAS = NEUTRAL (do not force a trade).
    """
    bull_score = 0
    bear_score = 0

    # 1. GIFT Nifty directional component (threshold +-0.15%)
    if gift_nifty_change_pct > 0.15:
        bull_score += 1
    elif gift_nifty_change_pct < -0.15:
        bear_score += 1

    # 2. Nasdaq directional component
    if nasdaq_change_pct > 0.20:
        bull_score += 1
    elif nasdaq_change_pct < -0.20:
        bear_score += 1

    # 3. Dow Jones directional component
    if dow_change_pct > 0.20:
        bull_score += 1
    elif dow_change_pct < -0.20:
        bear_score += 1

    # 4. Market Breadth: Advances vs Declines
    total_breadth = advances + declines
    ad_ratio = (advances / declines) if declines > 0 else (2.0 if advances > 0 else 1.0)
    advance_pct = (advances / total_breadth * 100.0) if total_breadth > 0 else 50.0

    breadth_bias = "NEUTRAL"
    if ad_ratio >= BREADTH_BULL_RATIO:
        bull_score += 1
        breadth_bias = "BULLISH"
    elif ad_ratio <= BREADTH_BEAR_RATIO:
        bear_score += 1
        breadth_bias = "BEARISH"

    # 5. Determine Overall Bias
    if bull_score > bear_score and (bull_score - bear_score) >= 2:
        market_bias = "BULLISH"
    elif bear_score > bull_score and (bear_score - bull_score) >= 2:
        market_bias = "BEARISH"
    else:
        market_bias = "NEUTRAL"

    # 6. Volatility Regime
    vix_regime = classify_vix_regime(vix_value)

    timestamp_str = (as_of_time or datetime.now(timezone.utc)).isoformat()

    return {
        "timestamp": timestamp_str,
        "gift_nifty_change_pct": round(gift_nifty_change_pct, 2),
        "nasdaq_change_pct": round(nasdaq_change_pct, 2),
        "dow_change_pct": round(dow_change_pct, 2),
        "vix_value": round(vix_value, 2),
        "vix_regime": vix_regime,
        "advances": advances,
        "declines": declines,
        "advance_decline_ratio": round(ad_ratio, 2),
        "advance_percentage": round(advance_pct, 1),
        "breadth_bias": breadth_bias,
        "premarket_bull_score": bull_score,
        "premarket_bear_score": bear_score,
        "market_bias": market_bias
    }
