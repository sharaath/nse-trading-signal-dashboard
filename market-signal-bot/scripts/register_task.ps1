$batPath = "C:\Users\varun\OneDrive\Desktop\Trading analysis\market-signal-bot\start_bot.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:40AM
$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "TradingBot_AutoStart" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Successfully registered Windows Scheduled Task: TradingBot_AutoStart"
