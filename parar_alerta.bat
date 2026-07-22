@echo off
rem Desliga o vigia de drops (mata qualquer python rodando o alerta_drops.py).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*alerta_drops.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Vigia parado (se estava rodando).
pause
