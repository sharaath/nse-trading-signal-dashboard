$startupFolder = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder "MarketSignalBot.lnk"
$targetPath = "C:\Users\varun\OneDrive\Desktop\Trading analysis\market-signal-bot\start_bot.bat"
$workDir = "C:\Users\varun\OneDrive\Desktop\Trading analysis\market-signal-bot"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)
$Shortcut.TargetPath = $targetPath
$Shortcut.WorkingDirectory = $workDir
$Shortcut.WindowStyle = 1
$Shortcut.Description = "MarketSignalBot Scanner Auto-Start"
$Shortcut.Save()

Write-Host "Successfully added MarketSignalBot to Windows Startup folder at: $shortcutPath"
