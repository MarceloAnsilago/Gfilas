@echo off
setlocal
cd /d %~dp0

call bootstrap_venv.bat
if %errorlevel% neq 0 exit /b 1

echo [INFO] Iniciando servidor em 0.0.0.0:5000 ...
if exist venv\Scripts\waitress-serve.exe (
  venv\Scripts\waitress-serve.exe --listen=0.0.0.0:5000 run:app
) else (
  echo [AVISO] waitress nao encontrado no ambiente virtual. Usando servidor Flask embutido.
  venv\Scripts\python.exe run.py
)
endlocal
