from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from .database import Base, engine

class SignalHistory(Base):
    __tablename__ = "signal_history"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    price = Column(Float)
    signal = Column(String)  # BUY, SELL, HOLD
    confidence = Column(Float)  # percentage (e.g. 75.0)
    reason = Column(String)
    indicators = Column(String)  # Comma-separated list of triggered indicators
    timestamp = Column(DateTime, default=datetime.utcnow)

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, unique=True, index=True)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class StrategyState(Base):
    __tablename__ = "strategy_states"
    
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, unique=True, index=True)
    is_enabled = Column(Boolean, default=True)

# Create tables in startup if migrations are not run
def init_db():
    Base.metadata.create_all(bind=engine)
