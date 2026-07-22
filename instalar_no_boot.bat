@echo off
rem Faz o vigia ligar sozinho quando o Windows inicia (cria um .bat na pasta Inicializar).
set ALVO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\drops_alerta.bat
(
echo @echo off
echo cd /d "%~dp0"
echo set PYW=%%LOCALAPPDATA%%\Programs\Python\Python314\pythonw.exe
echo if not exist "%%PYW%%" set PYW=pythonw
echo start "" "%%PYW%%" drops_tray.py
) > "%ALVO%"
echo Pronto: o vigia liga junto com o Windows.
echo Pra desfazer, rode desinstalar_do_boot.bat
pause
