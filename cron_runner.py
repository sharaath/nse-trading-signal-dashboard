import yfinance as yf
import pandas as pd
import ta
import urllib.request
import urllib.parse
import os
import json
from datetime import date, timedelta, datetime, timezone

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

TRADE_FILE = "active_trades.json"

def get_active_trades():
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_active_trades(trades_dict):
    try:
        with open(TRADE_FILE, "w") as f:
            json.dump(trades_dict, f)
    except Exception:
        pass

INTRADAY_CACHE_FILE = "last_intraday_signals.json"

def get_last_intraday_signals():
    if os.path.exists(INTRADAY_CACHE_FILE):
        try:
            with open(INTRADAY_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_current_intraday_signals(signals_dict):
    try:
        with open(INTRADAY_CACHE_FILE, "w") as f:
            json.dump(signals_dict, f)
    except Exception:
        pass

INTRADAY_TRADE_FILE = "active_intraday_trades.json"

def get_active_intraday_trades():
    if os.path.exists(INTRADAY_TRADE_FILE):
        try:
            with open(INTRADAY_TRADE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_active_intraday_trades(trades_dict):
    try:
        with open(INTRADAY_TRADE_FILE, "w") as f:
            json.dump(trades_dict, f)
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
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()]
    
    df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd_obj = ta.trend.MACD(df['Close'])
    df['MACD'] = macd_obj.macd()
    df['MACD_Signal'] = macd_obj.macd_signal()
    df['MACD_Diff'] = macd_obj.macd_diff()
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

def calculate_intraday_indicators(df):
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()]
    
    df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd_obj = ta.trend.MACD(df['Close'])
    df['MACD'] = macd_obj.macd()
    df['MACD_Signal'] = macd_obj.macd_signal()
    df['MACD_Diff'] = macd_obj.macd_diff()
    df['EMA20'] = ta.trend.EMAIndicator(df['Close'], window=20).ema_indicator()
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    
    def get_signal(row):
        if pd.isna(row['RSI']) or pd.isna(row['MACD']) or pd.isna(row['EMA20']) or pd.isna(row['Vol_SMA20']):
            return 'HOLD'
        
        is_buy = (row['Close'] > row['EMA20']) and (row['RSI'] < 40) and (row['MACD'] > row['MACD_Signal']) and (row['Volume'] > row['Vol_SMA20'])
        is_sell = (row['RSI'] > 65) and (row['MACD'] < row['MACD_Signal']) or (row['Close'] < row['EMA20'])
        
        if is_buy:
            return 'BUY'
        elif is_sell:
            return 'SELL'
        return 'HOLD'
        
    df['Signal'] = df.apply(get_signal, axis=1)
    return df

def get_completed_signal_row(df):
    if len(df) < 2:
        return df.iloc[-1]
        
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    
    is_market_hours = False
    if ist_now.weekday() < 5:
        market_start = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
        if market_start <= ist_now <= market_end:
            is_market_hours = True
            
    if is_market_hours:
        last_row_date = df.index[-1].date()
        if last_row_date == ist_now.date():
            return df.iloc[-2]
            
    return df.iloc[-1]

# -------------------------------------------------------------
# MAIN CRON SCANNER & REPORT GENERATION
# -------------------------------------------------------------
NIFTY_50_TICKERS = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BHARTIARTL.NS", "BPCL.NS",
    "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS",
    "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "INDUSINDBK.NS",
    "INFY.NS", "ITC.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS",
    "LTM.NS", "M&M.NS", "MARUTI.NS", "NESTLEIND.NS", "NTPC.NS",
    "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SBIN.NS",
    "SUNPHARMA.NS", "TATACONSUM.NS", "TMPV.NS", "TATASTEEL.NS", "TCS.NS",
    "TECHM.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS"
]

NIFTY_NEXT_50_TICKERS = [
    "ABB.NS", "ACC.NS", "ADANIENSOL.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS",
    "DMART.NS", "BANKBARODA.NS", "BEL.NS", "BOSCHLTD.NS", "CANBK.NS", "CGPOWER.NS",
    "CHOLAFIN.NS", "COLPAL.NS", "DLF.NS", "GAIL.NS", "HAL.NS", "HAVELLS.NS",
    "ICICIPRULI.NS", "IOC.NS", "IRCTC.NS", "IRFC.NS", "JINDALSTEL.NS", "JIOFIN.NS",
    "LICI.NS", "MUTHOOTFIN.NS", "PIDILITIND.NS", "PFC.NS", "PNB.NS", "RECLTD.NS",
    "SHREECEM.NS", "SIEMENS.NS", "SRF.NS", "TATAELXSI.NS", "TATAPOWER.NS", "TRENT.NS",
    "TVSSMOTOR.NS", "UNITDSPR.NS", "VBL.NS", "ZOMATO.NS", "ZYDUSLIFE.NS"
]

TICKER_NAMES = {
    "ADANIENT": "Adani Enterprises", "ADANIPORTS": "Adani Ports & SEZ", "APOLLOHOSP": "Apollo Hospitals", 
    "ASIANPAINT": "Asian Paints", "AXISBANK": "Axis Bank", "BAJAJ-AUTO": "Bajaj Auto", 
    "BAJFINANCE": "Bajaj Finance", "BAJAJFINSV": "Bajaj Finserv", "BHARTIARTL": "Bharti Airtel", 
    "BPCL": "Bharat Petroleum", "BRITANNIA": "Britannia Industries", "CIPLA": "Cipla", 
    "COALINDIA": "Coal India", "DIVISLAB": "Divi's Laboratories", "DRREDDY": "Dr. Reddy's Laboratories", 
    "EICHERMOT": "Eicher Motors", "GRASIM": "Grasim Industries", "HCLTECH": "HCL Technologies", 
    "HDFCBANK": "HDFC Bank", "HDFCLIFE": "HDFC Life Insurance", "HEROMOTOCO": "Hero MotoCorp", 
    "HINDALCO": "Hindalco Industries", "HINDUNILVR": "Hindustan Unilever", "ICICIBANK": "ICICI Bank", 
    "INDUSINDBK": "IndusInd Bank", "INFY": "Infosys", "ITC": "ITC Limited", "JSWSTEEL": "JSW Steel", 
    "KOTAKBANK": "Kotak Mahindra Bank", "LT": "Larsen & Tourbro", "LTM": "LTIMindtree", 
    "M&M": "Mahindra & Mahindra", "MARUTI": "Maruti Suzuki", "NESTLEIND": "Nestle India", 
    "NTPC": "NTPC Limited", "ONGC": "Oil & Natural Gas Corp", "POWERGRID": "Power Grid Corp", 
    "RELIANCE": "Reliance Industries", "SBILIFE": "SBI Life Insurance", "SBIN": "State Bank of India", 
    "SUNPHARMA": "Sun Pharmaceutical", "TATACONSUM": "Tata Consumer Products", "TMPV": "Tata Motors Passenger", 
    "TATASTEEL": "Tata Steel", "TCS": "Tata Consultancy Services", "TECHM": "Tech Mahindra", 
    "TITAN": "Titan Company", "ULTRACEMCO": "UltraTech Cement", "WIPRO": "Wipro Limited",
    "ABB": "ABB India", "ACC": "ACC Limited", "ADANIENSOL": "Adani Energy Solutions",
    "ADANIGREEN": "Adani Green Energy", "ADANIPOWER": "Adani Power", "AMBUJACEM": "Ambuja Cements",
    "DMART": "Avenue Supermarts", "BANKBARODA": "Bank of Baroda", "BEL": "Bharat Electronics",
    "BOSCHLTD": "Bosch Limited", "CANBK": "Canara Bank", "CGPOWER": "CG Power",
    "CHOLAFIN": "Cholamandalam Finance", "COLPAL": "Colgate-Palmolive", "DLF": "DLF Limited",
    "GAIL": "GAIL India", "HAL": "Hindustan Aeronautics", "HAVELLS": "Havells India",
    "ICICIPRULI": "ICICI Prudential Life", "IOC": "Indian Oil Corp", "IRCTC": "IRCTC",
    "IRFC": "Indian Railway Finance", "JINDALSTEL": "Jindal Steel & Power", "JIOFIN": "Jio Financial Services",
    "LICI": "LIC of India", "MUTHOOTFIN": "Muthoot Finance", "PIDILITIND": "Pidilite Industries",
    "PFC": "Power Finance Corp", "PNB": "Punjab National Bank", "RECLTD": "REC Limited",
    "SHREECEM": "Shree Cement", "SIEMENS": "Siemens Limited", "SRF": "SRF Limited",
    "TATAELXSI": "Tata Elxsi", "TATAPOWER": "Tata Power", "TRENT": "Trent Limited",
    "TVSSMOTOR": "TVS Motor Company", "UNITDSPR": "United Spirits", "VBL": "Varun Beverages",
    "ZOMATO": "Zomato Limited", "ZYDUSLIFE": "Zydus Lifesciences"
}

def calculate_confidence(row, signal_type):
    confidence = 50.0
    if signal_type == "BUY":
        if row['RSI'] < 30:
            confidence += 15.0
        if row['Volume'] > 1.5 * row['Vol_SMA20']:
            confidence += 15.0
        if 'MACD_Diff' in row and row['MACD_Diff'] > 0:
            confidence += 20.0
    elif signal_type == "SELL":
        if row['RSI'] > 75:
            confidence += 15.0
        if row['Volume'] > 1.5 * row['Vol_SMA20']:
            confidence += 15.0
        if 'MACD_Diff' in row and row['MACD_Diff'] < 0:
            confidence += 20.0
    return min(100.0, confidence)

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        raise ValueError(
            "CRITICAL: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables are missing. "
            "Please configure these as Secrets in your GitHub repository settings."
        )
        
    market_index = os.environ.get("MARKET_INDEX", "Nifty 50")
    if market_index == "Nifty 100":
        tickers = NIFTY_50_TICKERS + NIFTY_NEXT_50_TICKERS
    else:
        tickers = NIFTY_50_TICKERS
        
    start_scan_time = datetime.now()
    
    # Determine if it's market hours in IST
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    
    is_market_hours = False
    if ist_now.weekday() < 5:  # Monday to Friday
        market_start = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
        if market_start <= ist_now <= market_end:
            is_market_hours = True
            
    print(f"Starting scheduled market scan for {date.today()} (Market Hours: {is_market_hours})...")
    
    # We download 1 year of daily history to ensure MA200 is fully populated
    start_date = date.today() - timedelta(days=365)
    
    last_signals = get_last_signals()
    active_trades = get_active_trades()
    current_signals = {}
    
    last_intraday_signals = get_last_intraday_signals()
    active_intraday_trades = get_active_intraday_trades()
    current_intraday_signals = {}
    
    failed_scans = 0
    scanned_count = 0
    
    buy_signals_daily_list = []
    sell_signals_daily_list = []
    buy_signals_intra_list = []
    sell_signals_intra_list = []
    
    for ticker in tickers:
        ticker_clean = ticker.split(".")[0]  # E.g. RELIANCE instead of RELIANCE.NS
        stock_name = TICKER_NAMES.get(ticker_clean, ticker_clean)
        
        # --- 1. SWING TRADING SCAN & MONITORING ---
        try:
            df = yf.download(ticker, start=str(start_date), end=str(date.today() + timedelta(days=1)), progress=False)
            if df.empty or len(df) < 200:
                print(f"Skipping {ticker} Daily: Empty or insufficient data.")
                failed_scans += 1
            else:
                df = calculate_indicators(df)
                latest_live = df.iloc[-1]
                price = float(latest_live['Close'])
                
                # Use completed day's signal during market hours to prevent overwriting cache with live HOLD
                signal_row = get_completed_signal_row(df)
                today_signal = signal_row['Signal']
                current_signals[ticker] = today_signal
                
                # Retrieve cached signal
                prev_signal = last_signals.get(ticker, "HOLD")
                
                print(f"[{ticker}] Daily Previous: {prev_signal} -> Today: {today_signal} (Price: Rs.{price:.2f})")
                
                # Monitor active Swing trades
                if ticker_clean in active_trades:
                    trade_info = active_trades[ticker_clean]
                    target_val = float(trade_info['target_price'])
                    sl_val = float(trade_info['stop_loss'])
                    
                    if price >= target_val:
                        pct_gain = ((price - trade_info['entry_price']) / trade_info['entry_price']) * 100
                        msg = (
                            f"🎉 *PROFIT TARGET HIT!*\n\n"
                            f"*Ticker:* `{ticker_clean}`\n"
                            f"*Current Price:* ₹{price:.2f}\n"
                            f"*Entry Price:* ₹{trade_info['entry_price']:.2f}\n"
                            f"*Target Price:* ₹{target_val:.2f}\n"
                            f"*Gain:* +{pct_gain:.1f}%\n\n"
                            f"Recommend selling now to book your profit! 💰"
                        )
                        send_telegram_message(token, chat_id, msg)
                        print(f"Target hit alert sent for {ticker_clean}")
                        del active_trades[ticker_clean]
                    elif price <= sl_val:
                        pct_loss = ((price - trade_info['entry_price']) / trade_info['entry_price']) * 100
                        msg = (
                            f"⚠️ *STOP LOSS HIT!*\n\n"
                            f"*Ticker:* `{ticker_clean}`\n"
                            f"*Current Price:* ₹{price:.2f}\n"
                            f"*Entry Price:* ₹{trade_info['entry_price']:.2f}\n"
                            f"*Stop Loss Price:* ₹{sl_val:.2f}\n"
                            f"*Loss:* {pct_loss:.1f}%\n\n"
                            f"Recommend exiting now to protect capital. 🛑"
                        )
                        send_telegram_message(token, chat_id, msg)
                        print(f"Stop loss hit alert sent for {ticker_clean}")
                        del active_trades[ticker_clean]
                
                # Track signals for report
                if today_signal in ["BUY", "SELL"]:
                    conf = calculate_confidence(signal_row, today_signal)
                    sig_info = {
                        "name": stock_name,
                        "ticker": ticker_clean,
                        "price": price,
                        "signal": today_signal,
                        "entry": price,
                        "sl": price * 0.97 if today_signal == "BUY" else price * 1.03,
                        "target1": price * 1.05 if today_signal == "BUY" else price * 0.95,
                        "target2": price * 1.08 if today_signal == "BUY" else price * 0.92,
                        "rrr": "1:1.67",
                        "confidence": conf,
                        "reason": "RSI oversold & MACD bullish crossover" if today_signal == "BUY" else "RSI overbought & MACD bearish crossover",
                        "indicators": "RSI, MACD, Volume, MA200" if today_signal == "BUY" else "RSI, MACD",
                        "time": ist_now.strftime("%H:%M:%S")
                    }
                    if today_signal == "BUY":
                        buy_signals_daily_list.append(sig_info)
                    else:
                        sell_signals_daily_list.append(sig_info)
                
                # Daily Swing Signal Transitions
                if today_signal != prev_signal:
                    if today_signal == "BUY":
                        target_price = price * 1.05
                        stop_loss = price * 0.97
                        msg = f"🟢 *BUY SIGNAL TRIGGERED*\n\n*Ticker:* `{ticker_clean}`\n*Action:* BUY (Market Open / Live)\n*Entry Price:* ₹{price:.2f}\n*Target Price (+5%):* ₹{target_price:.2f}\n*Stop Loss (-3%):* ₹{stop_loss:.2f}\n*Date:* {date.today()}\n\n_Indicators alignment: RSI is low, MACD momentum is positive, volume is high, and price is above MA200._"
                        send_telegram_message(token, chat_id, msg)
                        print(f"Sent BUY alert for {ticker}")
                        
                        active_trades[ticker_clean] = {
                            "entry_price": price,
                            "target_price": target_price,
                            "stop_loss": stop_loss,
                            "date": str(date.today())
                        }
                    elif today_signal == "SELL":
                        msg = f"🔴 *SELL SIGNAL TRIGGERED*\n\n*Ticker:* `{ticker_clean}`\n*Action:* SELL / Exit immediately\n*Exit Price:* ₹{price:.2f}\n*Date:* {date.today()}\n\n_Indicators alignment: RSI is overbought or MACD momentum crossover has turned bearish._"
                        send_telegram_message(token, chat_id, msg)
                        print(f"Sent SELL alert for {ticker}")
                        if ticker_clean in active_trades:
                            del active_trades[ticker_clean]
            scanned_count += 1
        except Exception as e:
            print(f"Error evaluating daily for {ticker}: {e}")
            failed_scans += 1

        # --- 2. INTRADAY SCANNING & MONITORING (15m Timeframe) ---
        try:
            df_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
            if df_15m.empty or len(df_15m) < 20:
                print(f"Skipping {ticker} Intraday: Empty or insufficient data.")
                failed_scans += 1
            else:
                df_15m = calculate_intraday_indicators(df_15m)
                latest_live_15m = df_15m.iloc[-1]
                price_15m = float(latest_live_15m['Close'])
                
                # If market is active, today's last 15m candle is incomplete (live), so use the completed index [-2]
                signal_row_15m = latest_live_15m
                if is_market_hours:
                    signal_row_15m = df_15m.iloc[-2] if len(df_15m) > 1 else latest_live_15m
                
                today_intraday_signal = signal_row_15m['Signal']
                current_intraday_signals[ticker] = today_intraday_signal
                
                # Retrieve cached signal
                prev_intraday_signal = last_intraday_signals.get(ticker, "HOLD")
                
                print(f"[{ticker}] Intraday Previous: {prev_intraday_signal} -> Today: {today_intraday_signal} (Price: Rs.{price_15m:.2f})")
                
                # Monitor active Intraday trades
                if ticker_clean in active_intraday_trades:
                    trade_info = active_intraday_trades[ticker_clean]
                    target_val = float(trade_info['target_price'])
                    sl_val = float(trade_info['stop_loss'])
                    
                    if price_15m >= target_val:
                        pct_gain = ((price_15m - trade_info['entry_price']) / trade_info['entry_price']) * 100
                        msg = (
                            f"⚡ *INTRADAY PROFIT TARGET HIT!*\n\n"
                            f"*Ticker:* `{ticker_clean}`\n"
                            f"*Current Price:* ₹{price_15m:.2f}\n"
                            f"*Entry Price:* ₹{trade_info['entry_price']:.2f}\n"
                            f"*Target Price:* ₹{target_val:.2f}\n"
                            f"*Gain:* +{pct_gain:.1f}%\n\n"
                            f"Recommend selling now to book intraday profit! 💰"
                        )
                        send_telegram_message(token, chat_id, msg)
                        print(f"Intraday target hit alert sent for {ticker_clean}")
                        del active_intraday_trades[ticker_clean]
                    elif price_15m <= sl_val:
                        pct_loss = ((price_15m - trade_info['entry_price']) / trade_info['entry_price']) * 100
                        msg = (
                            f"⚡ *INTRADAY STOP LOSS HIT!*\n\n"
                            f"*Ticker:* `{ticker_clean}`\n"
                            f"*Current Price:* ₹{price_15m:.2f}\n"
                            f"*Entry Price:* ₹{trade_info['entry_price']:.2f}\n"
                            f"*Stop Loss Price:* ₹{sl_val:.2f}\n"
                            f"*Loss:* {pct_loss:.1f}%\n\n"
                            f"Recommend exiting intraday position immediately. 🛑"
                        )
                        send_telegram_message(token, chat_id, msg)
                        print(f"Intraday stop loss hit alert sent for {ticker_clean}")
                        del active_intraday_trades[ticker_clean]
                
                # Track intraday signals for report
                if today_intraday_signal in ["BUY", "SELL"]:
                    conf = calculate_confidence(signal_row_15m, today_intraday_signal)
                    sig_info = {
                        "name": stock_name,
                        "ticker": ticker_clean,
                        "price": price_15m,
                        "signal": today_intraday_signal,
                        "entry": price_15m,
                        "sl": price_15m * 0.995 if today_intraday_signal == "BUY" else price_15m * 1.005,
                        "target1": price_15m * 1.01 if today_intraday_signal == "BUY" else price_15m * 0.99,
                        "target2": price_15m * 1.015 if today_intraday_signal == "BUY" else price_15m * 0.985,
                        "rrr": "1:2.0",
                        "confidence": conf,
                        "reason": "EMA20 breakout & MACD cross" if today_intraday_signal == "BUY" else "Price fell below EMA20 trendline",
                        "indicators": "RSI, MACD, Volume, EMA20" if today_intraday_signal == "BUY" else "EMA20",
                        "time": ist_now.strftime("%H:%M:%S")
                    }
                    if today_intraday_signal == "BUY":
                        buy_signals_intra_list.append(sig_info)
                    else:
                        sell_signals_intra_list.append(sig_info)
                        
                # Intraday Signal Transitions
                if today_intraday_signal != prev_intraday_signal:
                    if today_intraday_signal == "BUY":
                        target_price = price_15m * 1.01
                        stop_loss = price_15m * 0.995
                        msg = f"⚡ *INTRADAY BUY SIGNAL*\n\n*Ticker:* `{ticker_clean}`\n*Entry Price:* ₹{price_15m:.2f}\n*Target (+1%):* ₹{target_price:.2f}\n*Stop Loss (-0.5%):* ₹{stop_loss:.2f}\n\n_Indicators: Price is above EMA20, RSI is oversold (<40) in pullback, MACD has turned bullish, and volume is above average._"
                        send_telegram_message(token, chat_id, msg)
                        print(f"Sent Intraday BUY alert for {ticker}")
                        
                        active_intraday_trades[ticker_clean] = {
                            "entry_price": price_15m,
                            "target_price": target_price,
                            "stop_loss": stop_loss,
                            "time": str(ist_now)
                        }
                    elif today_intraday_signal == "SELL":
                        msg = f"⚡ *INTRADAY SELL SIGNAL*\n\n*Ticker:* `{ticker_clean}`\n*Exit Price:* ₹{price_15m:.2f}\n\n_Indicators: Price fell below EMA20, or RSI is overbought with MACD bearish crossover._"
                        send_telegram_message(token, chat_id, msg)
                        print(f"Sent Intraday SELL alert for {ticker}")
                        if ticker_clean in active_intraday_trades:
                            del active_intraday_trades[ticker_clean]
        except Exception as e:
            print(f"Error evaluating intraday for {ticker}: {e}")
            failed_scans += 1
            
    # Save the current states for the next run
    save_current_signals(current_signals)
    save_active_trades(active_trades)
    
    save_current_intraday_signals(current_intraday_signals)
    if not is_market_hours:
        save_active_intraday_trades({})
        print("Cleared active intraday trades (market closed).")
    else:
        save_active_intraday_trades(active_intraday_trades)
        
    # --- 3. EXPORT DAILY MD SCAN REPORT ---
    end_scan_time = datetime.now()
    execution_time = (end_scan_time - start_scan_time).total_seconds()
    
    total_buys = len(buy_signals_daily_list) + len(buy_signals_intra_list)
    total_sells = len(sell_signals_daily_list) + len(sell_signals_intra_list)
    total_holds = len(tickers) * 2 - (total_buys + total_sells)
    
    # Calculate Average Confidence Score
    confidences = [s['confidence'] for s in buy_signals_daily_list + sell_signals_daily_list + buy_signals_intra_list + sell_signals_intra_list]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    
    # Find Best Trading Opportunity of the Day (highest confidence BUY)
    all_buys = buy_signals_daily_list + buy_signals_intra_list
    best_opp = max(all_buys, key=lambda x: x['confidence']) if all_buys else None
    
    # Find Highest Risk Trade (lowest confidence BUY/SELL)
    all_signals = buy_signals_daily_list + sell_signals_daily_list + buy_signals_intra_list + sell_signals_intra_list
    highest_risk = min(all_signals, key=lambda x: x['confidence']) if all_signals else None
    
    report_md = f"""# Daily Trading Report - {date.today()}

## Scan Overview
* **Scan Start Time**: {start_scan_time.strftime("%Y-%m-%d %H:%M:%S")}
* **Scan End Time**: {end_scan_time.strftime("%Y-%m-%d %H:%M:%S")}
* **Total Execution Time**: {execution_time:.2f} seconds
* **Market Scanned**: {market_index}
* **Total Stocks Scanned**: {scanned_count}
* **Failed Scans**: {failed_scans}
* **Average Confidence Score**: {avg_confidence:.1f}%

## Signals Summary
* **BUY Signals**: {total_buys}
* **SELL Signals**: {total_sells}
* **HOLD Signals**: {total_holds}

---

## Best Opportunity of the Day
"""
    if best_opp:
        report_md += f"""* **Ticker**: `{best_opp['ticker']}` ({best_opp['name']})
* **Price**: ₹{best_opp['price']:.2f}
* **Confidence**: **{best_opp['confidence']:.1f}%**
* **Entry**: ₹{best_opp['entry']:.2f} | Stop Loss: ₹{best_opp['sl']:.2f}
* **Target 1**: ₹{best_opp['target1']:.2f} | Target 2: ₹{best_opp['target2']:.2f}
* **Indicators**: {best_opp['indicators']}
"""
    else:
        report_md += "_No BUY Trades Triggered Today._\n"
        
    report_md += "\n## Highest Risk Trade\n"
    if highest_risk:
        report_md += f"""* **Ticker**: `{highest_risk['ticker']}` ({highest_risk['name']})
* **Price**: ₹{highest_risk['price']:.2f}
* **Confidence**: **{highest_risk['confidence']:.1f}%** (Lower score indicates higher risk)
* **Entry**: ₹{highest_risk['entry']:.2f} | Stop Loss: ₹{highest_risk['sl']:.2f}
* **Indicators**: {highest_risk['indicators']}
"""
    else:
        report_md += "_No Trades Triggered Today._\n"

    report_md += "\n--- \n\n## Triggered Swing Signals (Daily timeframe)\n"
    if buy_signals_daily_list or sell_signals_daily_list:
        for s in buy_signals_daily_list + sell_signals_daily_list:
            report_md += f"""### `{s['ticker']}` ({s['name']}) - **{s['signal']}**
* **Price**: ₹{s['price']:.2f}
* **Confidence**: {s['confidence']:.1f}%
* **Targets**: Target 1: ₹{s['target1']:.2f} | Target 2: ₹{s['target2']:.2f}
* **Stop Loss**: ₹{s['sl']:.2f} | RRR: {s['rrr']}
* **Reason**: {s['reason']}
* **Indicators**: {s['indicators']}
"""
    else:
        report_md += "_No Trade - Strategy Conditions Not Met._\n"
        
    report_md += "\n## Triggered Intraday Signals (15m timeframe)\n"
    if buy_signals_intra_list or sell_signals_intra_list:
        for s in buy_signals_intra_list + sell_signals_intra_list:
            report_md += f"""### `{s['ticker']}` ({s['name']}) - **{s['signal']}**
* **Price**: ₹{s['price']:.2f}
* **Confidence**: {s['confidence']:.1f}%
* **Targets**: Target 1: ₹{s['target1']:.2f} | Target 2: ₹{s['target2']:.2f}
* **Stop Loss**: ₹{s['sl']:.2f} | RRR: {s['rrr']}
* **Reason**: {s['reason']}
* **Indicators**: {s['indicators']}
"""
    else:
        report_md += "_No Trade - Strategy Conditions Not Met._\n"
        
    try:
        with open("daily_scan_report.md", "w", encoding="utf-8") as f:
            f.write(report_md)
        print("Daily Trading Report generated successfully.")
    except Exception as e:
        print(f"Error generating daily scan report file: {e}")
        
    print("Scan completed successfully.")

if __name__ == "__main__":
    main()
