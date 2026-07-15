import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from db.database import SessionLocal
from db.models import UserSubscription, init_db

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 *Welcome to MarketSignalBot!*\n\n"
        "Use `/subscribe` to register for live technical entry/exit signals.\n"
        "Use `/unsubscribe` to opt-out of alerts."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("CRITICAL: TELEGRAM_BOT_TOKEN environment variable not set. Bot exiting.")
        return
        
    # Ensure database table existence
    init_db()
    
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    
    print("Telegram Bot listener daemon successfully started.")
    application.run_polling()

if __name__ == "__main__":
    main()
