import os
import urllib.request
import urllib.error
import json
from dotenv import load_dotenv

load_dotenv()

token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")
print(f"Testing Telegram bot with token: {token[:10]}... and chat_id: {chat_id}")

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": "🔥 CRT + PO3 Bot Online & Ready!\n\n• System Mode: PAPER_TRADING\n• Strategy: CRT + PO3 Fast Scalping\n• Status: NOTIFICATIONS READY"
}
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        print("Success! Response:")
        print(resp.read().decode())
except urllib.error.HTTPError as e:
    print("HTTP Error code:", e.code)
    print("Details:", e.read().decode())
except Exception as e:
    print("Other error:", e)
