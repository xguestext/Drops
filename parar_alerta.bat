@echo off
rem Desliga o Drops Radar (bandeja, vigia antigo e janela do site).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'drops_tray.py|alerta_drops.py|viewer_site.py' -and $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Drops Radar parado (se estava rodando).
pause
