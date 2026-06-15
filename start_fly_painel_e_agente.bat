@echo off
setlocal
cd /d "%~dp0"

set "PAINEL_URL=https://white-glade-1234.fly.dev/painel"

if not exist "venv\Scripts\python.exe" (
  echo Ambiente virtual nao encontrado em venv\Scripts\python.exe
  pause
  exit /b 1
)

tasklist /FI "IMAGENAME eq msedge.exe" | find /I "msedge.exe" >nul
set "EDGE_RUNNING=%errorlevel%"
tasklist /V /FI "IMAGENAME eq python.exe" | find /I "print_agent.py" >nul
set "AGENT_RUNNING=%errorlevel%"

if "%AGENT_RUNNING%"=="0" (
  echo [INFO] Agente ja esta em execucao.
) else (
echo [INFO] Iniciando agente de impressao...
start "Agente de Impressao" cmd /k "cd /d %~dp0 && venv\Scripts\python.exe print_agent.py"
)

timeout /t 2 /nobreak >nul

if "%EDGE_RUNNING%"=="0" (
  echo [INFO] Edge ja esta aberto. Abrindo painel em nova janela.
  start "" msedge "%PAINEL_URL%"
) else (
  echo [INFO] Abrindo painel em %PAINEL_URL%
  start "" msedge --kiosk "%PAINEL_URL%"
)

endlocal
