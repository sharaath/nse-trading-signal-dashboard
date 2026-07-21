import pytest
from signals.option_chain_provider import NSEOptionChainProvider
from db.instruments import get_instrument_metadata

def test_get_full_chain():
    provider = NSEOptionChainProvider()
    res = provider.get_full_chain("NIFTY")

    assert res["symbol"] == "NIFTY"
    assert res["spot_price"] > 0
    assert res["atm_strike"] > 0
    assert "data_source" in res
    assert isinstance(res["chain"], list)
    assert len(res["chain"]) > 0

    first = res["chain"][0]
    expected_keys = {"strike", "ce_ltp", "ce_chng_pct", "ce_oi", "ce_volume", "pe_ltp", "pe_chng_pct", "pe_oi", "pe_volume", "data_source"}
    assert expected_keys.issubset(set(first.keys()))

def test_option_profit_calculator_nifty():
    meta = get_instrument_metadata("^NSEI")
    lot_size = meta["lot_size"]  # 75

    entry_premium = 25.50
    target_premium = 31.88
    quantity_lots = 1

    total_shares = quantity_lots * lot_size
    profit_per_lot = round((target_premium - entry_premium) * lot_size, 2)
    total_profit = round(profit_per_lot * quantity_lots, 2)
    total_investment = round(entry_premium * total_shares, 2)
    roi_pct = round(((target_premium - entry_premium) / entry_premium) * 100.0, 2)

    assert lot_size == 75
    assert profit_per_lot == 478.50
    assert total_profit == 478.50
    assert total_investment == 1912.50
    assert roi_pct == 25.02

def test_option_profit_calculator_banknifty():
    meta = get_instrument_metadata("^NSEBANK")
    lot_size = meta["lot_size"]  # 15

    entry_premium = 100.00
    target_premium = 125.00
    quantity_lots = 2

    total_shares = quantity_lots * lot_size
    profit_per_lot = round((target_premium - entry_premium) * lot_size, 2)
    total_profit = round(profit_per_lot * quantity_lots, 2)
    total_investment = round(entry_premium * total_shares, 2)
    roi_pct = round(((target_premium - entry_premium) / entry_premium) * 100.0, 2)

    assert lot_size == 15
    assert profit_per_lot == 375.00
    assert total_profit == 750.00
    assert total_investment == 3000.00
    assert roi_pct == 25.00
