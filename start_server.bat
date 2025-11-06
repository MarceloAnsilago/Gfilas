@echo off
setlocal
cd /d %~dp0

call bootstrap_venv.bat
if %errorlevel% neq 0 exit /b 1

echo [INFO] Iniciando servidor em 0.0.0.0:5000 ...
venv\Scripts\waitress-serve.exe --listen=0.0.0.0:5000 run:app
endlocal
