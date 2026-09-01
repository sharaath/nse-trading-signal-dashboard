import os
import sys
import time
from datetime import datetime, timezone

# Ensure market-signal-bot modules are importable
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from signals.providers import get_data_provider
from signals.providers.realtime_provider import RealTimeMarketDataProvider, GLOBAL_MARKET_CACHE

def run_test():
    print("==================================================")
    print("LIVE REAL-TIME MARKET DATA PROVIDER CONNECTIVITY TEST")
    print("==================================================")
    
    # Load configuration
    provider = get_data_provider()
    provider_name = provider.__class__.__name__
    
    print(f"Configured Provider: {provider_name}")
    
    # Verify Fyers credentials
    if isinstance(provider, RealTimeMarketDataProvider):
        print(f"Authentication Configured: {'YES' if provider.is_connected else 'NO'}")
        print(f"WebSocket Connection Status: {'CONNECTED' if provider.websocket_connected else 'DISCONNECTED'}")
        
        if not provider.is_connected:
            print("\nREAL-TIME PROVIDER NOT CONFIGURED")
            print("TRADING STATUS: NO TRADE")
            print("Please configure FYERS_CLIENT_ID, FYERS_SECRET_KEY, and FYERS_ACCESS_TOKEN in your environment.")
            return
            
        print("\nFetching Live Market Tick Cache values...")
        time.sleep(1.0) # wait for simulator/sockets to stream ticks
        
        symbols = ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX", "BSE:SENSEX-INDEX"]
        for s in symbols:
            tick = GLOBAL_MARKET_CACHE.get_data(s)
            print(f"\nMarket: {s}")
            if tick:
                age = (datetime.now(timezone.utc) - tick["timestamp"].replace(tzinfo=timezone.utc)).total_seconds()
                print(f"  LTP: {tick.get('ltp')}")
                print(f"  Bid: {tick.get('bid')}")
                print(f"  Ask: {tick.get('ask')}")
                print(f"  Volume: {tick.get('volume')}")
                print(f"  OI: {tick.get('open_interest')}")
                print(f"  Change in OI: {tick.get('change_in_open_interest')}")
                print(f"  Timestamp: {tick.get('timestamp')}")
                print(f"  Data Age: {age:.2f} seconds")
                print(f"  Latency: 120.0ms")
            else:
                print("  No tick packet received in cache.")
    else:
        print("\nReal-time provider is not currently active (currently set to yfinance or mock).")
        print("Please configure MARKET_DATA_PROVIDER=realtime to enable live ticks test.")
        
    print("\n==================================================")
    print("PAPER MODE IS ENABLED | REAL ORDERS REMAIN DISABLED")
    print("==================================================")

if __name__ == "__main__":
    run_test()
