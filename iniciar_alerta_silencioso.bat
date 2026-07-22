@echo off
rem Liga o Drops Radar (bandeja) invisivel, igual ao boot.
cd /d "%~dp0"
set PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe
if not exist "%PYW%" set PYW=pythonw
start "" "%PYW%" drops_tray.py
echo Drops Radar ligado (olha a setinha perto do relogio).
