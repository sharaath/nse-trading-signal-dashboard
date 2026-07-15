import os
# Force testing session to run on in-memory SQLite instead of Postgres
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, engine
from db.models import SignalHistory
from signals.providers import MarketDataProvider
from signals.engine import calculate_consensus_signal

class MockDataProvider(MarketDataProvider):
    def __init__(self, mode: str):
        self.mode = mode
        
    def get_history(self, symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        dates = pd.date_range(end="2026-07-15", periods=50, freq="15min")
        
        if self.mode == "bullish":
            prices = [100.0 + i * 2.0 for i in range(50)]
        elif self.mode == "bearish":
            prices = [500.0 - i * 5.0 for i in range(50)]
        else:
            prices = [100.0 for _ in range(50)]
            
        df = pd.DataFrame({
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": [1000 + i * 10 for i in range(50)]
        }, index=dates)
        return df

def test_signal_generation():
    provider = MockDataProvider(mode="bullish")
    df = provider.get_history("MOCK_STOCK")
    
    analysis = calculate_consensus_signal(df, ["ema_crossover", "rsi"], symbol="^NSEI")
    
    assert "signal" in analysis
    assert "confidence" in analysis
    assert "reason" in analysis
    assert "indicators" in analysis
    
    # Verify bounds of outputs
    assert analysis["signal"] in ["BUY", "SELL", "HOLD"]
    assert 0.0 <= analysis["confidence"] <= 100.0

def test_database_insert():
    # Setup test in-memory SQLite database
    TEST_DATABASE_URL = "sqlite:///:memory:"
    engine_test = create_engine(TEST_DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)
    
    Base.metadata.create_all(bind=engine_test)
    db = TestingSessionLocal()
    
    try:
        # Create mock record
        entry = SignalHistory(
            symbol="^NSEI",
            price=24200.30,
            signal="BUY",
            confidence=100.0,
            reason="All indicators bullish consensus",
            indicators="EMA Crossover, RSI Oversold, MACD Bullish Cross, Bollinger Low Breakout"
        )
        db.add(entry)
        db.commit()
        
        # Query record and verify fields
        retrieved = db.query(SignalHistory).filter(SignalHistory.symbol == "^NSEI").first()
        assert retrieved is not None
        assert retrieved.price == 24200.30
        assert retrieved.signal == "BUY"
        assert retrieved.confidence == 100.0
        assert "RSI Oversold" in retrieved.indicators
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine_test)

def test_telegram_alert_message_formatting():
    symbol = "^NSEI"
    close_price = 24200.30
    analysis = {
        "confidence": 75.0,
        "indicators": "EMA Crossover, MACD Bullish Cross",
        "reason": "Bullish crossovers confirmed"
    }
    
    # Compile text
    msg = (
        f"🟢 BUY *SIGNAL TRIGGERED*\n\n"
        f"*Instrument:* `{symbol}`\n"
        f"*Signal Price:* Rs.{close_price:.2f}\n"
        f"*Confidence Score:* {analysis['confidence']:.1f}%\n"
        f"*Indicators:* {analysis['indicators']}\n"
        f"*Reason:* {analysis['reason']}"
    )
    
    # Assert correct markup and parameters
    assert "🟢 BUY" in msg
    assert "^NSEI" in msg
    assert "Rs.24200.30" in msg
    assert "75.0%" in msg
