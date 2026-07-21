import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import init_db, SignalHistory, UserSubscription, StrategyState
from signals.providers import YFinanceDataProvider
from signals.engine import calculate_consensus_signal

MONITORED_TICKERS = ["^NSEI", "^BSESN", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"]
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PERSONAL_USE_ONLY = os.environ.get("PERSONAL_USE_ONLY", "true").lower() == "true"

def send_telegram_alert(message: str, chat_id: str):
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram Token not configured. Alert skipped.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
    except Exception as e:
        print(f"Error sending telegram alert: {e}")

def get_enabled_strategies(db: Session) -> list:
    strategies = db.query(StrategyState).filter(StrategyState.is_enabled == True).all()
    if not strategies:
        # Default all enabled if table is empty
        return ["ema_crossover", "rsi", "macd", "bollinger_bands"]
    return [s.strategy_name for s in strategies]

def get_last_signal(db: Session, symbol: str) -> str:
    last_record = db.query(SignalHistory).filter(SignalHistory.symbol == symbol).order_index = SignalHistory.timestamp.desc()
    # Wait, SQLAlchemy order_by syntax is order_by(desc(SignalHistory.timestamp))
    # Let's write it cleanly:
    from sqlalchemy import desc
    last_record = db.query(SignalHistory).filter(SignalHistory.symbol == symbol).order_by(desc(SignalHistory.timestamp)).first()
    return last_record.signal if last_record else "HOLD"

def run_market_scan():
    # 1. Verify market hours (IST: 9:15 AM to 3:30 PM, Monday-Friday)
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    
    # Check if weekday (0-4 are Mon-Fri)
    if ist_now.weekday() >= 5:
        print(f"Weekend ({ist_now.strftime('%A')}). Scanning skipped.")
        return
        
    market_start = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    # Allow scanning overrides in non-production docker configurations for testing
    force_scan = os.environ.get("FORCE_SCAN", "false").lower() == "true"
    
    if not force_scan and not (market_start <= ist_now <= market_end):
        print(f"Outside market hours ({ist_now.strftime('%H:%M:%S IST')}). Scanning skipped.")
        return
        
    print(f"Executing market scan job at {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}...")
    db = SessionLocal()
    provider = YFinanceDataProvider()
    enabled_strats = get_enabled_strategies(db)
    
    for symbol in MONITORED_TICKERS:
        df = provider.get_history(symbol)
        if df.empty:
            print(f"No history data fetched for {symbol}.")
            continue
            
        latest_row = df.iloc[-1]
        close_price = float(latest_row['Close'])
        
        analysis = calculate_consensus_signal(df, enabled_strats, symbol=symbol)
        sig = analysis['signal']
        
        # Check transition to prevent spam
        prev_sig = get_last_signal(db, symbol)
        
        # Save signal in history
        history_entry = SignalHistory(
            symbol=symbol,
            price=close_price,
            signal=sig,
            confidence=analysis['confidence'],
            reason=analysis['reason'],
            indicators=analysis['indicators']
        )
        db.add(history_entry)
        db.commit()
        
        print(f"Analyzed {symbol}: Spot={close_price:.2f} | Prev={prev_sig} -> Current={sig}")
        
        # If transition occurs and is BUY/SELL, send alerts
        if sig in ["BUY", "SELL"] and sig != prev_sig:
            emoji = "🟢 BUY" if sig == "BUY" else "🔴 SELL"
            t1 = analysis.get('target1', close_price * 1.025)
            t2 = analysis.get('target2', close_price * 1.050)
            sl = analysis.get('stop_loss', close_price * 0.985)
            
            t1_pct = ((t1 - close_price) / close_price) * 100 if sig == "BUY" else ((close_price - t1) / close_price) * 100
            t2_pct = ((t2 - close_price) / close_price) * 100 if sig == "BUY" else ((close_price - t2) / close_price) * 100
            sl_pct = ((close_price - sl) / close_price) * 100 if sig == "BUY" else ((sl - close_price) / close_price) * 100
            
            opt_contract = analysis.get('option_contract', 'N/A')
            opt_entry = analysis.get('option_entry', 0.0)
            opt_target = analysis.get('option_target', 0.0)
            opt_sl = analysis.get('option_sl', 0.0)
            
            sig_time_str = ist_now.strftime("%H:%M:%S IST")
            start_win_str = ist_now.strftime("%I:%M %p IST")
            end_win_str = (ist_now + timedelta(minutes=5)).strftime("%I:%M %p IST")
            
            sym_clean = symbol.replace("^", "").replace(".NS", "")
            
            if sig == "BUY":
                msg = (
                    f"🟢 *BUY SIGNAL TRIGGERED*\n\n"
                    f"*Instrument:* `{sym_clean}`\n\n"
                    f"*Signal Time:* {sig_time_str}\n\n"
                    f"⏰ *ENTRY WINDOW*\n"
                    f"Enter Between: {start_win_str} – {end_win_str}\n"
                    f"Trade Valid Until: {end_win_str}\n\n"
                    f"*Spot Entry:* ₹{close_price:,.2f}\n\n"
                    f"🎯 *Target 1:* ₹{t1:,.2f} (+{abs(t1_pct):.1f}%)\n"
                    f"🎯 *Target 2:* ₹{t2:,.2f} (+{abs(t2_pct):.1f}%)\n\n"
                    f"🛑 *Stop Loss:* ₹{sl:,.2f} (-{abs(sl_pct):.1f}%)\n\n"
                    f"📊 *OPTION TRADE*\n"
                    f"Contract: `{opt_contract}`\n"
                    f"Premium Entry: ₹{opt_entry:,.2f}\n\n"
                    f"🎯 *Option Target:* ₹{opt_target:,.2f} (+30%)\n"
                    f"🛑 *Option Stop Loss:* ₹{opt_sl:,.2f} (-15%)\n\n"
                    f"📈 *Confidence:* {analysis['confidence']:.0f}%\n"
                    f"Timeframe: 15 Minutes\n"
                    f"Strategy: EMA20 + MACD + RSI"
                )
            else:
                msg = (
                    f"🔴 *SELL SIGNAL TRIGGERED*\n\n"
                    f"*Instrument:* `{sym_clean}`\n\n"
                    f"*Signal Time:* {sig_time_str}\n\n"
                    f"*Spot Exit:* ₹{close_price:,.2f}\n\n"
                    f"📊 *OPTION TRADE*\n"
                    f"Contract: `{opt_contract}`\n"
                    f"Premium Entry: ₹{opt_entry:,.2f}\n\n"
                    f"🎯 *Option Target:* ₹{opt_target:,.2f} (+30%)\n"
                    f"🛑 *Option Stop Loss:* ₹{opt_sl:,.2f} (-15%)\n\n"
                    f"📈 *Confidence:* {analysis['confidence']:.0f}%\n"
                    f"Timeframe: 15 Minutes\n"
                    f"Strategy: EMA20 + MACD + RSI"
                )
            
            # Send to all active subscribers
            subs = db.query(UserSubscription).filter(UserSubscription.is_active == True).all()
            for sub in subs:
                send_telegram_alert(msg, sub.chat_id)
                
    db.close()

def main():
    print("Initializing Database tables...")
    init_db()
    
    # Initialize default strategies if table is empty
    db = SessionLocal()
    if db.query(StrategyState).count() == 0:
        default_strats = ["ema_crossover", "rsi", "macd", "bollinger_bands"]
        for s in default_strats:
            db.add(StrategyState(strategy_name=s, is_enabled=True))
        db.commit()
    db.close()
    
    if PERSONAL_USE_ONLY:
        print("\n" + "="*80)
        print("WARNING: PERSONAL_USE_ONLY is set to true.")
        print("Note that public distribution of trading recommendations in India may require SEBI registration.")
        print("="*80 + "\n")
        
    # Start Scheduler in Background
    from apscheduler.schedulers.background import BackgroundScheduler
    from fastapi import FastAPI
    import uvicorn

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_market_scan, 'interval', minutes=15, next_run_time=datetime.now())
    print("APScheduler polling worker successfully started in background.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass

    # Dummy Web Server to satisfy Render Free Tier health checks
    app = FastAPI(title="MarketSignalBot Worker Service")
    @app.get("/health")
    def health():
        return {"status": "healthy", "service": "worker"}
        
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting web server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
