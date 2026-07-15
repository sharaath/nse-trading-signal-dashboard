# MarketSignalBot

A dockerized full-stack trading analysis bot that polls live NSE (Nifty 50) and BSE (Sensex) index/stock feeds, calculates technical indicator crossovers, saves trades in a PostgreSQL ledger, and dispatches automated alerts to users via Telegram commands.

---

## Architecture Setup

* **FastAPI Backend (Port `8000`)**: Serves historical signals, health endpoints, and strategy state managers.
* **APScheduler Worker**: Runs scanning ticks every 15 minutes during Indian market hours (9:15 AM - 3:30 PM IST), checking indicators and saving logs.
* **Telegram Listener (Bot)**: Manages Subscriber chat registrations using `/subscribe` and `/unsubscribe`.
* **PostgreSQL (Port `5432`)**: Stores subscriptions, system states, and signal records.
* **React Dashboard (Port `5173`)**: Recharts visual graphs, logs feeds, and supports admin toggles.

---

## Installation & Launch

### 1. Configure Credentials
Copy `.env.example` to `.env` and fill in your Telegram bot tokens:
```bash
cp .env.example .env
```
Inside `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_father_token_here
TELEGRAM_CHAT_ID=-1000000000000
```

### 2. Boot Service Containers
Use Docker Compose to build and start all linked nodes:
```bash
docker-compose up --build
```
Once initialized:
* **Frontend**: Open `http://localhost:5173`
* **API Documentation**: Open `http://localhost:8000/docs`

---

## Running Integration Tests
To run the automated pipeline validation:
```bash
pip install -r requirements.txt
pytest tests/test_pipeline.py
```

---

## How to Implement a New Technical Strategy

Pluggable strategies can be added by following these steps:

1. **Write the Strategy Indicator Logic** in `signals/engine.py`:
   Define the calculation parameters on the DataFrame and append to `buy_votes` or `sell_votes` lists. For example, adding an **ADX Trend strength** check:
   ```python
   # Inside signals/engine.py calculate_consensus_signal()
   if "adx" in enabled_strategies:
       df['ADX'] = ta.trend.ADXIndicator(df['High'], df['Low'], df['Close']).adx()
       if df.iloc[-2]['ADX'] > 25:
           buy_votes.append("Strong ADX Trend")
   ```

2. **Register the Strategy Default state** in `worker/main.py` and `frontend/src/App.jsx` toggle forms to make it administrative-controllable from the dashboard panel.

---

## Cloud Deployment (Render Blueprint 24/7 Hosting)

To deploy this application to run 24/7 on the cloud:

1. **Commit and Push** your `market-signal-bot` code to a repository on **GitHub** or **GitLab**.
2. Log in to **[Render.com](https://render.com/)**.
3. Go to the dashboard, click **New** (top right) -> **Blueprint**.
4. Connect your GitHub repository containing the bot project.
5. Render will detect `render.yaml` and show the blueprint configuration setup.
6. Enter your **`TELEGRAM_BOT_TOKEN`** in the prompt (under worker and bot secrets configuration inputs).
7. Click **Apply**. Render will automatically provision:
   * A PostgreSQL database.
   * FastAPI api web service.
   * Background scanner worker.
   * Telegram Bot command listener.
   * Static React Frontend Dashboard (connected dynamically to the FastAPI URL).

