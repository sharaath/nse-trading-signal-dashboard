from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, inspect, text
from datetime import datetime, timezone
from .database import Base, engine

class SignalHistory(Base):
    __tablename__ = "signal_history"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    instrument_type = Column(String, default="STOCK")  # STOCK, INDEX
    price = Column(Float)
    signal = Column(String)  # BUY, SELL, HOLD
    confidence = Column(Float)  # percentage (e.g. 75.0)
    reason = Column(String)
    reject_reason = Column(String, nullable=True)
    indicators = Column(String)  # Comma-separated list of triggered indicators
    system_mode = Column(String, default="PAPER")  # LIVE, PAPER, SIMULATION
    data_source = Column(String, default="yfinance")
    
    # Extended Scores
    strategy_score = Column(Float, default=0.0)
    ml_probability = Column(Float, default=0.0)
    trade_quality_score = Column(Float, default=0.0)
    
    # Selected Strike & Targets
    option_contract = Column(String, nullable=True)
    strike = Column(Integer, nullable=True)
    option_type = Column(String, nullable=True)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_1 = Column(Float, nullable=True)
    target_2 = Column(Float, nullable=True)
    target_3 = Column(Float, nullable=True)
    
    # Structural state machines
    mss_state = Column(String, default="NOT_PRESENT")
    sweep_state = Column(String, default="NOT_PRESENT")
    fvg_state = Column(String, default="NOT_PRESENT")
    ob_state = Column(String, default="NOT_PRESENT")
    breaker_state = Column(String, default="NOT_PRESENT")
    po3_state = Column(String, default="NOT_PRESENT")
    crt_state = Column(String, default="NOT_PRESENT")
    option_state = Column(String, default="INVALID")
    
    # Execution metrics
    signal_price = Column(Float, default=0.0)
    bid_price = Column(Float, default=0.0)
    ask_price = Column(Float, default=0.0)
    entry_spread = Column(Float, default=0.0)
    entry_spread_pct = Column(Float, default=0.0)
    fill_price = Column(Float, default=0.0)
    slippage_pct = Column(Float, default=0.0)
    slippage_amount = Column(Float, default=0.0)
    brokerage = Column(Float, default=0.0)
    stt = Column(Float, default=0.0)
    gst = Column(Float, default=0.0)
    exchange_charges = Column(Float, default=0.0)
    total_transaction_cost = Column(Float, default=0.0)
    gross_pnl = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, unique=True, index=True)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class StrategyState(Base):
    __tablename__ = "strategy_states"
    
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, unique=True, index=True)
    is_enabled = Column(Boolean, default=True)

class OptionMomentumHistory(Base):
    __tablename__ = "option_momentum_history"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    strike = Column(Integer)
    option_type = Column(String)
    contract = Column(String)
    old_premium = Column(Float)
    new_premium = Column(Float)
    pct_change = Column(Float)
    oi_change = Column(Integer)
    volume = Column(Integer)
    spot_price = Column(Float)
    data_source = Column(String, default="live")
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    direction = Column(String)  # BUY_CALL or BUY_PUT
    option_contract = Column(String)
    qty = Column(Integer)
    initial_qty = Column(Integer, default=0)
    entry_price = Column(Float)
    current_price = Column(Float)
    stop_loss = Column(Float)
    target_1 = Column(Float)
    target_2 = Column(Float)
    target_3 = Column(Float)
    trailing_stop = Column(Float)
    partial_exit_1 = Column(Boolean, default=False)  # T1 partial exit
    partial_exit_2 = Column(Boolean, default=False)  # T2 partial exit
    status = Column(String, default="ACTIVE")  # ACTIVE, CLOSED
    pnl = Column(Float, default=0.0)
    roi = Column(Float, default=0.0)
    signal_score = Column(Float)
    confidence = Column(Float)
    trade_quality_score = Column(Float)
    reason = Column(String)
    reject_reason = Column(String, nullable=True)
    system_mode = Column(String, default="PAPER")  # LIVE, PAPER, SIMULATION
    data_source = Column(String, default="yfinance")
    
    # Structural state machine logs
    mss_state = Column(String, default="ACTIVE")
    sweep_state = Column(String, default="ACTIVE")
    fvg_state = Column(String, default="ACTIVE")
    ob_state = Column(String, default="ACTIVE")
    breaker_state = Column(String, default="ACTIVE")
    po3_state = Column(String, default="ACTIVE")
    crt_state = Column(String, default="ACTIVE")
    option_state = Column(String, default="STRONG")

    # Auditable execution metrics
    signal_price = Column(Float, default=0.0)
    bid_price = Column(Float, default=0.0)
    ask_price = Column(Float, default=0.0)
    entry_spread = Column(Float, default=0.0)
    entry_spread_pct = Column(Float, default=0.0)
    fill_price = Column(Float, default=0.0)
    slippage_pct = Column(Float, default=0.0)
    slippage_amount = Column(Float, default=0.0)
    brokerage = Column(Float, default=0.0)
    stt = Column(Float, default=0.0)
    gst = Column(Float, default=0.0)
    exchange_charges = Column(Float, default=0.0)
    total_transaction_cost = Column(Float, default=0.0)
    gross_pnl = Column(Float, default=0.0)
    net_pnl = Column(Float, default=0.0)

    # Scalping & MFE/MAE Execution tracking
    signal_id = Column(String, nullable=True)
    exit_reason = Column(String, nullable=True)  # TP_EXIT, SL_EXIT, TIME_EXIT, EOD_EXIT
    mfe = Column(Float, default=0.0)  # Maximum Favorable Excursion
    mae = Column(Float, default=0.0)  # Maximum Adverse Excursion
    max_holding_time_minutes = Column(Integer, default=5)

    entry_time = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    exit_time = Column(DateTime(timezone=True), nullable=True)

class DataQuality(Base):
    __tablename__ = "data_quality"
    
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String)
    symbol = Column(String, unique=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    age_seconds = Column(Float, nullable=True)
    is_fresh = Column(Boolean, default=False)
    source_mode = Column(String)
    data_status = Column(String)
    missing_fields = Column(String, default="")
    latency_ms = Column(Float, default=0.0)
    trading_eligible = Column(Boolean, default=False)

class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)

class ScanLog(Base):
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    market = Column(String, index=True)
    spot_price = Column(Float)
    data_age = Column(Float)
    data_latency = Column(Float)
    strategy_score = Column(Float)
    ml_probability = Column(Float)
    trade_quality = Column(Float)
    direction = Column(String)
    option_confirmation = Column(String)
    selected_strike = Column(String)
    strike_score = Column(Float)
    signal = Column(String)
    rejection_reason = Column(String, nullable=True)

# Create tables and auto-migrate missing columns in startup
def init_db():
    Base.metadata.create_all(bind=engine)
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        with engine.connect() as conn:
            for table_name, table in Base.metadata.tables.items():
                if table_name in existing_tables:
                    existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(engine.dialect)
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"))
            conn.commit()
    except Exception as e:
        print(f"Warning during DB auto-migration: {e}")

