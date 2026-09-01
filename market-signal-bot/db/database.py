import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    # If running locally outside Docker without postgres set, default to SQLite
    if not os.path.exists("/.dockerenv"):
        DATABASE_URL = "sqlite:///marketsignalbot.db"
    else:
        DATABASE_URL = "postgresql://postgres:postgres@db:5432/marketsignalbot"

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def validate_paper_mode(bypass_test_check=True):
    import os
    import sys
    
    # Bypass during test session to allow simulation/backtesting unit tests
    if bypass_test_check and ("pytest" in sys.modules or any("pytest" in arg for arg in sys.argv)):
        return
        
    system_mode = os.environ.get("SYSTEM_MODE", "PAPER").upper()
    real_orders = os.environ.get("REAL_ORDERS_ENABLED", "false").lower() == "true"
    
    if system_mode != "PAPER" or real_orders:
        sys.exit("CRITICAL SAFETY BLOCK: Real orders are enabled or SYSTEM_MODE is not PAPER! Startup blocked.")
