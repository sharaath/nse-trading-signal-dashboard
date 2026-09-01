# MarketSignalBot

A dockerized full-stack trading analysis bot that polls live options and indices coordinates (Nifty 50, Bank Nifty, and SENSEX), computes technical + ICT/SMC structure shifts, executes consensus options analysis, and logs simulation parameters.

---

## ⚠️ Regulatory Compliance & Risk Disclaimer
> [!IMPORTANT]
> **SEBI Regulatory Compliance**: Under SEBI (Investment Advisers) Regulations, 2013, publishing or broadcasting index option tips, entry targets, or trading recommendations publicly requires SEBI registration. This project is configured in **Paper-Trading/Signal-Only Mode** by default and is meant for **personal research, simulated studies, and educational usage only**. Do not execute real-money trades automatically based on these signals.

---

## Architectural Data Quality Rules

1. **Explicit System Modes**:
   - `LIVE MODE`: Runs under authorized broker APIs. Signal execution occurs with live account parameters.
   - `PAPER MODE` (Default): Uses live market feeds, but does not place real orders (all ledger entries saved in `PaperTrade` logs).
   - `SIMULATION MODE`: Uses generated test or historical database mocks.
   
2. **No Web Scraping**: The project does not systematically scrape the NSE or BSE websites. It uses a modular abstract `MarketDataProvider` interface supporting licensed feed APIs.

3. **No SENSEX Simulations**: In LIVE and PAPER modes, BSE SENSEX options chain analysis must use a legitimate authorized BSE/broker provider. If unavailable, it does not fabricate premium prices or OI metrics, and outputs `DATA UNAVAILABLE`.

4. **Data Quality Checks**: Spot candles are inspected for missing indices, stale price feeds (frozen LTPs), and timestamp offsets before processing. Failed validations raise `DATA QUALITY FAILURE — NO SIGNAL`.

---

## Corrected Platform Flow Architecture

```text
       AUTHORIZED LIVE DATA FEED
                   ↓
         PRE-SCAN DATA VALIDATION
                   ↓
         MULTI-TIMEFRAME SCANNER
                   ↓
       SMC/ICT STRUCTURE ENGINE (Sweeps, MSS, FVG, OB)
                   ↓
       TECHNICAL ANALYSIS (VWAP, EMA alignment)
                   ↓
       OPTIONS ANALYTICS (PCR ratio, Premium momentum)
                   ↓
       ML PREDICTION PIPELINE (Target classification)
                   ↓
       STRATEGY SCORING CONVERGENCE
                   ↓
       RISK LIMITS & SESSION BOUNDARIES CHECK
                   ↓
       STRIKE SELECTION & STOP LOSS PROJECTION
                   ↓
       AUTOMATED PAPER POSITION TRACKING
                   ↓
       TELEGRAM DISPATCH + DASHBOARD LEDGER
```

---

## How to Install & Run

1. **Initialize Environments**:
   ```bash
   cp .env.example .env
   ```
   Fill in credentials for your active broker/licensed data feeds inside `.env`.

2. **Boot Platform Services**:
   ```bash
   docker-compose up --build
   ```
   - Frontend console: `http://localhost:5173`
   - REST API: `http://localhost:8000/docs`

3. **Tests Suite Verification**:
   To run pipeline logic validation checks:
   ```bash
   python -m pytest
   ```
