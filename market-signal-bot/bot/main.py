import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from sqlalchemy import desc

from db.database import SessionLocal, validate_paper_mode
validate_paper_mode()
from db.models import UserSubscription, init_db, PaperTrade, SystemSettings

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

def is_authorized(update: Update) -> bool:
    """
    Checks if incoming user/chat is authorized.
    Reads from TELEGRAM_ALLOWED_USERS (comma-separated user/chat IDs) or TELEGRAM_CHAT_ID.
    If neither is configured, allows in simulation/paper mode.
    """
    allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    allowed_ids = [x.strip() for x in allowed.split(",") if x.strip()]
    if not allowed_ids:
        default_chat = os.environ.get("TELEGRAM_CHAT_ID")
        if default_chat:
            allowed_ids = [default_chat.strip()]
            
    if not allowed_ids:
        return True

    user_id = str(update.effective_user.id) if update.effective_user else ""
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    return user_id in allowed_ids or chat_id in allowed_ids

async def reject_unauthorized(update: Update):
    await update.message.reply_text(
        "🔒 *Access Restricted*\n\nThis is a private trading signal bot. Your account is not authorized.",
        parse_mode="Markdown"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject_unauthorized(update)
        return
    welcome_text = (
        "👋 *Welcome to MarketSignalBot!*\n\n"
        "Use `/subscribe` to register for live technical entry/exit signals.\n"
        "Use `/unsubscribe` to opt-out of alerts.\n"
        "Use `/status` to check active trades and daily performance metrics."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject_unauthorized(update)
        return
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    
    db = SessionLocal()
    try:
        sub = db.query(UserSubscription).filter(UserSubscription.chat_id == chat_id).first()
        if not sub:
            sub = UserSubscription(chat_id=chat_id, username=username, is_active=True)
            db.add(sub)
            db.commit()
            msg = "🚀 *Subscribed!* You will now receive live confirmation signals."
        elif not sub.is_active:
            sub.is_active = True
            db.commit()
            msg = "✅ *Resubscribed!* Alerts have been reactivated for your account."
        else:
            msg = "ℹ️ You are already subscribed to live alerts."
    except Exception as e:
        db.rollback()
        msg = f"❌ *Subscription failed*: {e}"
    finally:
        db.close()
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject_unauthorized(update)
        return
    chat_id = str(update.effective_chat.id)
    
    db = SessionLocal()
    try:
        sub = db.query(UserSubscription).filter(UserSubscription.chat_id == chat_id).first()
        if sub and sub.is_active:
            sub.is_active = False
            db.commit()
            msg = "🛑 *Unsubscribed!* Alerts deactivated. You will no longer receive signal updates."
        else:
            msg = "ℹ️ You are not registered for signal alerts."
    except Exception as e:
        db.rollback()
        msg = f"❌ *Failed to unsubscribe*: {e}"
    finally:
        db.close()
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends current dashboard status, active positions, and daily performance metrics."""
    if not is_authorized(update):
        await reject_unauthorized(update)
        return
    db = SessionLocal()
    try:
        # 1. Fetch active trades
        active = db.query(PaperTrade).filter(PaperTrade.status == "ACTIVE").all()
        
        # 2. Fetch today's performance stats (IST)
        IST = ZoneInfo("Asia/Kolkata")
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now.astimezone(IST)
        ist_today_start_ist = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
        ist_today_start = ist_today_start_ist.astimezone(timezone.utc).replace(tzinfo=None)
        
        today_trades = db.query(PaperTrade).filter(PaperTrade.entry_time >= ist_today_start).all()
        closed_today = [t for t in today_trades if t.status == "CLOSED"]
        
        today_pnl = sum(t.pnl for t in closed_today)
        win_count = sum(1 for t in closed_today if t.pnl > 0)
        loss_count = sum(1 for t in closed_today if t.pnl <= 0)
        
        # Load risk thresholds
        max_loss = 5000.0
        max_trades = 5
        set_loss = db.query(SystemSettings).filter(SystemSettings.key == "max_daily_loss").first()
        if set_loss:
            max_loss = float(set_loss.value)
        set_trades = db.query(SystemSettings).filter(SystemSettings.key == "max_daily_trades").first()
        if set_trades:
            max_trades = int(set_trades.value)

        # Format Response Message
        header = "📊 *MARKET SIGNAL BOT STATUS*"
        
        # Active trades text
        active_txt = ""
        if active:
            for t in active:
                emoji = "🟢" if "CALL" in t.direction else "🔴"
                pnl_color = "+" if t.pnl >= 0 else ""
                active_txt += f"• `{t.option_contract}` ({emoji})\n  Entry: ₹{t.entry_price:.2f} | Current: ₹{t.current_price:.2f}\n"
        else:
            active_txt = "_No active open positions._\n"

        pnl_emoji = "📈" if today_pnl >= 0 else "📉"
        
        msg = (
            f"{header}\n\n"
            f"💼 *Active Positions:*\n"
            f"{active_txt}\n"
            f"💰 *Today's Realized P&L:* {pnl_emoji} *₹{today_pnl:,.2f}*\n"
            f"📊 *Win/Loss Ratio:* {win_count}W - {loss_count}L\n"
            f"🔄 *Trades Executed Today:* {len(today_trades)} / {max_trades}\n"
            f"🚨 *Daily Loss Limit:* ₹{max_loss:,.2f} ("
            f"{'SAFE' if today_pnl > -max_loss else 'BREACHED'})\n\n"
            f"⏰ *Server Time (IST):* {ist_now.strftime('%I:%M %p')}"
        )
    except Exception as e:
        msg = f"❌ *Failed to fetch status*: {e}"
    finally:
        db.close()
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def test_alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await reject_unauthorized(update)
        return
    # Verification label required by prompt
    prefix = "🧪 *TEST ALERT — PAPER MODE*\n*REAL ORDERS: DISABLED*\n\n_This is only to verify Telegram messaging and must never execute a real trade._\n\n"
    
    messages = {
        "buy_ce": prefix + (
            "🟢 *BUY CE — PAPER SIGNAL*\n\n"
            "📊 *INDEX:* NIFTY 50\n"
            "💹 *SPOT:* 24,850.25\n\n"
            "🎯 *OPTION:*\n"
            "NIFTY 24,900 CE\n"
            "Expiry: Nearest Weekly\n"
            "LTP: ₹142.50\n\n"
            "📈 *SIGNAL:*\n"
            "Direction: BULLISH\n"
            "Strategy Score: 87/100\n"
            "Trade Quality: 82/100\n"
            "ML Probability: 76%\n\n"
            "🧠 *SETUP:*\n"
            "✅ Liquidity Sweep\n"
            "✅ Bullish MSS\n"
            "✅ Bullish FVG\n"
            "✅ VWAP Support\n"
            "✅ EMA Alignment\n"
            "✅ Option Premium Momentum\n"
            "✅ OI Confirmation\n\n"
            "🎯 *PAPER ENTRY:* ₹142.50\n"
            "🛑 *STOP LOSS:* ₹125.00\n"
            "🎯 *TARGET 1:* ₹155.00\n"
            "🎯 *TARGET 2:* ₹170.00\n"
            "🎯 *TARGET 3:* ₹190.00\n\n"
            "📊 *RISK/REWARD:* 1:2.7\n"
            "🔥 *Strike Score:* 91/100\n\n"
            "⚠️ *PAPER TRADE*\n"
            "REAL ORDER: DISABLED\n\n"
            "🕐 Time: 10:25:15 IST"
        ),
        "buy_pe": prefix + (
            "🔴 *BUY PE — PAPER SIGNAL*\n\n"
            "📊 *INDEX:* BANK NIFTY\n"
            "💹 *SPOT:* 57,420.00\n\n"
            "🎯 *OPTION:*\n"
            "BANK NIFTY 57,400 PE\n"
            "LTP: ₹210.00\n\n"
            "📉 *SIGNAL:*\n"
            "Direction: BEARISH\n"
            "Strategy Score: 89/100\n"
            "Trade Quality: 85/100\n"
            "ML Probability: 79%\n\n"
            "🧠 *SETUP:*\n"
            "✅ Liquidity Sweep\n"
            "✅ Bearish MSS\n"
            "✅ Bearish FVG\n"
            "✅ VWAP Rejection\n"
            "✅ EMA Alignment\n"
            "✅ Premium Momentum\n"
            "✅ OI Confirmation\n\n"
            "🎯 *PAPER ENTRY:* ₹210.00\n"
            "🛑 *STOP LOSS:* ₹185.00\n"
            "🎯 *T1:* ₹230.00\n"
            "🎯 *T2:* ₹255.00\n"
            "🎯 *T3:* ₹290.00\n\n"
            "⚠️ *PAPER MODE*\n"
            "REAL ORDERS: DISABLED"
        ),
        "t1": prefix + (
            "🎯 *T1 HIT — PAPER TRADE*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Entry: ₹142.50\n"
            "Current: ₹155.00\n\n"
            "✅ *T1 TARGET HIT*\n\n"
            "Booked: 40%\n"
            "Remaining: 60%\n\n"
            "🛡️ *STOP LOSS MOVED TO BREAKEVEN*\n\n"
            "New SL: ₹142.50\n\n"
            "Current Paper P&L: +₹1,250.00\n\n"
            "REAL ORDER: DISABLED"
        ),
        "t2": prefix + (
            "🎯 *T2 HIT — PAPER TRADE*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Entry: ₹142.50\n"
            "Current: ₹170.00\n\n"
            "✅ *T2 TARGET HIT*\n\n"
            "Booked: Additional 30%\n"
            "Remaining: 30%\n\n"
            "🛡️ *TRAILING STOP ACTIVATED*\n\n"
            "ATR Trailing SL: ₹158.00\n\n"
            "Paper P&L: +₹2,100.00"
        ),
        "t3": prefix + (
            "🏆 *T3 HIT — PAPER TRADE CLOSED*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Entry: ₹142.50\n"
            "Exit: ₹190.00\n\n"
            "✅ *T3 HIT*\n\n"
            "Final Position: CLOSED\n"
            "Total Quantity: 100\n"
            "Profit: ₹4,750.00\n"
            "ROI: 33.3%\n\n"
            "Reason: T3 TARGET\n\n"
            "⚠️ *PAPER TRADE*\n"
            "REAL ORDERS: DISABLED"
        ),
        "sl": prefix + (
            "🛑 *STOP LOSS HIT — PAPER TRADE*\n\n"
            "📊 BANK NIFTY\n"
            "📉 BANK NIFTY 57,400 PE\n\n"
            "Entry: ₹210.00\n"
            "Exit: ₹185.00\n\n"
            "❌ *STOP LOSS HIT*\n\n"
            "Position: CLOSED\n"
            "Paper P&L: -₹1,875.00\n"
            "Reason: STOP LOSS\n\n"
            "REAL ORDER: DISABLED"
        ),
        "missed": prefix + (
            "⚠️ *ENTRY MISSED — DO NOT CHASE*\n\n"
            "📊 NIFTY 50\n"
            "📈 NIFTY 24,900 CE\n\n"
            "Calculated Entry: ₹142.50\n"
            "Current LTP: ₹151.00\n\n"
            "Price moved beyond:\n"
            "MAX_ENTRY_CHASE_PCT = 5%\n\n"
            "❌ *PAPER ENTRY CANCELLED*\n\n"
            "Reason:\n"
            "OPTION PRICE MOVED TOO FAR\n\n"
            "No trade was created."
        ),
        "invalidated": prefix + (
            "❌ *SETUP INVALIDATED — NO TRADE*\n\n"
            "📊 NIFTY 50\n\n"
            "Original Signal:\n"
            "BUY CE\n\n"
            "Re-validation:\n"
            "❌ MSS invalidated\n"
            "❌ Liquidity Sweep invalidated\n\n"
            "Option Confirmation:\n"
            "WEAK\n\n"
            "Decision:\n"
            "NO TRADE\n\n"
            "No paper position created."
        ),
        "data_fail": prefix + (
            "🚨 *MARKET DATA WARNING*\n\n"
            "Provider: FYERS\n"
            "WebSocket: DISCONNECTED\n\n"
            "Data Age: 8.4 seconds\n\n"
            "Trading Status:\n"
            "❌ NO TRADE\n\n"
            "Reason:\n"
            "REAL-TIME MARKET DATA UNAVAILABLE\n\n"
            "The bot must not generate a new trade signal until the feed becomes healthy again."
        ),
        "summary": prefix + (
            "📊 *DAILY PAPER TRADING SUMMARY*\n\n"
            "Date: 24-08-2026\n\n"
            "Trades: 8\n"
            "Wins: 5\n"
            "Losses: 3\n"
            "Win Rate: 62.5%\n\n"
            "Gross P&L: ₹8,125.00\n"
            "Net P&L: ₹7,850.00\n"
            "Max Drawdown: ₹1,500.00\n\n"
            "Best Index:\n"
            "NIFTY 50\n\n"
            "Best Setup:\n"
            "Liquidity Sweep + MSS + FVG\n\n"
            "⚠️ *PAPER TRADING*\n"
            "REAL ORDERS: DISABLED"
        )
    }

    args = context.args
    if args and args[0].lower() in messages:
        target = args[0].lower()
        await update.message.reply_text(messages[target], parse_mode="Markdown")
    else:
        await update.message.reply_text("🧪 *Starting Telegram alert templates test loop...*", parse_mode="Markdown")
        for key, msg in messages.items():
            try:
                await update.message.reply_text(msg, parse_mode="Markdown")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Telegram error in test alert loop: {e}")
        await update.message.reply_text("✅ *Telegram alert templates test completed successfully.*", parse_mode="Markdown")

from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram Token not configured. Daemon lifespan starting without polling.")
        yield
        return
        
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("test_alert", test_alert_cmd))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("Telegram Bot listener daemon successfully started in background.")
    app.state.tg_app = application
    
    yield
    
    application = getattr(app.state, "tg_app", None)
    if application:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        print("Telegram Bot stopped.")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("CRITICAL: TELEGRAM_BOT_TOKEN environment variable not set. Bot exiting.")
        return
        
    # Ensure database table existence
    init_db()
    
    import uvicorn
    
    app = FastAPI(title="MarketSignalBot Telegram Listener Service", lifespan=lifespan)
    
    @app.get("/health")
    def health():
        return {"status": "healthy", "service": "bot"}
        
    port = int(os.environ.get("BOT_PORT", os.environ.get("PORT", 10001)))
    print(f"Starting web server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
