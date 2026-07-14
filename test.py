import yfinance as yf
import pandas as pd
import ta
from datetime import date
from backtesting import Backtest, Strategy

# -------------------------------------------------------------
# STRATEGY 1: BASELINE RSI-ONLY STRATEGY
# -------------------------------------------------------------
class RSIStrategy(Strategy):
    def init(self):
        # Access pre-calculated RSI column
        self.rsi = self.I(lambda: self.data.RSI)

    def next(self):
        # BUY when RSI < 30 (Oversold)
        if self.rsi[-1] < 30 and not self.position:
            self.buy()
        # SELL when RSI > 70 (Overbought)
        elif self.rsi[-1] > 70 and self.position:
            self.position.close()

# -------------------------------------------------------------
# STRATEGY 2: ENHANCED 4-INDICATOR CONFIRMATION STRATEGY
# -------------------------------------------------------------
class EnhancedStrategy(Strategy):
    def init(self):
        # Access pre-calculated indicator columns
        self.rsi = self.I(lambda: self.data.RSI)
        self.macd = self.I(lambda: self.data.MACD)
        self.macd_signal = self.I(lambda: self.data.MACD_Signal)
        self.ma200 = self.I(lambda: self.data.MA200)
        self.vol_sma20 = self.I(lambda: self.data.Vol_SMA20)

    def next(self):
        # Make sure warm-up indicators are populated (especially MA200)
        if (pd.isna(self.rsi[-1]) or pd.isna(self.macd[-1]) or 
            pd.isna(self.ma200[-1]) or pd.isna(self.vol_sma20[-1])):
            return

        close = self.data.Close[-1]
        volume = self.data.Volume[-1]

        # BUY Condition: RSI < 40 & MACD > Signal & Close > MA200 & Volume > Vol_SMA20
        is_buy = (self.rsi[-1] < 40) and (self.macd[-1] > self.macd_signal[-1]) and (close > self.ma200[-1]) and (volume > self.vol_sma20[-1])
        
        # SELL Condition: RSI > 65 & MACD < Signal
        is_sell = (self.rsi[-1] > 65) and (self.macd[-1] < self.macd_signal[-1])

        if is_buy and not self.position:
            self.buy()
        elif is_sell and self.position:
            self.position.close()

# -------------------------------------------------------------
# CORE BACKTEST RUNNER LOOP
# -------------------------------------------------------------
def run_comparison():
    tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
    
    print("\n" + "="*80)
    print("NSE BACKTEST COMPARISON SUMMARY (2022-01-01 to Present)")
    print("="*80)
    
    for ticker in tickers:
        print(f"\nEvaluating Ticker: {ticker}...")
        
        # 1. Download data starting 1 year earlier (2021) to warm up MA200
        df = yf.download(ticker, start="2021-01-01", end=str(date.today()), progress=False)
        if df.empty:
            print(f"Failed to fetch data for {ticker}")
            continue
            
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # Remove duplicate column names
        df = df.loc[:, ~df.columns.duplicated()]

        # 2. Calculate Indicators in pandas
        df['RSI'] = ta.momentum.RSIIndicator(df['Close']).rsi()
        macd_obj = ta.trend.MACD(df['Close'])
        df['MACD'] = macd_obj.macd()
        df['MACD_Signal'] = macd_obj.macd_signal()
        df['MA200'] = df['Close'].rolling(200).mean()
        df['Vol_SMA20'] = df['Volume'].rolling(20).mean()

        # 3. Slice to start backtest from Jan 1, 2022
        df_backtest = df.loc['2022-01-01':].copy()

        # 4. Run RSI-Only Backtest
        bt_rsi = Backtest(df_backtest, RSIStrategy, cash=100000, commission=.002)
        stats_rsi = bt_rsi.run()

        # 5. Run Enhanced Backtest
        bt_enhanced = Backtest(df_backtest, EnhancedStrategy, cash=100000, commission=.002)
        stats_enhanced = bt_enhanced.run()

        # 6. Output Comparison
        print("-"*80)
        print(f"{'Metric':<25} | {'Baseline RSI-Only':<20} | {'Enhanced Strategy':<20}")
        print("-"*80)
        
        # Handle Win Rate display if no trades occurred
        win_rate_rsi = f"{stats_rsi['Win Rate [%]']:.2f}%" if not pd.isna(stats_rsi['Win Rate [%]']) else "N/A"
        win_rate_enhanced = f"{stats_enhanced['Win Rate [%]']:.2f}%" if not pd.isna(stats_enhanced['Win Rate [%]']) else "N/A"
        
        print(f"{'Total Return %':<25} | {stats_rsi['Return [%]']:>18.2f}% | {stats_enhanced['Return [%]']:>18.2f}%")
        print(f"{'Buy & Hold Return %':<25} | {stats_rsi['Buy & Hold Return [%]']:>18.2f}% | {stats_enhanced['Buy & Hold Return [%]']:>18.2f}%")
        print(f"{'Max Drawdown %':<25} | {stats_rsi['Max. Drawdown [%]']:>18.2f}% | {stats_enhanced['Max. Drawdown [%]']:>18.2f}%")
        print(f"{'Win Rate %':<25} | {win_rate_rsi:>19} | {win_rate_enhanced:>19}")
        print(f"{'Total Trades':<25} | {int(stats_rsi['# Trades']):>19} | {int(stats_enhanced['# Trades']):>19}")
        print("-"*80)

if __name__ == "__main__":
    run_comparison()