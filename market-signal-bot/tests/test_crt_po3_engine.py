import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from signals.premarket import classify_vix_regime, calculate_premarket_bias
from signals.ict_smc import (
    detect_swings, check_crt_4h_sweep, check_po3_15m_framework,
    detect_mathematical_mss_5m, detect_1m_retest_and_confirmation
)
from signals.engine import calculate_crt_po3_signal
from backtesting.crt_po3_backtester import CRTPO3Backtester

def create_synthetic_data(num_bars: int = 120, base_price: float = 24000.0, trend: str = "flat"):
    """Generates synthetic 1M OHLCV series for testing."""
    times = [datetime(2026, 8, 31, 9, 15, tzinfo=timezone.utc) + timedelta(minutes=i) for i in range(num_bars)]
    np.random.seed(42)
    prices = [base_price]
    for i in range(1, num_bars):
        delta = np.random.normal(0, 3)
        if trend == "bullish":
            delta += 1.5
        elif trend == "bearish":
            delta -= 1.5
        prices.append(max(100.0, prices[-1] + delta))

    highs = [p + abs(np.random.normal(2, 1)) for p in prices]
    lows = [p - abs(np.random.normal(2, 1)) for p in prices]
    opens = [prices[i - 1] if i > 0 else base_price for i in range(num_bars)]
    closes = prices
    volumes = [int(np.random.uniform(500, 2500)) for _ in range(num_bars)]

    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes
    }, index=times)

def test_premarket_scoring_and_vix_regimes():
    """Validates VIX volatility regimes and premarket sentiment logic."""
    # VIX regime checks
    assert classify_vix_regime(11.5) == "LOW"
    assert classify_vix_regime(14.8) == "NORMAL"
    assert classify_vix_regime(21.0) == "HIGH"

    # Bullish bias check
    res_bull = calculate_premarket_bias(
        gift_nifty_change_pct=0.35,
        nasdaq_change_pct=0.50,
        dow_change_pct=0.40,
        vix_value=14.2,
        advances=38,
        declines=12
    )
    assert res_bull["market_bias"] == "BULLISH"
    assert res_bull["vix_regime"] == "NORMAL"
    assert res_bull["breadth_bias"] == "BULLISH"
    assert res_bull["premarket_bull_score"] >= 3

    # Mixed conditions -> NEUTRAL bias (never forces trade)
    res_neutral = calculate_premarket_bias(
        gift_nifty_change_pct=0.20,
        nasdaq_change_pct=-0.40,
        dow_change_pct=0.10,
        vix_value=15.0,
        advances=24,
        declines=26
    )
    assert res_neutral["market_bias"] == "NEUTRAL"

def test_point_in_time_swings_no_lookahead():
    """Validates that a swing at index i requires window future bars before being confirmed."""
    df = create_synthetic_data(num_bars=30)
    window = 3

    # At bar 4, candidate at bar 1 needs 1 + 3 = 4 bars.
    # At bar 2, candidate at bar 1 cannot be confirmed yet!
    highs_at_2, lows_at_2 = detect_swings(df, window=window, up_to_index=2)
    assert len(highs_at_2) == 0
    assert len(lows_at_2) == 0

    highs_at_10, lows_at_10 = detect_swings(df, window=window, up_to_index=10)
    for s in highs_at_10:
        assert s["index"] + window <= 10  # Zero lookahead!

def test_crt_4h_sweep_modes():
    """Validates LIVE_SWEEP (Mode A) vs CONFIRMED_SWEEP (Mode B) behavior."""
    times_4h = [datetime(2026, 8, 30, 9, 15, tzinfo=timezone.utc), datetime(2026, 8, 31, 9, 15, tzinfo=timezone.utc)]
    df_4h = pd.DataFrame({
        "Open": [24500.0, 24550.0],
        "High": [24600.0, 24650.0],
        "Low": [24400.0, 24450.0],
        "Close": [24550.0, 24580.0]
    }, index=times_4h)

    # In LIVE_SWEEP mode: price sweeps above previous 4H high (24600.0)
    current_high = 24620.0
    current_low = 24570.0
    current_price = 24590.0  # Rejected back below 24600.0

    res_live = check_crt_4h_sweep(df_4h, current_high, current_low, current_price, sweep_mode="LIVE_SWEEP")
    assert res_live["sweep_detected"] is True
    assert res_live["status"] == "SWEEP_DETECTED"
    assert res_live["direction"] == "BEARISH"
    assert res_live["sweep_level"] == 24600.0

    # In CONFIRMED_SWEEP mode: requires 4H candle completion
    res_confirmed = check_crt_4h_sweep(df_4h, current_high, current_low, current_price, sweep_mode="CONFIRMED_SWEEP")
    assert res_confirmed["sweep_confirmed"] is True
    assert res_confirmed["status"] == "SWEEP_CONFIRMED"

def test_mandatory_gates_fail_safe():
    """Ensures that failure of ANY mandatory gate immediately returns NO_TRADE."""
    df_1m = create_synthetic_data(num_bars=60)
    
    # Run with empty 4H data -> Gate 1 fails
    res_no_sweep = calculate_crt_po3_signal(
        df_1m=df_1m,
        df_4h=pd.DataFrame(),  # No 4H data
        force_session_valid=True
    )
    assert res_no_sweep["status"] == "NO_TRADE"
    assert res_no_sweep["failed_gate"] == "GATE_1_4H_SWEEP"
    assert res_no_sweep["mandatory_gates_passed"] is False

    # Run outside session -> Gate 7 fails
    res_outside_session = calculate_crt_po3_signal(
        df_1m=df_1m,
        current_time=datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc),  # 11:30 PM IST
        force_session_valid=False
    )
    assert res_outside_session["status"] == "NO_TRADE"
    assert res_outside_session["failed_gate"] == "GATE_7_SESSION"

def test_statutory_costs_and_backtester():
    """Validates the transaction cost calculations and backtester execution."""
    tester = CRTPO3Backtester(symbol="NIFTY", lot_size=50)
    costs = tester.calculate_statutory_costs(entry_price=150.0, exit_price=200.0, qty=50)

    assert costs["brokerage"] == 40.0  # ₹20 * 2
    assert costs["stt"] > 0.0  # STT charged on sell
    assert costs["gst"] > 0.0  # GST on brokerage + turnover
    assert costs["total_costs"] > 40.0

    df_1m = create_synthetic_data(num_bars=100, trend="bullish")
    results = tester.run_backtest(
        df_1m=df_1m,
        holding_periods=[1, 3, 5],
        slippages=[0.001, 0.005]
    )
    assert "baseline_metrics" in results
    assert "parameter_matrix" in results
    assert results["total_bars_tested"] == 100
