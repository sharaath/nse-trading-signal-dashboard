import pandas as pd
import ta
from typing import Dict, Any, List

def calculate_consensus_signal(df: pd.DataFrame, enabled_strategies: List[str] = None) -> Dict[str, Any]:
    """
    Evaluates indicators on the latest completed row (df.iloc[-2]) and returns:
    - Signal: BUY, SELL, or HOLD
    - Confidence: consensus score (%)
    - Reason: text description of active indicator conditions
    - Triggered Indicators: list of indicator names that generated triggers
    """
    if df.empty or len(df) < 30:
        return {"signal": "HOLD", "confidence": 0.0, "reason": "Insufficient data", "indicators": ""}
        
    if not enabled_strategies:
        enabled_strategies = ["ema_crossover", "rsi", "macd", "bollinger_bands"]
        
    df = df.copy()
    
    # 1. EMA Crossover (EMA9 / EMA21)
    df['EMA9'] = ta.trend.EMAIndicator(df['Close'], window=9).ema_indicator()
    df['EMA21'] = ta.trend.EMAIndicator(df['Close'], window=21).ema_indicator()
    
    # 2. RSI(14)
    df['RSI'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    
    # 3. MACD
    macd_obj = ta.trend.MACD(df['Close'])
    df['MACD'] = macd_obj.macd()
    df['MACD_Signal'] = macd_obj.macd_signal()
    df['MACD_Diff'] = macd_obj.macd_diff()
    
    # 4. Bollinger Bands
    bb_obj = ta.volatility.BollingerBands(df['Close'])
    df['BB_High'] = bb_obj.bollinger_hband()
    df['BB_Low'] = bb_obj.bollinger_lband()
    
    # We evaluate on the last completed row (index -2) to prevent repainting live candles
    row = df.iloc[-2]
    prev_row = df.iloc[-3]
    
    buy_votes = []
    sell_votes = []
    
    # --- EMA Crossover Strategy ---
    if "ema_crossover" in enabled_strategies:
        # Cross above
        if row['EMA9'] > row['EMA21'] and prev_row['EMA9'] <= prev_row['EMA21']:
            buy_votes.append("EMA Crossover")
        # Cross below
        elif row['EMA9'] < row['EMA21'] and prev_row['EMA9'] >= prev_row['EMA21']:
            sell_votes.append("EMA Crossover")
            
    # --- RSI Strategy ---
    if "rsi" in enabled_strategies:
        if row['RSI'] < 30:
            buy_votes.append("RSI Oversold")
        elif row['RSI'] > 70:
            sell_votes.append("RSI Overbought")
            
    # --- MACD Crossover Strategy ---
    if "macd" in enabled_strategies:
        # MACD Line crosses above Signal Line
        if row['MACD'] > row['MACD_Signal'] and prev_row['MACD'] <= prev_row['MACD_Signal']:
            buy_votes.append("MACD Bullish Cross")
        # MACD Line crosses below Signal Line
        elif row['MACD'] < row['MACD_Signal'] and prev_row['MACD'] >= prev_row['MACD_Signal']:
            sell_votes.append("MACD Bearish Cross")
            
    # --- Bollinger Bands Strategy ---
    if "bollinger_bands" in enabled_strategies:
        if row['Close'] <= row['BB_Low']:
            buy_votes.append("Bollinger Low Breakout")
        elif row['Close'] >= row['BB_High']:
            sell_votes.append("Bollinger High Breakout")
            
    # Calculate consensus
    total_strategies = len(enabled_strategies)
    if not total_strategies:
        return {"signal": "HOLD", "confidence": 0.0, "reason": "No active strategies", "indicators": ""}
        
    num_buys = len(buy_votes)
    num_sells = len(sell_votes)
    
    if num_buys > 0 and num_buys >= num_sells:
        signal = "BUY"
        triggered = buy_votes
        confidence = (num_buys / total_strategies) * 100
        reason = f"Bullish consensus: {', '.join(buy_votes)}"
    elif num_sells > 0 and num_sells > num_buys:
        signal = "SELL"
        triggered = sell_votes
        confidence = (num_sells / total_strategies) * 100
        reason = f"Bearish consensus: {', '.join(sell_votes)}"
    else:
        signal = "HOLD"
        triggered = []
        confidence = 0.0
        reason = "No consensus reached / Trend is neutral"
        
    # Consensus Threshold: If confidence is too low (e.g. only 1 of 4 agree, which is 25.0%), output HOLD
    # We require at least 50% consensus (2 of 4 agree) to trigger a BUY or SELL
    if confidence < 50.0:
        signal = "HOLD"
        
    return {
        "signal": signal,
        "confidence": confidence,
        "reason": reason,
        "indicators": ", ".join(triggered)
    }
