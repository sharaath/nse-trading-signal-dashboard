import os
import math
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import OptionMomentumHistory
from signals.option_chain_provider import NSEOptionChainProvider
from signals.option_momentum import OptionMomentumDetector

logger = logging.getLogger(__name__)

# Singletons for continuous worker scanning
chain_provider = NSEOptionChainProvider()
momentum_detector = OptionMomentumDetector(min_pct_change=8.0, strikes_around_atm=3)

def send_telegram_alert(message: str, chat_id: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.info("Telegram Token not configured. Option momentum alert skipped.")
        return
    import urllib.request
    import urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
    except Exception as e:
        logger.error(f"Error sending option momentum Telegram alert: {e}")

def run_option_momentum_scan():
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)

    # Check weekday (Mon-Fri)
    if ist_now.weekday() >= 5:
        logger.info(f"Weekend ({ist_now.strftime('%A')}). Option momentum scan skipped.")
        return

    market_start = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
    force_scan = os.environ.get("FORCE_SCAN", "false").lower() == "true"

    if not force_scan and not (market_start <= ist_now <= market_end):
        logger.info(f"Outside market hours ({ist_now.strftime('%H:%M:%S IST')}). Option scan skipped.")
        return

    logger.info(f"Executing fast-option momentum scan at {ist_now.strftime('%Y-%m-%d %H:%M:%S IST')}...")
    db = SessionLocal()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    symbols_to_scan = ["NIFTY", "BANKNIFTY"]

    try:
        for symbol in symbols_to_scan:
            chain = chain_provider.fetch_option_chain(symbol)
            alerts = momentum_detector.detect_momentum(chain, symbol)

            for alert in alerts:
                # Save entry in DB
                history_entry = OptionMomentumHistory(
                    symbol=alert["symbol"],
                    strike=alert["strike"],
                    option_type=alert["option_type"],
                    contract=alert["contract"],
                    old_premium=alert["old_premium"],
                    new_premium=alert["new_premium"],
                    pct_change=alert["pct_change"],
                    oi_change=alert["oi_change"],
                    volume=alert["volume"],
                    spot_price=alert["spot_price"],
                    data_source=alert.get("data_source", "live"),
                )
                db.add(history_entry)
                db.commit()

                logger.info(f"FAST OPTION MOVE ({alert.get('data_source')}): {alert['contract']} | Premium: ₹{alert['old_premium']:.2f} -> ₹{alert['new_premium']:.2f} (+{alert['pct_change']}%)")

                # Dispatch Telegram alert
                if chat_id:
                    sig_time_str = ist_now.strftime("%H:%M:%S IST")
                    sym_clean = "NIFTY 50" if alert["symbol"] == "NIFTY" else "BANKNIFTY"
                    opt_emoji = "🟢 CE (Bullish Surge)" if alert["option_type"] == "CE" else "🔴 PE (Bearish Surge)"

                    is_simulated = alert.get("data_source") == "simulated"
                    header = "⚠️ *SIMULATED DATA — NOT A REAL SIGNAL*" if is_simulated else "⚡ *FAST OPTION MOVE DETECTED*"

                    msg = (
                        f"{header}\n\n"
                        f"*Index:* `{sym_clean}`\n"
                        f"*Contract:* `{alert['contract']}` ({opt_emoji})\n\n"
                        f"🚀 *Premium Jump:* ₹{alert['old_premium']:,.2f} → ₹{alert['new_premium']:,.2f} (+{alert['pct_change']:.1f}%)\n"
                        f"📊 *OI Build-Up:* +{alert['oi_change']:,}\n"
                        f"📈 *Volume:* {alert['volume']:,}\n"
                        f"📍 *Spot Price:* ₹{alert['spot_price']:,.2f}\n\n"
                        f"⏰ *Detected Time:* {sig_time_str}\n"
                        f"_Momentum alert triggered by 1-minute premium spike with rising OI._"
                    )
                    send_telegram_alert(msg, chat_id)
    except Exception as e:
        logger.error(f"Error executing option momentum scan: {e}")
    finally:
        db.close()
