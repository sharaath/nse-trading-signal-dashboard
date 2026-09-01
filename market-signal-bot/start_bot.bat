@echo off
title MarketSignalBot Scanner ^& Fast Scalper
cd /d "C:\Users\varun\OneDrive\Desktop\Trading analysis\market-signal-bot"
echo ===================================================
echo Refreshing Angel One SmartAPI Session (TOTP)
echo ===================================================
python scripts/angel_auto_login.py
echo ===================================================
echo Starting Telegram Command Listener
echo ===================================================
start "MarketSignalBot Telegram Listener" /min python -m bot.main
echo ===================================================
echo Starting MarketSignalBot Scanner (CRT + PO3 Engine)
echo Time: %date% %time%
echo ===================================================
python -m worker.main
pause
