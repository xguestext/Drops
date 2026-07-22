@echo off
rem Liga o vigia de drops SEM janela (fica rodando invisivel). Use parar_alerta.bat pra desligar.
cd /d "%~dp0"
set PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe
if not exist "%PYW%" set PYW=pythonw
start "" "%PYW%" alerta_drops.py
echo Vigia ligado em segundo plano.
