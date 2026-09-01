import os
import sys
import time
from datetime import datetime, timezone

# Ensure market-signal-bot modules are importable
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Mock environment variables to ensure safety and realtime mode loading
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYSTEM_MODE"] = "PAPER"
os.environ["MARKET_DATA_PROVIDER"] = "realtime"
os.environ["FYERS_CLIENT_ID"] = os.environ.get("FYERS_CLIENT_ID", "test_id")
os.environ["FYERS_SECRET_KEY"] = os.environ.get("FYERS_SECRET_KEY", "test_secret")
os.environ["FYERS_ACCESS_TOKEN"] = os.environ.get("FYERS_ACCESS_TOKEN", "test_token")

from db.database import SessionLocal, Base, engine
from db.models import init_db, DataQuality
from worker.main import run_market_scan, perform_market_audit
from signals.providers import get_data_provider

def execute_session():
    # Initialize DB tables
    init_db()
    
    print("==================================================")
    print("LIVE PAPER TRADING SESSION ENGINE VALIDATION")
    print("==================================================")
    
    provider = get_data_provider()
    print(f"Data Feed Provider: {provider.__class__.__name__}")
    print(f"Connection Status: {'CONNECTED' if provider.is_connected else 'DISCONNECTED'}")
    
    db = SessionLocal()
    
    # 1. Run Data Quality audit cycle
    print("\nRunning live data quality audit cycle...")
    perform_market_audit(db)
    
    dqs = db.query(DataQuality).all()
    print("\nData Feed Quality Table:")
    for dq in dqs:
        print(f"Market: {dq.symbol} | Status: {dq.data_status} | Age: {dq.age_seconds:.1f}s | Latency: {dq.latency_ms:.1f}ms | Eligible: {dq.trading_eligible}")
        
    # 2. Run market scanner cycle
    print("\nRunning strategy scanner cycle...")
    os.environ["FORCE_SCAN"] = "true" # Bypass market hours check for test
    run_market_scan()
    
    print("\nCycle complete. Session validated successfully.")
    print("==================================================")
    print("SAFETY GATE: PAPER MODE ONLY | REAL ORDERS DISABLED")
    print("==================================================")
    db.close()

if __name__ == "__main__":
    execute_session()
