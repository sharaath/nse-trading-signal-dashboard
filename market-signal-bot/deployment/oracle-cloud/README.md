# Oracle Cloud Always Free Deployment Guide

This guide details the step-by-step procedure to deploy the MarketSignalBot on the **Oracle Cloud Always Free Tier** to run the 1-minute scanner, real-time Fyers data connection, and Telegram notifications 24/7.

---

## ⚠️ Oracle Cloud Cost Protection Rules

Oracle Cloud Always Free VMs are highly reliable, but enabling certain paid addons or resizing resources can generate unexpected charges. To ensure a **COMPLETELY FREE** operation:
* **VM Shape**: Select **Always Free Eligible** shapes only.
  * Use the **Ampere (ARM) A1 Compute** (4 OCPUs, 24 GB RAM) or **AMD VM.Standard.E2.1.Micro** (1 OCPU, 1 GB RAM).
  * We recommend creating **1 instance of Ampere A1** with **2 OCPUs and 8-12 GB of RAM**, which is fully Always Free eligible.
* **Boot Volume**: The default Always Free boot volume limit is **200 GB** total across all VMs. Do not allocate more than 100 GB for this VM.
* **DO NOT ENABLE**:
  * Paid databases (OCI Autonomous Database limits are free up to 2 instances; do not create other DB shapes).
  * Paid load balancers (only the default 10 Mbps load balancer is free).
  * Paid object storage (free up to 10 GB).
  * Public IP addresses beyond the 1 reserved ephemeral public IP included in the Always Free compute instance.

---

## Deployment Steps (Beginner Friendly)

### Step 1: Create Oracle Cloud Free Tier Account
Go to [oracle.com/cloud/free/](https://www.oracle.com/cloud/free/) and register for a free account. A valid credit/debit card is required for verification, but no charges will be made.

### Step 2: Create Always Free Ubuntu VM
1. Log in to the Oracle Cloud Console.
2. Go to **Compute** -> **Instances** -> **Create Instance**.
3. **Placement**: Keep default (ad-1).
4. **Image and Shape**:
   * Click **Edit**.
   * **Image**: Click **Change Image**, select **Canonical Ubuntu** (version 22.04 LTS recommended).
   * **Shape**: Click **Change Shape**, select **Ampere (ARM)** and select **Always Free Eligible VM.Standard.A1.Flex** (Set OCPUs = 2, Memory = 8 GB).
5. **Networking**: Ensure "Assign a public IPv4 address" is checked.
6. **Add SSH Keys**:
   * Click **Save Private Key** to download the private key (`ssh-key-*.key`).
7. **Create**: Click **Create** at the bottom.

### Step 3: Configure Ingress Rules (Ports)
Before connecting, open API/Frontend ports in the Oracle virtual network:
1. Under **Instance Details**, click on the **Virtual Cloud Network** link.
2. Click on **Security Lists** -> **Default Security List for...**
3. Click **Add Ingress Rules**:
   * **Source CIDR**: `0.0.0.0/0`
   * **IP Protocol**: `TCP`
   * **Destination Port Range**: `8000` (FastAPI REST API)
   * Click **Add Ingress Rules**.
4. Click **Add Ingress Rules** again:
   * **Source CIDR**: `0.0.0.0/0`
   * **IP Protocol**: `TCP`
   * **Destination Port Range**: `5173` (React Frontend Dashboard)
   * Click **Add Ingress Rules**.

### Step 4: Connect to the VM
Open a terminal on your laptop (or PowerShell on Windows) and run:
```bash
chmod 400 /path/to/ssh-key-*.key
ssh -i /path/to/ssh-key-*.key ubuntu@<YOUR_VM_PUBLIC_IP>
```

### Step 5: Upload/Clone the Project
Clone the repository directly inside the VM home directory:
```bash
git clone <your_github_repo_url> ~/market-signal-bot
cd ~/market-signal-bot/market-signal-bot/deployment/oracle-cloud
```

### Step 6: Install Docker & Configure Firewall
Execute the automated system setup script. This script will install Docker, Docker Compose, configure the local Ubuntu iptables firewall (critical for OCI Ubuntu VM network access), and copy the `.env` template:
```bash
chmod +x setup.sh
./setup.sh
```
**Important**: After the script finishes, **log out** of the SSH session (`exit`) and **log back in** to refresh group permissions.

### Step 7: Configure Environment Variables (.env)
Edit the environment variables file using nano:
```bash
nano ~/market-signal-bot/market-signal-bot/.env
```
Fill in the credentials carefully:
```env
SYSTEM_MODE=PAPER
REAL_ORDERS_ENABLED=false
MARKET_DATA_PROVIDER=angelone
FORCE_SCAN=true

# Angel One SmartAPI Credentials
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_CODE=your_client_code
ANGEL_PIN=your_pin
ANGEL_TOTP_KEY=your_totp_secret_key

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```
Press `Ctrl+O` and `Enter` to save, then `Ctrl+X` to exit.

### Step 8: Start the Services
Run the update script to build images and boot all Docker containers in background mode:
```bash
chmod +x update.sh
./update.sh
```

### Step 9: Verify Health & Testing
* **Check live container statuses & API diagnostics**:
  ```bash
  chmod +x health_check.sh
  ./health_check.sh
  ```
* **Verify Fyers Connection**: Check worker logs for WebSocket ticks and data parsing:
  ```bash
  docker compose logs -f worker
  ```
* **Verify Telegram Notifications**: Send the command `/test_alert` to your bot via Telegram chat. Your mobile app should receive the complete set of 10 sample alerts verifying transmission from the cloud VM.
* **Turn OFF Laptop**: Shut down your laptop completely. Wait for 5-15 minutes, and verify that Telegram notifications continue to arrive on your mobile phone.

---

## 6. Verification Reference Commands

| Telemetry / Target | Command | Expected Output |
| :--- | :--- | :--- |
| **Container Status** | `docker compose ps` | Status `Up` (HEALTHY) for all services. |
| **Worker Logs** | `docker compose logs --tail=50 worker` | Logs detailing spot scans, indicator results, and score confluences. |
| **Health endpoint** | `curl -s http://localhost:8000/health` | JSON status mapping database, connection, and modes. |
| **Paper Mode Enforced** | `docker compose exec api env \| grep SYSTEM_MODE` | `SYSTEM_MODE=PAPER` |
| **Real Orders Disabled** | `docker compose exec api env \| grep REAL_ORDERS` | `REAL_ORDERS_ENABLED=false` |
| **Safety Gate Exit Verify** | `docker compose run --rm -e REAL_ORDERS_ENABLED=true api` | Exit code 1 with `"CRITICAL SAFETY BLOCK: Real orders are enabled..."` |
| **Scanner Frequency** | `docker compose logs worker \| grep "Executing market scan"` | Execution lines spaced exactly 1 minute apart. |
| **Container Recovery** | `sudo reboot` (after reboot verify `docker ps`) | All containers running automatically on system boot. |
