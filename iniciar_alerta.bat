@echo off
rem Liga o vigia de drops COM janela (pra ver os logs). Ctrl+C ou fechar a janela para parar.
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe
if not exist "%PY%" set PY=python
"%PY%" alerta_drops.py
pause
