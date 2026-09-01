# Cloud Deployment Guide — 24/7 Continuous Paper Trading

This guide details the steps to deploy the trading bot on an always-on Linux cloud server (VPS) to run the 1-minute scanner and virtual paper trading continuously, completely independent of your laptop.

---

## 1. Cloud Server Requirements

* **Operating System**: Ubuntu 22.04 LTS (or any modern Linux distribution with Docker support)
* **Minimum Specifications**:
  * 1 vCPU (2 vCPUs recommended)
  * 1 GB RAM (2 GB recommended)
  * 10 GB SSD Storage space
* **Software Prerequisites**:
  * **Docker Engine** (version 20.10+)
  * **Docker Compose** (version 2.0+)

---

## 2. Environment Variables Configuration

Create a `.env` file in the `market-signal-bot` folder on your server. Do not hardcode values in configuration files.

```env
# --- SYSTEM MODE & SAFETY ENFORCEMENT ---
# Enforce paper trading only (production default)
SYSTEM_MODE=PAPER
REAL_ORDERS_ENABLED=false

# --- DATA PROVIDER CONFIGURATION ---
# Options: 'realtime' or 'yfinance'
MARKET_DATA_PROVIDER=realtime

# --- FYERS API CREDENTIALS ---
FYERS_CLIENT_ID=your_fyers_client_id
FYERS_SECRET_KEY=your_fyers_secret_key
FYERS_ACCESS_TOKEN=your_fyers_access_token

# --- TELEGRAM BOT CONFIGURATION ---
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_broadcast_chat_id
```

---

## 3. Deployment Commands (Docker Compose)

The project includes a `docker-compose.yml` file that orchestrates all five services (`db`, `api`, `worker`, `bot`, `frontend`).

### Build and Start Services
Runs in detached mode (background) and pulls/builds the images:
```bash
docker compose up --build -d
```

### Stop Services
Stops running containers without deleting database volumes:
```bash
docker compose down
```

### Restart Services
Restarts all containers:
```bash
docker compose restart
```

### Check Logs
* **All Services**:
  ```bash
  docker compose logs -f
  ```
* **Trading Scanner (Worker) Logs**:
  ```bash
  docker compose logs -f worker
  ```
* **API Service Logs**:
  ```bash
  docker compose logs -f api
  ```
* **Telegram Bot Logs**:
  ```bash
  docker compose logs -f bot
  ```

---

## 4. Verification & Health Monitoring

### Confirm Paper Mode & Safety
On container startup, the `api`, `worker`, and `bot` services run the centralized `validate_paper_mode()` function. 
* If `REAL_ORDERS_ENABLED=true` is set, the process terminates immediately on boot with code 1.
* Check the logs to ensure there are no safety exit logs.

### Check Service Health
Query the `/health` REST endpoint on your VPS server (Port 8000):
```bash
curl http://<your_server_ip>:8000/health
```
**Expected Response**:
```json
{
  "api": "HEALTHY",
  "database": "HEALTHY",
  "worker": "RUNNING",
  "provider": "fyers",
  "connection": "CONNECTED",
  "websocket": "CONNECTED",
  "data_age": "1.2 sec",
  "latency": "120.0ms",
  "telegram": "CONNECTED",
  "mode": "PAPER",
  "real_orders_enabled": false,
  "trading_eligibility": true
}
```

### Verify Fyers Connection
1. Run `docker compose logs worker`.
2. Verify that logs state:
   * `"RealTimeMarketDataProvider initialized."`
   * `"WebSocket ticks stream parser starting..."`
   * `"overall_status: GOOD"` inside scan telemetry.

### Verify Telegram Alerts
Trigger a test loop directly via your Telegram bot chat:
1. Send the command: `/test_alert`
2. Confirm your phone receives all 10 sample alerts with the header:
   `🧪 TEST ALERT — PAPER MODE`
   `REAL ORDERS: DISABLED`

---

## 5. Laptop-Off Test Procedure

To verify that the VPS server is fully executing the bot with your laptop powered down:
1. SSH into the cloud server.
2. Run `docker compose up -d` to spin up all services.
3. Check `curl http://localhost:8000/health` to confirm `connection: CONNECTED` and `trading_eligibility: true`.
4. Turn **OFF** your laptop (disconnect internet and close the lid).
5. Wait for 5 to 15 minutes.
6. Verify your mobile Telegram app receives live signal updates and status warnings directly from the cloud bot.
7. Turn your laptop back on, load the React Dashboard, and verify that the trade logs and performance metrics were updated while your laptop was offline.
