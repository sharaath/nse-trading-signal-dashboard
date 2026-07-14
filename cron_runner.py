import yfinance as yf
import pandas as pd
import ta
import urllib.request
import urllib.parse
import os
import json
from datetime import date, timedelta

CACHE_FILE = "last_signals.json"

def get_last_signals():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_current_signals(signals_dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(signals_dict, f)
    except Exception:
        pass

# -------------------------------------------------------------
# TELEGRAM NOTIFICATION HELPER
# -------------------------------------------------------------
def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read()
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return None

# -------------------------------------------------------------
# INDICATORS & SIGNAL LOGIC
# -------------------------------------------------------------
def calculate_indicators(df):
    df = df.copy()
    
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Remove duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]
    
    # Technical Indicators
    df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd_obj = ta.trend.MACD(df['Close'])
    df['MACD'] = macd_obj.macd()
    df['MACD_Signal'] = macd_obj.macd_signal()
    df['MA200'] = df['Close'].rolling(200).mean()
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    
    def get_signal(row):
        if pd.isna(row['RSI']) or pd.isna(row['MACD']) or pd.isna(row['MA200']) or pd.isna(row['Vol_SMA20']):
            return 'HOLD'
        
        is_buy = (row['RSI'] < 40) and (row['MACD'] > row['MACD_Signal']) and (row['Close'] > row['MA200']) and (row['Volume'] > row['Vol_SMA20'])
        is_sell = (row['RSI'] > 65) and (row['MACD'] < row['MACD_Signal'])
        
        if is_buy:
            return 'BUY'
        elif is_sell:
            return 'SELL'
        return 'HOLD'
        
    df['Signal'] = df.apply(get_signal, axis=1)
    return df

# -------------------------------------------------------------
# MAIN CRON SCANNER
# -------------------------------------------------------------
def main():
    # 1. Load credentials from Environment Variables (GitHub Secrets)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("CRITICAL: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables are missing.")
        return
        
    tickers = [
        "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
        "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BHARTIARTL.NS", "BPCL.NS",
        "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS", "DRREDDY.NS",
        "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS",
        "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "INDUSINDBK.NS",
        "INFY.NS", "ITC.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS",
        "LTIM.NS", "M&M.NS", "MARUTI.NS", "NESTLEIND.NS", "NTPC.NS",
        "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SBIN.NS",
        "SUNPHARMA.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS",
        "TECHM.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS"
    ]
    
    print(f"Starting scheduled market scan for {date.today()}...")
    
    # We download 1 year of daily history to ensure MA200 is fully populated
    start_date = date.today() - timedelta(days=365)
    
    last_signals = get_last_signals()
    current_signals = {}
    
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=str(start_date), end=str(date.today() + timedelta(days=1)), progress=False)
            if df.empty or len(df) < 200:
                print(f"Skipping {ticker}: Empty or insufficient data.")
                continue
                
            df = calculate_indicators(df)
            
            latest = df.iloc[-1]
            
            ticker_clean = ticker.split(".")[0]  # E.g. RELIANCE instead of RELIANCE.NS
            price = float(latest['Close'])
            
            today_signal = latest['Signal']
            current_signals[ticker] = today_signal
            
            # Retrieve cached signal
            prev_signal = last_signals.get(ticker, "HOLD")
            
            print(f"[{ticker}] Previous Cached: {prev_signal} -> Today: {today_signal} (Price: Rs.{price:.2f})")
            
            # 2. Caching-based Signal Transition Logic (Prevents double alerting during the day)
            if today_signal != prev_signal:
                if today_signal == "BUY":
                    target_price = price * 1.05
                    stop_loss = price * 0.97
                    msg = f"🟢 *BUY SIGNAL TRIGGERED*\n\n*Ticker:* `{ticker_clean}`\n*Action:* BUY (Market Open / Live)\n*Entry Price:* ₹{price:.2f}\n*Target Price (+5%):* ₹{target_price:.2f}\n*Stop Loss (-3%):* ₹{stop_loss:.2f}\n*Date:* {date.today()}\n\n_Indicators alignment: RSI is low, MACD momentum is positive, volume is high, and price is above MA200._"
                    send_telegram_message(token, chat_id, msg)
                    print(f"Sent BUY alert for {ticker}")
                elif today_signal == "SELL":
                    msg = f"🔴 *SELL SIGNAL TRIGGERED*\n\n*Ticker:* `{ticker_clean}`\n*Action:* SELL / Exit immediately\n*Exit Price:* ₹{price:.2f}\n*Date:* {date.today()}\n\n_Indicators alignment: RSI is overbought or MACD momentum crossover has turned bearish._"
                    send_telegram_message(token, chat_id, msg)
                    print(f"Sent SELL alert for {ticker}")
                    
        except Exception as e:
            print(f"Error evaluating {ticker}: {e}")
            
    # Save the current states for the next run
    save_current_signals(current_signals)
    print("Scan completed successfully.")

if __name__ == "__main__":
    main()
