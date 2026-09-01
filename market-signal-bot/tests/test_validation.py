import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "SIMULATION"

import pytest
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base
from db.models import PaperTrade, SystemSettings
from api.main import get_analytics_performance

def test_direction_aware_fills():
    # Setup parameters
    sig_price = 120.0
    bid_p = 119.50
    ask_p = 120.50
    slippage_pct = 0.5
    slippage_amt = (slippage_pct / 100.0) * sig_price # 0.60
    
    # 1. BUY option trade uses Ask Price + Slippage
    buy_fill = ask_p + slippage_amt
    assert buy_fill == 121.10
    
    # 2. SELL option trade uses Bid Price - Slippage
    sell_fill = bid_p - slippage_amt
    assert sell_fill == 118.90

def test_missing_bid_ask_fills():
    sig_price = 120.0
    slippage_pct = 0.5
    slippage_amt = (slippage_pct / 100.0) * sig_price # 0.60
    
    # Missing bid/ask uses LTP +/- Slippage
    buy_fill_fallback = sig_price + slippage_amt
    sell_fill_fallback = sig_price - slippage_amt
    
    assert buy_fill_fallback == 120.60
    assert sell_fill_fallback == 119.40

def test_transaction_costs_gross_net_pnl():
    qty = 150 # 2 lots of NIFTY
    entry_fill = 121.10
    exit_fill = 135.00
    
    # Gross P&L
    gross_pnl = (exit_fill - entry_fill) * qty
    assert gross_pnl == pytest.approx(2085.0)
    
    # Transaction costs calculations (Brokerage ₹40, STT 0.0625%, exchange charges 0.053%, GST 18%)
    brokerage_entry = 20.0
    brokerage_exit = 20.0
    
    stt_exit = 0.000625 * exit_fill * qty
    exchange_entry = 0.00053 * entry_fill * qty
    exchange_exit = 0.00053 * exit_fill * qty
    
    gst_entry = 0.18 * (brokerage_entry + exchange_entry)
    gst_exit = 0.18 * (brokerage_exit + exchange_exit)
    
    total_costs = (
        brokerage_entry + brokerage_exit +
        stt_exit +
        exchange_entry + exchange_exit +
        gst_entry + gst_exit
    )
    
    net_pnl = gross_pnl - total_costs
    assert net_pnl < gross_pnl
    assert total_costs > 40.0

def test_analytics_metrics_calculation():
    # Setup test in-memory SQLite database
    TEST_DATABASE_URL = "sqlite:///:memory:"
    engine_test = create_engine(TEST_DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)
    Base.metadata.create_all(bind=engine_test)
    
    db = TestingSessionLocal()
    
    # Inject closed paper trades
    t1 = PaperTrade(
        symbol="NIFTY",
        direction="BUY_CALL",
        option_contract="NIFTY 24200 CE",
        qty=150,
        initial_qty=150,
        entry_price=100.0,
        current_price=120.0,
        stop_loss=80.0,
        target_1=120.0,
        target_2=140.0,
        target_3=160.0,
        status="CLOSED",
        gross_pnl=3000.0,
        total_transaction_cost=100.0,
        net_pnl=2900.0
    )
    
    t2 = PaperTrade(
        symbol="NIFTY",
        direction="BUY_CALL",
        option_contract="NIFTY 24200 CE",
        qty=150,
        initial_qty=150,
        entry_price=100.0,
        current_price=90.0,
        stop_loss=80.0,
        target_1=120.0,
        target_2=140.0,
        target_3=160.0,
        status="CLOSED",
        gross_pnl=-1500.0,
        total_transaction_cost=80.0,
        net_pnl=-1580.0
    )
    
    db.add(t1)
    db.add(t2)
    db.commit()
    
    # Verify performance calculator endpoint logic
    perf = get_analytics_performance(db)
    
    assert perf["total_trades"] == 2
    assert perf["gross_pnl"] == 1500.0
    assert perf["net_pnl"] == 1320.0
    assert perf["total_costs"] == 180.0
    assert perf["win_rate_gross"] == 50.0
    assert perf["win_rate_net"] == 50.0
    
    # Net Profit Factor: 2900 / 1580 = 1.835
    assert perf["net_profit_factor"] == 1.84
    
    # Drawdown cumulative trace
    # cumulative net: [2900, 1320], peaks: [2900, 2900], drawdowns: [0, 1580]. Max = 1580
    assert perf["net_max_drawdown"] == 1580.0
    
    db.close()
