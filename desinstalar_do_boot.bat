@echo off
rem Tira o vigia da inicializacao do Windows.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\drops_alerta.bat" 2>nul
echo Removido da inicializacao.
pause
