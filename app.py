import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta
from datetime import date, timedelta

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
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# CORE LOGIC & INDICATORS
# -------------------------------------------------------------

@st.cache_data(ttl=1800)  # Cache data for 30 minutes to improve performance
def get_ticker_data(ticker, start_date, end_date):
    try:
        df = yf.download(ticker, start=str(start_date), end=str(end_date), progress=False)
        if df.empty:
            return None
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        st.sidebar.error(f"Error fetching data for {ticker}: {e}")
        return None

def calculate_indicators(df):
    if df is None or len(df) < 50:
        return df
    
    df = df.copy()
    
    # 1. RSI Indicator
    df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    
    # 2. MACD Indicator
    macd = ta.trend.MACD(df['Close'])
    df['MACD'] = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    df['MACD_Diff'] = macd.macd_diff()
    
    # 3. Moving Averages
    df['MA50'] = df['Close'].rolling(50).mean()
    df['MA200'] = df['Close'].rolling(200).mean()
    
    # 4. Volume 20 SMA
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    
    # 5. Signal Logic
    def get_signal(row):
        # Prevent calculations if necessary indicators are missing
        if pd.isna(row['RSI']) or pd.isna(row['MACD']) or pd.isna(row['MA200']) or pd.isna(row['Vol_SMA20']):
            return 'HOLD'
        
        # BUY Condition: 
        # - RSI < 40 (Oversold/near-oversold)
        # - MACD Line > MACD Signal Line (Bullish momentum crossover)
        # - Close > MA200 (Long-term uptrend trend filter)
        # - Volume > 20-day Volume SMA (Volume confirmation)
        is_buy = (row['RSI'] < 40) and (row['MACD'] > row['MACD_Signal']) and (row['Close'] > row['MA200']) and (row['Volume'] > row['Vol_SMA20'])
        
        # SELL Condition:
        # - RSI > 65 (Overbought/near-overbought)
        # - MACD Line < MACD Signal Line (Bearish momentum crossover)
        is_sell = (row['RSI'] > 65) and (row['MACD'] < row['MACD_Signal'])
        
        if is_buy:
            return 'BUY'
        elif is_sell:
            return 'SELL'
        return 'HOLD'
        
    df['Signal'] = df.apply(get_signal, axis=1)
    return df

# -------------------------------------------------------------
# SIDEBAR NAVIGATION
# -------------------------------------------------------------
st.sidebar.title("🧭 Navigation")
app_mode = st.sidebar.radio("Go to", ["Multi-Stock Dashboard", "Single Stock Analysis"])

# Info Sidebar Section
st.sidebar.markdown("---")
st.sidebar.subheader("💡 Strategy Specs")
st.sidebar.markdown("""
**🟢 BUY Signal:**
- RSI < 40
- MACD > Signal Line
- Close > MA200
- Volume > 20-day Volume SMA

**🔴 SELL Signal:**
- RSI > 65
- MACD < Signal Line
""")

# -------------------------------------------------------------
# VIEW 1: MULTI-STOCK DASHBOARD
# -------------------------------------------------------------
if app_mode == "Multi-Stock Dashboard":
    st.title("📊 NSE Multi-Stock Dashboard")
    st.caption("Real-time monitoring of 15 key Nifty 50 stocks using our confirmation trading strategy.")
    
    tickers = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
        "BHARTIARTL.NS", "SBIN.NS", "ITC.NS", "HINDUNILVR.NS", "LT.NS",
        "AXISBANK.NS", "KOTAKBANK.NS", "TATASTEEL.NS", "M&M.NS", "ASIANPAINT.NS"
    ]
    
    # Analyze all tickers
    with st.spinner("Analyzing Nifty 15 tickers..."):
        results = []
        # Need 1 year of daily data to ensure reliable MA200 calculations
        start_date_dash = date.today() - timedelta(days=365)
        
        for ticker in tickers:
            df = get_ticker_data(ticker, start_date_dash, date.today())
            if df is not None and len(df) >= 200:
                df = calculate_indicators(df)
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                
                close_val = float(latest['Close'])
                prev_close = float(prev['Close'])
                pct_change = ((close_val - prev_close) / prev_close) * 100
                
                results.append({
                    "Ticker": ticker,
                    "Price (₹)": close_val,
                    "Change %": pct_change,
                    "RSI (14)": float(latest['RSI']),
                    "MACD": float(latest['MACD']),
                    "MACD Signal": float(latest['MACD_Signal']),
                    "Volume": int(latest['Volume']),
                    "Vol SMA20": int(latest['Vol_SMA20']),
                    "Signal": latest['Signal']
                })
        
        if results:
            df_results = pd.DataFrame(results)
            
            # Map emojis to signals for display
            signal_emoji = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
            df_results['Display Signal'] = df_results['Signal'].map(signal_emoji)
            
            # Summary stats
            buy_count = len(df_results[df_results['Signal'] == 'BUY'])
            sell_count = len(df_results[df_results['Signal'] == 'SELL'])
            hold_count = len(df_results[df_results['Signal'] == 'HOLD'])
            
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("🟢 BUY Signals Active", buy_count)
            col_m2.metric("🔴 SELL Signals Active", sell_count)
            col_m3.metric("🟡 HOLD / Neutral Tickers", hold_count)
            
            st.markdown("### Ticker Signals Overview")
            
            # Display interactive dataframe with custom configuration
            st.dataframe(
                df_results[['Ticker', 'Price (₹)', 'Change %', 'RSI (14)', 'Volume', 'Vol SMA20', 'Display Signal']],
                column_config={
                    "Ticker": st.column_config.TextColumn("Ticker", width="medium"),
                    "Price (₹)": st.column_config.NumberColumn("Price (₹)", format="₹%.2f"),
                    "Change %": st.column_config.NumberColumn("Change %", format="%.2f%%"),
                    "RSI (14)": st.column_config.NumberColumn("RSI (14)", format="%.2f"),
                    "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                    "Vol SMA20": st.column_config.NumberColumn("Vol SMA20", format="%d"),
                    "Display Signal": st.column_config.TextColumn("Signal State", width="medium")
                },
                use_container_width=True,
                hide_index=True,
                height=450
            )
            
            # Detail Section
            st.markdown("---")
            st.subheader("🔍 Selected Ticker Detailed Analysis")
            selected_ticker = st.selectbox("Select a ticker from the list to view interactive charts:", tickers)
            
            # Fetch full history for chart view
            detail_df = get_ticker_data(selected_ticker, start_date_dash, date.today())
            if detail_df is not None and len(detail_df) >= 200:
                detail_df = calculate_indicators(detail_df)
                
                # Candlestick
                fig = go.Figure(data=[go.Candlestick(
                    x=detail_df.index,
                    open=detail_df['Open'], high=detail_df['High'],
                    low=detail_df['Low'], close=detail_df['Close'],
                    name="Price"
                )])
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
        else:
            st.error("Unable to load data for tickers.")

# -------------------------------------------------------------
# VIEW 2: SINGLE STOCK ANALYSIS
# -------------------------------------------------------------
else:
    st.title("📈 Custom Ticker Deep Analysis")
    st.caption("Search for any global or NSE ticker, customize parameters, and view a comprehensive analysis.")
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        symbol = st.text_input("Enter Ticker Symbol (e.g. RELIANCE.NS, TCS.NS, AAPL, TSLA)", "RELIANCE.NS")
    with col_input2:
        # Default start date 2 years back to give plenty of data for MA200
        start_date = st.date_input("Analysis Start Date", value=pd.to_datetime("2024-01-01"))
        
    if st.button("Run Deep Analysis"):
        with st.spinner(f"Downloading and calculating indicators for {symbol}..."):
            df = get_ticker_data(symbol, start_date, date.today())
            
        if df is None or df.empty:
            st.error(f"No data found for symbol '{symbol}'. Ensure it is written correctly (add '.NS' for NSE stocks).")
        elif len(df) < 200:
            st.warning(f"Data contains only {len(df)} entries. At least 200 trading days are required to calculate the 200-period MA correctly.")
        else:
            df = calculate_indicators(df)
            latest = df.iloc[-1]
            
            # Today's Signal Header Card
            st.subheader("Today's Analysis Summary")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Date", str(latest.name.date()))
            col2.metric("Close Price", f"₹{latest['Close']:.2f}" if symbol.endswith(".NS") else f"${latest['Close']:.2f}")
            col3.metric("RSI (14)", f"{latest['RSI']:.2f}")
            
            # Determine color for Signal metric card
            signal_color = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}
            col4.metric("Strategy Signal", signal_color[latest['Signal']])
            
            # Volume vs Vol SMA20 metric
            vol_ratio = latest['Volume'] / latest['Vol_SMA20'] if latest['Vol_SMA20'] > 0 else 1.0
            col5.metric("Volume Ratio", f"{vol_ratio:.2f}x")
            
            # Charts Section
            st.subheader("Price & Moving Averages")
            fig = go.Figure(data=[go.Candlestick(
                x=df.index,
                open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'],
                name="Price"
            )])
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
                
            # Recent signals table
            st.subheader("Historical Buy/Sell Events (Last 15 Signals)")
            signals_df = df[df['Signal'] != 'HOLD'][['Close', 'RSI', 'Signal', 'Volume']].tail(15)
            # Reformat index for presentation
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