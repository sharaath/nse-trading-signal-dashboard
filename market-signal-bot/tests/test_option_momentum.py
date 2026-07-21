import pytest
from signals.option_momentum import OptionMomentumDetector

def test_detect_momentum_positive():
    detector = OptionMomentumDetector(min_pct_change=8.0, strikes_around_atm=3)

    # Snapshot 1
    snapshot1 = {
        "records": {
            "underlyingValue": 24200.0,
            "data": [
                {
                    "strikePrice": 24200,
                    "CE": {
                        "strikePrice": 24200,
                        "underlying": 24200.0,
                        "lastPrice": 100.0,
                        "changeinOpenInterest": 5000,
                        "totalTradedVolume": 10000
                    }
                }
            ]
        }
    }

    # Initial snapshot registration (returns empty alerts as baseline)
    alerts1 = detector.detect_momentum(snapshot1, symbol="NIFTY")
    assert len(alerts1) == 0

    # Snapshot 2: Premium jumps from 100.0 to 115.0 (+15%) with rising OI (+8000)
    snapshot2 = {
        "records": {
            "underlyingValue": 24200.0,
            "data": [
                {
                    "strikePrice": 24200,
                    "CE": {
                        "strikePrice": 24200,
                        "underlying": 24200.0,
                        "lastPrice": 115.0,
                        "changeinOpenInterest": 8000,
                        "totalTradedVolume": 25000
                    }
                }
            ]
        }
    }

    alerts2 = detector.detect_momentum(snapshot2, symbol="NIFTY")
    assert len(alerts2) == 1
    alert = alerts2[0]
    assert alert["symbol"] == "NIFTY"
    assert alert["strike"] == 24200
    assert alert["option_type"] == "CE"
    assert alert["old_premium"] == 100.0
    assert alert["new_premium"] == 115.0
    assert alert["pct_change"] == 15.0
    assert alert["oi_change"] == 8000
    assert alert["data_source"] == "live"

def test_detect_momentum_simulated_tag():
    detector = OptionMomentumDetector(min_pct_change=8.0, strikes_around_atm=3)
    snapshot1 = {
        "data_source": "simulated",
        "records": {
            "underlyingValue": 24200.0,
            "data": [{"strikePrice": 24200, "CE": {"strikePrice": 24200, "underlying": 24200.0, "lastPrice": 100.0, "changeinOpenInterest": 5000, "totalTradedVolume": 10000}}]
        }
    }
    snapshot2 = {
        "data_source": "simulated",
        "records": {
            "underlyingValue": 24200.0,
            "data": [{"strikePrice": 24200, "CE": {"strikePrice": 24200, "underlying": 24200.0, "lastPrice": 115.0, "changeinOpenInterest": 8000, "totalTradedVolume": 25000}}]
        }
    }
    detector.detect_momentum(snapshot1, symbol="NIFTY")
    alerts = detector.detect_momentum(snapshot2, symbol="NIFTY")
    assert len(alerts) == 1
    assert alerts[0]["data_source"] == "simulated"

def test_fallback_option_chain_variance():
    from signals.option_chain_provider import NSEOptionChainProvider
    provider = NSEOptionChainProvider()

    snap1 = provider._generate_fallback_option_chain("NIFTY")
    snap2 = provider._generate_fallback_option_chain("NIFTY")

    assert snap1["data_source"] == "simulated"
    assert snap2["data_source"] == "simulated"

    p1 = snap1["records"]["data"][0]["CE"]["lastPrice"]
    p2 = snap2["records"]["data"][0]["CE"]["lastPrice"]

    # Verify premiums evolve and are not identical static values
    assert p1 != p2 or snap1["records"]["data"][1]["CE"]["lastPrice"] != snap2["records"]["data"][1]["CE"]["lastPrice"]

def test_detect_momentum_ignore_negative_oi_noise():
    detector = OptionMomentumDetector(min_pct_change=8.0, strikes_around_atm=3)

    snapshot1 = {
        "records": {
            "underlyingValue": 24200.0,
            "data": [
                {
                    "strikePrice": 24200,
                    "PE": {
                        "strikePrice": 24200,
                        "underlying": 24200.0,
                        "lastPrice": 100.0,
                        "changeinOpenInterest": 5000,
                        "totalTradedVolume": 10000
                    }
                }
            ]
        }
    }

    detector.detect_momentum(snapshot1, symbol="NIFTY")

    # Snapshot 2: Premium jumps +20%, but OI is negative (-500) -> Noise / Liquidation
    snapshot2 = {
        "records": {
            "underlyingValue": 24200.0,
            "data": [
                {
                    "strikePrice": 24200,
                    "PE": {
                        "strikePrice": 24200,
                        "underlying": 24200.0,
                        "lastPrice": 120.0,
                        "changeinOpenInterest": -500,
                        "totalTradedVolume": 25000
                    }
                }
            ]
        }
    }

    alerts2 = detector.detect_momentum(snapshot2, symbol="NIFTY")
    # Should be rejected because OI change <= 0
    assert len(alerts2) == 0
