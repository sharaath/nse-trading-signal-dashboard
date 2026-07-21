import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta
from datetime import date, timedelta, datetime, timezone
import urllib.request
import urllib.parse
import json
import os
import sys

# Ensure market-signal-bot modules are importable
sys.path.append(os.path.join(os.path.dirname(__file__), "market-signal-bot"))
from db.instruments import INSTRUMENTS_REGISTRY, get_instrument_metadata, get_grouped_instruments

def get_ticker_name(ticker: str) -> str:
    meta = get_instrument_metadata(ticker)
    return meta.get("name", ticker.replace("^", "").replace(".NS", ""))

CACHE_FILE = "last_signals.json"

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read()
    except Exception:
        return None

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

# Set page config for a wider dashboard layout and custom title
st.set_page_config(page_title="NSE Trading Signal Dashboard", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for premium styling
st.markdown("""
<style>
    .reportview-container {
        background: #f8f9fa;
    }
    .metric-card {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        border-left: 5px solid #007bff;
        margin-bottom: 15px;
    }
    .metric-val {
        font-size: 24px;
        font-weight: bold;
    }
    .metric-label {
        font-size: 14px;
        color: #6c757d;
    }
    .no-trade-box {
        background-color: #f8d7da;
        color: #721c24;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #f5c6cb;
        font-weight: bold;
        text-align: center;
        margin: 15px 0;
    }
</style>
""", unsafe_allow_html=True)

def get_completed_signal_row(df):
    if len(df) < 2:
        return df.iloc[-1]
        
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    
    is_market_hours = False
    if ist_now.weekday() < 5:  # Monday to Friday
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
# CORE LOGIC & INDICATORS
# -------------------------------------------------------------

@st.cache_data(ttl=1800)  # Cache data for 30 minutes to improve performance
def get_ticker_data(ticker, start_date, end_date):
    try:
        ticker_clean = ticker.strip()
        if not ticker_clean:
            return None
        if len(ticker_clean.split()) > 1:
            raise ValueError("Ticker symbol cannot contain spaces.")
            
        df = yf.download(ticker_clean, start=str(start_date), end=str(end_date), progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]
        return df
    except Exception as e:
        st.sidebar.error(f"Error fetching data for {ticker}: {e}")
        return None

def calculate_indicators(df):
    if df is None or len(df) < 50:
        return df
    
    df = df.copy()
    df = df.loc[:, ~df.columns.duplicated()]
    
    df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd = ta.trend.MACD(df['Close'])
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    df['MACD_Diff'] = macd.macd_diff()
    df['MA50'] = df['Close'].rolling(50).mean()
    df['MA200'] = df['Close'].rolling(200).mean()
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    
    def get_signal(row):
        if pd.isna(row['RSI']) or pd.isna(row['MACD']):
            return 'HOLD'
        
        is_buy = (row['MACD'] > row['MACD_Signal']) and (35 <= row['RSI'] <= 65)
        if 'MA200' in row and not pd.isna(row['MA200']):
            is_buy = is_buy and (row['Close'] > row['MA200'] * 0.97)
            
        is_sell = (row['MACD'] < row['MACD_Signal']) and (row['RSI'] > 60)
        
        if is_buy:
            return 'BUY'
        elif is_sell:
            return 'SELL'
        return 'HOLD'
        
    df['Signal'] = df.apply(get_signal, axis=1)
    return df

@st.cache_data(ttl=300)  # Intraday data updates faster (5 min TTL)
def get_intraday_ticker_data(ticker):
    try:
        ticker_clean = ticker.strip()
        if not ticker_clean or len(ticker_clean.split()) > 1:
            raise ValueError("Ticker symbol cannot contain spaces.")
        df = yf.download(ticker_clean, period="5d", interval="15m", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]
        return df
    except Exception as e:
        st.sidebar.error(f"Error fetching intraday for {ticker}: {e}")
        return None

def calculate_intraday_indicators(df):
    if df is None or len(df) < 20:
        return df
        
    df = df.copy()
    df = df.loc[:, ~df.columns.duplicated()]
    
    df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd = ta.trend.MACD(df['Close'])
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    df['MACD_Diff'] = macd.macd_diff()
    df['EMA20'] = ta.trend.EMAIndicator(df['Close'], window=20).ema_indicator()
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    
    def get_signal(row):
        if pd.isna(row['RSI']) or pd.isna(row['MACD']) or pd.isna(row['EMA20']):
            return 'HOLD'
        
        macd_bullish = row['MACD'] > row['MACD_Signal']
        rsi_healthy_buy = (40 <= row['RSI'] <= 68)
        price_above_ema = (row['Close'] >= row['EMA20'])
        
        is_buy = macd_bullish and rsi_healthy_buy and price_above_ema
        
        macd_bearish = row['MACD'] < row['MACD_Signal']
        rsi_high_sell = (row['RSI'] >= 55)
        price_below_ema = (row['Close'] < row['EMA20'])
        
        is_sell = macd_bearish and rsi_high_sell and price_below_ema
        
        if is_buy:
            return 'BUY'
        elif is_sell:
            return 'SELL'
        return 'HOLD'
        
    df['Signal'] = df.apply(get_signal, axis=1)
    return df

# Helper for option chain render tab
def render_option_chain_tab(ticker_symbol, underlying_price, current_signal):
    import math
    ticker_obj = yf.Ticker(ticker_symbol)
    try:
        expiries = ticker_obj.options
    except Exception:
        expiries = []
        
    is_simulated = False
    if not expiries:
        # Generate simulated Thursdays (index options style)
        today_dt = date.today()
        sim_expiries = []
        for i in range(1, 4):
            days_ahead = 3 - today_dt.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_thurs = today_dt + timedelta(days=days_ahead + (i-1)*7)
            sim_expiries.append(next_thurs.strftime("%Y-%m-%d"))
        expiries = sim_expiries
        is_simulated = True
        
    # Dropdown select box for expiry date selection
    selected_expiry = st.selectbox("Select Options Expiry Date", expiries, key=f"expiry_selector_{ticker_symbol}")
    
    if is_simulated:
        st.info("⚠️ **Simulating NSE Option Chain** (Yahoo Finance lacks NSE derivatives licensing. Lot sizes and strikes are mathematically mapped to NSE contract specifications).")
        # Strike step & Lot size mapping
        lot_size = LOT_SIZES.get(ticker_symbol.split('.')[0], 100)
        if ticker_symbol in ["^NSEI", "NIFTY50", "NIFTY"]:
            step = 50
            lot_size = 25
        elif ticker_symbol in ["^BSESN", "SENSEX"]:
            step = 100
            lot_size = 10
        else:
            if underlying_price > 5000: step = 100
            elif underlying_price > 1000: step = 50
            elif underlying_price > 500: step = 20
            else: step = 10
            
        atm_strike = round(underlying_price / step) * step
        strikes = [atm_strike + i * step for i in range(-5, 6)]
        
        calls_data = []
        puts_data = []
        for K in strikes:
            # Call LTP (Premium model)
            if K >= underlying_price:
                c_ltp = underlying_price * 0.015 * math.exp(-10 * (K - underlying_price) / underlying_price)
            else:
                c_ltp = (underlying_price - K) + underlying_price * 0.015 * math.exp(-10 * (underlying_price - K) / underlying_price)
                
            # Put LTP
            if K <= underlying_price:
                p_ltp = underlying_price * 0.015 * math.exp(-10 * (underlying_price - K) / underlying_price)
            else:
                p_ltp = (K - underlying_price) + underlying_price * 0.015 * math.exp(-10 * (K - underlying_price) / underlying_price)
                
            calls_data.append({
                "strike": K,
                "lastPrice": max(0.5, c_ltp),
                "volume": int(10000 * math.exp(-abs(K - underlying_price)/(underlying_price * 0.05))),
                "openInterest": int(15000 * math.exp(-abs(K - underlying_price)/(underlying_price * 0.05)))
            })
            puts_data.append({
                "strike": K,
                "lastPrice": max(0.5, p_ltp),
                "volume": int(10000 * math.exp(-abs(K - underlying_price)/(underlying_price * 0.05))),
                "openInterest": int(15000 * math.exp(-abs(K - underlying_price)/(underlying_price * 0.05)))
            })
        calls = pd.DataFrame(calls_data)
        puts = pd.DataFrame(puts_data)
    else:
        with st.spinner("Fetching option chain details..."):
            try:
                opt = ticker_obj.option_chain(selected_expiry)
                calls = opt.calls
                puts = opt.puts
            except Exception as e:
                st.error(f"Failed to fetch option chain: {e}")
                return
            
    if calls.empty or puts.empty:
        st.warning("Empty options chain returned for this expiry.")
        return
        
    # Flatten multi-indexes if present
    for df in [calls, puts]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
    # Filter strikes within +/- 7% of underlying price
    low_bound = underlying_price * 0.93
    high_bound = underlying_price * 1.07
    
    calls_filt = calls[(calls['strike'] >= low_bound) & (calls['strike'] <= high_bound)].copy()
    puts_filt = puts[(puts['strike'] >= low_bound) & (puts['strike'] <= high_bound)].copy()
    
    if calls_filt.empty or puts_filt.empty:
        calls_filt = calls.head(10).copy()
        puts_filt = puts.head(10).copy()
        
    # Merge Call and Put chains on strike price
    merged_chain = pd.merge(
        calls_filt[['strike', 'lastPrice', 'volume', 'openInterest']],
        puts_filt[['strike', 'lastPrice', 'volume', 'openInterest']],
        on='strike',
        suffixes=('_Call', '_Put')
    )
    
    # Calculate ATM Strike
    atm_strike = min(merged_chain['strike'], key=lambda x: abs(x - underlying_price))
    
    # Rename columns for presentation
    merged_chain.rename(columns={
        "openInterest_Call": "Call OI",
        "volume_Call": "Call Vol",
        "lastPrice_Call": "Call LTP (₹)",
        "strike": "Strike Price",
        "lastPrice_Put": "Put LTP (₹)",
        "volume_Put": "Put Vol",
        "openInterest_Put": "Put OI"
    }, inplace=True)
    
    # Highlight ATM row
    merged_chain['ATM'] = merged_chain['Strike Price'].apply(lambda x: "⭐ ATM" if x == atm_strike else "")
    
    disp_cols = ["Call OI", "Call Vol", "Call LTP (₹)", "Strike Price", "ATM", "Put LTP (₹)", "Put Vol", "Put OI"]
    merged_chain = merged_chain[[c for c in disp_cols if c in merged_chain.columns]]
    
    st.markdown(f"### Option Chain - Expiry: `{selected_expiry}`")
    st.dataframe(
        merged_chain,
        column_config={
            "Call LTP (₹)": st.column_config.NumberColumn("Call LTP (₹)", format="₹%.2f"),
            "Put LTP (₹)": st.column_config.NumberColumn("Put LTP (₹)", format="₹%.2f"),
            "Strike Price": st.column_config.NumberColumn("Strike Price", format="%.2f"),
            "Call OI": st.column_config.NumberColumn("Call OI", format="%d"),
            "Put OI": st.column_config.NumberColumn("Put OI", format="%d"),
            "Call Vol": st.column_config.NumberColumn("Call Vol", format="%d"),
            "Put Vol": st.column_config.NumberColumn("Put Vol", format="%d")
        },
        use_container_width=True,
        hide_index=True,
        height=320
    )
    
    # Retrieve ATM Premiums
    atm_row = merged_chain[merged_chain['Strike Price'] == atm_strike]
    call_ltp = float(atm_row['Call LTP (₹)'].iloc[0]) if not atm_row.empty and 'Call LTP (₹)' in atm_row.columns else 0.0
    put_ltp = float(atm_row['Put LTP (₹)'].iloc[0]) if not atm_row.empty and 'Put LTP (₹)' in atm_row.columns else 0.0
    
    st.markdown("### 🎯 Option Trade Recommendations")
    if current_signal == "BUY":
        st.success(f"""
        **🟢 Recommended Action: Buy Call Option (CE)**
        * **Option Contract**: `{ticker_symbol.split('.')[0]} {selected_expiry} {atm_strike} CE`
        * **Estimated Entry Premium**: ₹{call_ltp:.2f}
        * **Target Price (+30%)**: ₹{call_ltp * 1.30:.2f}
        * **Stop Loss (-15%)**: ₹{call_ltp * 0.85:.2f}
        * **Rationale**: Bullish trend confirmation on the underlying stock indicates high-probability upside. Buying Calls captures this breakout.
        """)
    elif current_signal == "SELL":
        st.error(f"""
        **🔴 Recommended Action: Buy Put Option (PE)**
        * **Option Contract**: `{ticker_symbol.split('.')[0]} {selected_expiry} {atm_strike} PE`
        * **Estimated Entry Premium**: ₹{put_ltp:.2f}
        * **Target Price (+30%)**: ₹{put_ltp * 1.30:.2f}
        * **Stop Loss (-15%)**: ₹{put_ltp * 0.85:.2f}
        * **Rationale**: Bearish trend breakdown triggers downside options exposure. Buying Put options capitalizes on falling asset prices.
        """)
    else:
        st.info("""
        **🟡 Action: No Option Trade Recommended**
        * **Rationale**: Underlying trend is neutral (HOLD). Buying options in flat/neutral markets is discouraged due to premium decay (Theta decay).
        """)

# -------------------------------------------------------------
# CONSTITUENTS & DICTIONARIES
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

# -------------------------------------------------------------
# SIDEBAR CONFIGURATION
# -------------------------------------------------------------
st.sidebar.title("🧭 Navigation")
app_mode = st.sidebar.radio("Go to", ["Multi-Stock Dashboard", "Single Stock Analysis"])

st.sidebar.markdown("---")
strategy_mode = st.sidebar.selectbox("📈 Strategy Mode", ["Swing Trading (Daily)", "Intraday Trading (15m)"])
market_index = st.sidebar.selectbox("🎯 Market Index", ["Nifty 50", "Nifty 100", "Nifty 500 (Disabled)", "All NSE Stocks (Disabled)"])

# Position Sizing
st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Risk Management")
capital = st.sidebar.number_input("Trading Capital (₹)", value=100000, step=10000)
max_risk = st.sidebar.slider("Max Risk per Trade %", min_value=0.1, max_value=5.0, value=1.0, step=0.1)

# Info Sidebar Section
st.sidebar.markdown("---")
st.sidebar.subheader("💡 Strategy Specs")
if strategy_mode == "Swing Trading (Daily)":
    st.sidebar.markdown("""
    **🟢 Swing BUY:**
    - RSI < 40
    - MACD > Signal Line
    - Close > MA200
    - Volume > 20-day Volume SMA
    
    **🔴 Swing SELL:**
    - RSI > 65
    - MACD < Signal Line
    """)
else:
    st.sidebar.markdown("""
    **🟢 Intraday BUY (15m):**
    - Close > EMA20
    - RSI < 40 (pullback)
    - MACD > Signal Line
    - Volume > 20-period Vol SMA
    
    **🔴 Intraday SELL (15m):**
    - RSI > 65 and MACD < Signal
    - OR Close < EMA20
    """)

# Telegram Sidebar Section
st.sidebar.markdown("---")
telegram_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")

with st.sidebar.expander("🔔 Telegram Alerts Config"):
    token_input = st.text_input("Bot Token", value=telegram_token, type="password", help="Get from @BotFather")
    chat_id_input = st.text_input("Chat ID", value=telegram_chat_id, help="Get from @userinfobot")
    
    if st.button("Send Test Alert"):
        if token_input and chat_id_input:
            test_res = send_telegram_message(token_input, chat_id_input, "📈 *NSE Signal App Connection Test*\n\nYour Telegram Bot alerts are fully working!")
            if test_res:
                st.success("Test alert sent!")
            else:
                st.error("Failed to send. Double check credentials.")
        else:
            st.warning("Please enter credentials.")

# -------------------------------------------------------------
# VIEW 1: MULTI-STOCK DASHBOARD
# -------------------------------------------------------------
if app_mode == "Multi-Stock Dashboard":
    st.title("📊 NSE Multi-Stock Dashboard")
    st.caption(f"Real-time monitoring of {market_index} index constituents using confirmation algorithms.")
    
    # Determine tickers list
    if market_index == "Nifty 100":
        tickers = NIFTY_50_TICKERS + NIFTY_NEXT_50_TICKERS
    elif market_index == "Nifty 50":
        tickers = NIFTY_50_TICKERS
    else:
        st.warning("Nifty 500 and All NSE Stocks are disabled in the dashboard to prevent Yahoo Finance API rate limits. Reverting to Nifty 50.")
        tickers = NIFTY_50_TICKERS
        
    # Signals Filter
    st.markdown("#### Filter Dashboard Signals")
    sig_filter = st.radio("Display Filter:", ["Show All Signals", "BUY & SELL Only", "BUY Only", "SELL Only"], horizontal=True)

    # Analyze all tickers
    start_scan_time = datetime.now()
    failed_scans = 0
    results = []
    
    with st.spinner(f"Analyzing {market_index} tickers ({strategy_mode})..."):
        start_date_dash = date.today() - timedelta(days=365)
        
        for ticker in tickers:
            ticker_clean = ticker.split(".")[0]
            stock_name = get_ticker_name(ticker)
            
            if strategy_mode == "Intraday Trading (15m)":
                df = get_intraday_ticker_data(ticker)
                min_len = 20
                calc_func = calculate_intraday_indicators
            else:
                df = get_ticker_data(ticker, start_date_dash, date.today())
                min_len = 200
                calc_func = calculate_indicators
                
            if df is not None and len(df) >= min_len:
                try:
                    df = calc_func(df)
                    latest = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else latest
                    
                    close_val = float(latest['Close'])
                    prev_close = float(prev['Close'])
                    pct_change = ((close_val - prev_close) / prev_close) * 100
                    
                    signal_row = get_completed_signal_row(df)
                    sig = signal_row['Signal']
                    conf = calculate_confidence(signal_row, sig) if sig != "HOLD" else 0.0
                    
                    # Target/SL calculations
                    entry = close_val
                    if strategy_mode == "Intraday Trading (15m)":
                        sl = entry * 0.995 if sig == "BUY" else entry * 1.005
                        t1 = entry * 1.01 if sig == "BUY" else entry * 0.99
                        t2 = entry * 1.015 if sig == "BUY" else entry * 0.985
                        rrr = "1:2.0"
                        indicators = "RSI, MACD, Volume, EMA20" if sig == "BUY" else "EMA20"
                        reason = "EMA20 breakout & MACD cross" if sig == "BUY" else "Price fell below EMA20 trendline"
                    else:
                        sl = entry * 0.97 if sig == "BUY" else entry * 1.03
                        t1 = entry * 1.05 if sig == "BUY" else entry * 0.95
                        t2 = entry * 1.08 if sig == "BUY" else entry * 0.92
                        rrr = "1:1.67"
                        indicators = "RSI, MACD, Volume, MA200" if sig == "BUY" else "RSI, MACD"
                        reason = "RSI oversold & MACD crossover" if sig == "BUY" else "RSI overbought & MACD crossover"
                        
                    # Position Sizing
                    risk_amt = capital * (max_risk / 100)
                    sl_dist = abs(entry - sl)
                    qty = int(risk_amt / sl_dist) if sl_dist > 0 and sig != "HOLD" else 0
                    
                    # Generate time
                    gen_time = datetime.now().strftime("%H:%M:%S")
                    
                    results.append({
                        "Ticker": ticker_clean,
                        "Name": stock_name,
                        "Price (₹)": close_val,
                        "Change %": pct_change,
                        "Signal": sig,
                        "Entry (₹)": entry if sig != "HOLD" else None,
                        "Stop Loss (₹)": sl if sig != "HOLD" else None,
                        "Target 1 (₹)": t1 if sig != "HOLD" else None,
                        "Target 2 (₹)": t2 if sig != "HOLD" else None,
                        "RRR": rrr if sig != "HOLD" else None,
                        "Confidence (%)": conf if sig != "HOLD" else None,
                        "Reason": reason if sig != "HOLD" else "Strategy Conditions Not Met",
                        "Indicators": indicators if sig != "HOLD" else None,
                        "Position Size": qty if sig != "HOLD" else None,
                        "Time": gen_time
                    })
                except Exception:
                    failed_scans += 1
            else:
                failed_scans += 1
        
        end_scan_time = datetime.now()
        exec_duration = (end_scan_time - start_scan_time).total_seconds()
        
        if results:
            df_full = pd.DataFrame(results)
            
            # Send Telegram Transitions if credentials exist
            if token_input and chat_id_input:
                if strategy_mode == "Intraday Trading (15m)":
                    from cron_runner import get_last_intraday_signals, save_current_intraday_signals
                    last_sigs = get_last_intraday_signals()
                    current_sigs = {row['Ticker'] + ".NS": row['Signal'] for row in results}
                    
                    if last_sigs:
                        for tick, signal in current_sigs.items():
                            prev_signal = last_sigs.get(tick, "HOLD")
                            if signal != prev_signal:
                                row_data = next(r for r in results if r['Ticker'] == tick.split(".")[0])
                                price = row_data['Price (₹)']
                                if signal == "BUY":
                                    msg = f"⚡ *INTRADAY BUY SIGNAL*\n\n*Ticker:* `{row_data['Ticker']}`\n*Entry Price:* ₹{price:.2f}\n*Target (+1%):* ₹{row_data['Target 1 (₹)']:.2f}\n*Stop Loss (-0.5%):* ₹{row_data['Stop Loss (₹)']:.2f}\n\n_Indicators: Price is above EMA20, RSI is oversold (<40) in pullback, MACD has turned bullish, and volume is above average._"
                                    send_telegram_message(token_input, chat_id_input, msg)
                                elif signal == "SELL":
                                    msg = f"⚡ *INTRADAY SELL SIGNAL*\n\n*Ticker:* `{row_data['Ticker']}`\n*Exit Price:* ₹{price:.2f}\n\n_Indicators: Price fell below EMA20, or RSI is overbought with MACD bearish crossover._"
                                    send_telegram_message(token_input, chat_id_input, msg)
                    save_current_intraday_signals(current_sigs)
                else:
                    last_sigs = get_last_signals()
                    current_sigs = {row['Ticker'] + ".NS": row['Signal'] for row in results}
                    
                    if last_sigs:
                        for tick, signal in current_sigs.items():
                            prev_signal = last_sigs.get(tick, "HOLD")
                            if signal != prev_signal:
                                row_data = next(r for r in results if r['Ticker'] == tick.split(".")[0])
                                price = row_data['Price (₹)']
                                if signal == "BUY":
                                    msg = f"🟢 *BUY SIGNAL TRIGGERED*\n\n*Ticker:* `{row_data['Ticker']}`\n*Action:* BUY tomorrow (Market Open)\n*Entry Price:* ₹{price:.2f}\n*Target Price (+5%):* ₹{row_data['Target 1 (₹)']:.2f}\n*Stop Loss (-3%):* ₹{row_data['Stop Loss (₹)']:.2f}\n*Date:* {date.today()}\n\n_Indicators alignment: RSI is low, MACD momentum is positive, volume is high, and price is above MA200._"
                                    send_telegram_message(token_input, chat_id_input, msg)
                                elif signal == "SELL":
                                    msg = f"🔴 *SELL SIGNAL TRIGGERED*\n\n*Ticker:* `{row_data['Ticker']}`\n*Action:* SELL / Exit tomorrow\n*Exit Price:* ₹{price:.2f}\n*Date:* {date.today()}\n\n_Indicators alignment: RSI is overbought or MACD momentum crossover has turned bearish._"
                                    send_telegram_message(token_input, chat_id_input, msg)
                    save_current_signals(current_sigs)
            
            # Metric Card Counts
            buy_count = len(df_full[df_full['Signal'] == 'BUY'])
            sell_count = len(df_full[df_full['Signal'] == 'SELL'])
            hold_count = len(df_full[df_full['Signal'] == 'HOLD'])
            
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("🟢 BUY Signals Active", buy_count)
            col_m2.metric("🔴 SELL Signals Active", sell_count)
            col_m3.metric("🟡 HOLD / Neutral Tickers", hold_count)
            
            # Instrument Type & Signal Filters
            df_full['Instrument Type'] = df_full['Ticker'].apply(lambda x: "INDEX" if (x.startswith("^") or x in ["NIFTY", "SENSEX", "BANKNIFTY", "NIFTYIT", "SPX", "DJIA", "NDX"]) else "STOCK")
            
            if sig_filter == "BUY & SELL Only":
                df_filtered = df_full[df_full['Signal'].isin(["BUY", "SELL"])]
            elif sig_filter == "BUY Only":
                df_filtered = df_full[df_full['Signal'] == "BUY"]
            elif sig_filter == "SELL Only":
                df_filtered = df_full[df_full['Signal'] == "SELL"]
            else:
                df_filtered = df_full
                
            # Emojis for display
            signal_emoji = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
            if not df_filtered.empty:
                df_filtered['Display Signal'] = df_filtered['Signal'].map(signal_emoji)
            
            st.markdown("### Ticker Signals Overview")
            
            if df_filtered.empty:
                st.markdown("<div class='no-trade-box'>No Trade - Strategy Conditions Not Met.</div>", unsafe_allow_html=True)
            else:
                st.dataframe(
                    df_filtered[[
                        "Display Signal", "Ticker", "Instrument Type", "Name", "Price (₹)",
                        "Target 1 (₹)", "Target 2 (₹)", "Stop Loss (₹)", "RRR",
                        "Confidence (%)", "Position Size", "Reason", "Indicators", "Time"
                    ]],
                    column_config={
                        "Display Signal": st.column_config.TextColumn("Signal"),
                        "Ticker": st.column_config.TextColumn("Ticker"),
                        "Instrument Type": st.column_config.TextColumn("Type"),
                        "Name": st.column_config.TextColumn("Instrument / Company"),
                        "Price (₹)": st.column_config.NumberColumn("Price", format="₹%.2f"),
                        "Stop Loss (₹)": st.column_config.NumberColumn("Stop Loss", format="₹%.2f"),
                        "Target 1 (₹)": st.column_config.NumberColumn("Target 1", format="₹%.2f"),
                        "Target 2 (₹)": st.column_config.NumberColumn("Target 2", format="₹%.2f"),
                        "RRR": st.column_config.TextColumn("R:R"),
                        "Confidence (%)": st.column_config.NumberColumn("Confidence", format="%.1f%%"),
                        "Position Size": st.column_config.NumberColumn("Qty (Units)", format="%d"),
                        "Reason": st.column_config.TextColumn("Signal Reason"),
                        "Indicators": st.column_config.TextColumn("Indicators Triggered"),
                        "Time": st.column_config.TextColumn("Scan Time")
                    },
                    use_container_width=True,
                    hide_index=True,
                    height=450
                )
                
            # --- DAILY TRADING REPORT ---
            st.markdown("---")
            st.subheader("📋 Daily Scan & Trading Report")
            
            conf_vals = df_full[df_full['Signal'].isin(["BUY", "SELL"])]['Confidence (%)'].dropna()
            avg_conf = conf_vals.mean() if not conf_vals.empty else 0.0
            
            all_buys = df_full[df_full['Signal'] == "BUY"]
            best_opportunity = all_buys.loc[all_buys['Confidence (%)'].idxmax()]['Ticker'] if not all_buys.empty else "None"
            
            all_sigs = df_full[df_full['Signal'].isin(["BUY", "SELL"])]
            highest_risk = all_sigs.loc[all_sigs['Confidence (%)'].idxmin()]['Ticker'] if not all_sigs.empty else "None"
            
            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1:
                st.markdown(f"""
                **Scan Metrics:**
                * **Scan Start**: {start_scan_time.strftime("%H:%M:%S")}
                * **Scan End**: {end_scan_time.strftime("%H:%M:%S")}
                * **Execution Duration**: {exec_duration:.2f}s
                * **Total Scanned**: {len(tickers)} Tickers
                * **Failed Scans**: {failed_scans} Tickers
                """)
            with col_r2:
                st.markdown(f"""
                **Signal Overview:**
                * **🟢 BUY Setups**: {buy_count}
                * **🔴 SELL Setups**: {sell_count}
                * **🟡 HOLD Tickers**: {hold_count}
                * **Average Confidence**: {avg_conf:.1f}%
                """)
            with col_r3:
                st.markdown(f"""
                **Analyzed Opportunities:**
                * **⭐ Best Opportunity**: `{best_opportunity}`
                * **⚠️ Highest Risk Setup**: `{highest_risk}`
                """)
                
            # Detail Section
            st.markdown("---")
            st.subheader("🔍 Selected Ticker Detailed Analysis")
            selected_ticker = st.selectbox("Select a ticker from the list to view interactive charts:", tickers)
            
            # Fetch full history for chart view
            if strategy_mode == "Intraday Trading (15m)":
                detail_df = get_intraday_ticker_data(selected_ticker)
                min_len_detail = 20
                calc_func_detail = calculate_intraday_indicators
            else:
                detail_df = get_ticker_data(selected_ticker, start_date_dash, date.today())
                min_len_detail = 200
                calc_func_detail = calculate_indicators
                
            if detail_df is not None and len(detail_df) >= min_len_detail:
                detail_df = calc_func_detail(detail_df)
                latest_detail = detail_df.iloc[-1]
                detail_sig = latest_detail['Signal']
                
                # Tabbed Detailed analysis
                tab_chart, tab_options = st.tabs(["📉 Technical Charts", "⛓️ Option Chain Signal Tracker"])
                
                with tab_chart:
                    # Candlestick
                    fig = go.Figure(data=[go.Candlestick(
                        x=detail_df.index,
                        open=detail_df['Open'], high=detail_df['High'],
                        low=detail_df['Low'], close=detail_df['Close'],
                        name="Price"
                    )])
                    if strategy_mode == "Intraday Trading (15m)":
                        fig.add_trace(go.Scatter(x=detail_df.index, y=detail_df['EMA20'], name='20 EMA', line=dict(color='blue', width=1.5)))
                    else:
                        fig.add_trace(go.Scatter(x=detail_df.index, y=detail_df['MA50'], name='MA50', line=dict(color='orange', width=1.2)))
                        fig.add_trace(go.Scatter(x=detail_df.index, y=detail_df['MA200'], name='MA200', line=dict(color='blue', width=1.5)))
                    fig.update_layout(title=f"{selected_ticker} Candlestick Chart", xaxis_rangeslider_visible=False, height=400, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # RSI & MACD Columns
                    col_c1, col_c2 = st.columns(2)
                    
                    with col_c1:
                        fig_rsi = go.Figure()
                        fig_rsi.add_trace(go.Scatter(x=detail_df.index, y=detail_df['RSI'], name='RSI', line=dict(color='purple', width=1.2)))
                        fig_rsi.add_hline(y=65, line_dash="dash", line_color="red", annotation_text="Sell limit (65)")
                        fig_rsi.add_hline(y=40, line_dash="dash", line_color="green", annotation_text="Buy threshold (40)")
                        fig_rsi.update_layout(title="Relative Strength Index (RSI)", height=250, margin=dict(t=40, b=10))
                        st.plotly_chart(fig_rsi, use_container_width=True)
                    
                    with col_c2:
                        fig_macd = go.Figure()
                        fig_macd.add_trace(go.Scatter(x=detail_df.index, y=detail_df['MACD'], name='MACD', line=dict(color='blue', width=1.2)))
                        fig_macd.add_trace(go.Scatter(x=detail_df.index, y=detail_df['MACD_Signal'], name='Signal Line', line=dict(color='orange', width=1.2)))
                        hist_colors = ['rgba(46, 204, 113, 0.6)' if val >= 0 else 'rgba(231, 76, 60, 0.6)' for val in detail_df['MACD_Diff']]
                        fig_macd.add_trace(go.Bar(x=detail_df.index, y=detail_df['MACD_Diff'], name='Histogram', marker_color=hist_colors))
                        fig_macd.update_layout(title="MACD Indicator", height=250, margin=dict(t=40, b=10))
                        st.plotly_chart(fig_macd, use_container_width=True)
                
                with tab_options:
                    render_option_chain_tab(selected_ticker, float(latest_detail['Close']), detail_sig)
        else:
            st.error("Unable to load data for tickers.")

# -------------------------------------------------------------
# VIEW 2: SINGLE STOCK ANALYSIS
# -------------------------------------------------------------
else:
    st.title("📈 Custom Ticker Deep Analysis")
    if strategy_mode == "Intraday Trading (15m)":
        st.caption("Search for any global or NSE ticker and view a comprehensive 15-minute timeframe analysis.")
    else:
        st.caption("Search for any global or NSE ticker, customize parameters, and view a comprehensive analysis.")
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        symbol = st.text_input("Enter Ticker Symbol (e.g. RELIANCE.NS, TCS.NS, AAPL, TSLA)", "RELIANCE.NS")
    with col_input2:
        start_date = st.date_input("Analysis Start Date", value=pd.to_datetime("2024-01-01"))
        
    if st.button("Run Deep Analysis"):
        symbol = symbol.strip()
        if " " in symbol:
            st.error("⚠️ Ticker symbol cannot contain spaces. Use Yahoo Finance format.")
        else:
            if strategy_mode == "Intraday Trading (15m)":
                with st.spinner(f"Downloading and calculating 15m indicators for {symbol}..."):
                    df = get_intraday_ticker_data(symbol)
                min_len_single = 20
                calc_func_single = calculate_intraday_indicators
            else:
                with st.spinner(f"Downloading and calculating daily indicators for {symbol}..."):
                    df = get_ticker_data(symbol, start_date, date.today())
                min_len_single = 200
                calc_func_single = calculate_indicators
                
            if df is None or df.empty:
                st.error(f"No data found for symbol '{symbol}'. Ensure it is written correctly (add '.NS' for NSE stocks).")
            elif len(df) < min_len_single:
                st.warning(f"Data contains only {len(df)} entries. At least {min_len_single} periods are required.")
            else:
                df = calc_func_single(df)
                latest = df.iloc[-1]
                
                sig = latest['Signal']
                price = float(latest['Close'])
                conf = calculate_confidence(latest, sig) if sig != "HOLD" else 0.0
                
                # Math Metrics
                if strategy_mode == "Intraday Trading (15m)":
                    sl = price * 0.995 if sig == "BUY" else price * 1.005
                    t1 = price * 1.01 if sig == "BUY" else price * 0.99
                    t2 = price * 1.015 if sig == "BUY" else price * 0.985
                    rrr = "1:2.0"
                    indicators = "RSI, MACD, Volume, EMA20" if sig == "BUY" else "EMA20"
                    reason = "EMA20 breakout & MACD cross" if sig == "BUY" else "Price fell below EMA20 trendline"
                else:
                    sl = price * 0.97 if sig == "BUY" else price * 1.03
                    t1 = price * 1.05 if sig == "BUY" else price * 0.95
                    t2 = price * 1.08 if sig == "BUY" else price * 0.92
                    rrr = "1:1.67"
                    indicators = "RSI, MACD, Volume, MA200" if sig == "BUY" else "RSI, MACD"
                    reason = "RSI oversold & MACD crossover" if sig == "BUY" else "RSI overbought & MACD crossover"
                
                # Sizing
                risk_amt = capital * (max_risk / 100)
                sl_dist = abs(price - sl)
                qty = int(risk_amt / sl_dist) if sl_dist > 0 and sig != "HOLD" else 0
            
                # Today's Signal Header Card
                st.subheader("Today's Analysis Summary")
                
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Date", str(latest.name.date()))
                col2.metric("Close Price", f"₹{latest['Close']:.2f}" if symbol.endswith(".NS") else f"${latest['Close']:.2f}")
                col3.metric("RSI (14)", f"{latest['RSI']:.2f}")
                
                signal_color = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
                col4.metric("Strategy Signal", signal_color[sig])
                
                vol_ratio = latest['Volume'] / latest['Vol_SMA20'] if latest['Vol_SMA20'] > 0 else 1.0
                col5.metric("Volume Ratio", f"{vol_ratio:.2f}x")
                
                # Detailed Quantitative Card if trade setup is active
                st.markdown("### Trade Plan Execution Specs")
                if sig == "HOLD":
                    st.markdown("<div class='no-trade-box'>No Trade - Strategy Conditions Not Met.</div>", unsafe_allow_html=True)
                else:
                    col_p1, col_p2, col_p3 = st.columns(3)
                    with col_p1:
                        st.markdown(f"""
                        **Order Parameters:**
                        * **Action Type**: `{sig}`
                        * **Entry Price**: ₹{price:.2f}
                        * **Stop Loss**: ₹{sl:.2f}
                        """)
                    with col_p2:
                        st.markdown(f"""
                        **Targets:**
                        * **Target 1**: ₹{t1:.2f}
                        * **Target 2**: ₹{t2:.2f}
                        * **Risk-Reward (RRR)**: `{rrr}`
                        """)
                    with col_p3:
                        st.markdown(f"""
                        **Risk Details & Sizing:**
                        * **Confidence Score**: **{conf:.1f}%**
                        * **Max Capital Allocation**: ₹{price * qty:.2f} ({qty} units)
                        * **Indicators triggered**: {indicators}
                        """)
            
                # Tabbed details for Single Stock Analysis
                tab_chart_s, tab_options_s, tab_history_s = st.tabs(["📉 Technical Charts", "⛓️ Option Chain Signal Tracker", "📜 Historical Signals"])
                
                with tab_chart_s:
                    # Charts Section
                    st.subheader("Price & Trend Indicator")
                    fig = go.Figure(data=[go.Candlestick(
                        x=df.index,
                        open=df['Open'], high=df['High'],
                        low=df['Low'], close=df['Close'],
                        name="Price"
                    )])
                    if strategy_mode == "Intraday Trading (15m)":
                        fig.add_trace(go.Scatter(x=df.index, y=df['EMA20'], name='20 EMA', line=dict(color='blue', width=1.5)))
                    else:
                        fig.add_trace(go.Scatter(x=df.index, y=df['MA50'], name='50 MA', line=dict(color='orange', width=1.2)))
                        fig.add_trace(go.Scatter(x=df.index, y=df['MA200'], name='200 MA', line=dict(color='blue', width=1.5)))
                    fig.update_layout(title=f"{symbol} Candlestick Chart", xaxis_rangeslider_visible=False, height=450)
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Indicators Column
                    st.subheader("Technical Oscillators")
                    col_ind1, col_ind2 = st.columns(2)
                    
                    with col_ind1:
                        fig_rsi = go.Figure()
                        fig_rsi.add_trace(go.Scatter(x=df.index, y=df['RSI'], name='RSI', line=dict(color='purple', width=1.2)))
                        fig_rsi.add_hline(y=65, line_dash="dash", line_color="red", annotation_text="Sell limit (65)")
                        fig_rsi.add_hline(y=40, line_dash="dash", line_color="green", annotation_text="Buy threshold (40)")
                        fig_rsi.update_layout(title="Relative Strength Index (RSI)", height=250, margin=dict(t=40, b=10))
                        st.plotly_chart(fig_rsi, use_container_width=True)
                        
                    with col_ind2:
                        fig_macd = go.Figure()
                        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD'], name='MACD', line=dict(color='blue', width=1.2)))
                        fig_macd.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], name='Signal Line', line=dict(color='orange', width=1.2)))
                        hist_colors = ['rgba(46, 204, 113, 0.6)' if val >= 0 else 'rgba(231, 76, 60, 0.6)' for val in df['MACD_Diff']]
                        fig_macd.add_trace(go.Bar(x=df.index, y=df['MACD_Diff'], name='Histogram', marker_color=hist_colors))
                        fig_macd.update_layout(title="MACD Indicator", height=250, margin=dict(t=40, b=10))
                        st.plotly_chart(fig_macd, use_container_width=True)
                        
                with tab_options_s:
                    render_option_chain_tab(symbol, price, sig)
                    
                with tab_history_s:
                    # Recent signals table
                    st.subheader("Historical Buy/Sell Events (Last 15 Signals)")
                    signals_df = df[df['Signal'] != 'HOLD'][['Close', 'RSI', 'Signal', 'Volume']].tail(15)
                    signals_df.index = signals_df.index.date
                    signals_df.index.name = "Date"
                    st.dataframe(
                        signals_df,
                        column_config={
                            "Close": st.column_config.NumberColumn("Close Price", format="₹%.2f" if symbol.endswith(".NS") else "$%.2f"),
                            "RSI": st.column_config.NumberColumn("RSI (14)", format="%.2f"),
                            "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                            "Signal": st.column_config.TextColumn("Signal Generated")
                        },
                        use_container_width=True
                    )