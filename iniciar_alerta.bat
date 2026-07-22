@echo off
rem Liga o Drops Radar (bandeja) COM janela de log, pra depurar.
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe
if not exist "%PY%" set PY=python
"%PY%" drops_tray.py
pause
