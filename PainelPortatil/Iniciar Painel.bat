@echo off
cd /d "%~dp0"
start "" /wait "%~dp0Painel.exe"
if errorlevel 1 (
  echo.
  echo O painel nao iniciou. Veja o erro abaixo e envie uma foto.
  if exist "logs\painel.log" powershell -NoProfile -Command "Get-Content -LiteralPath 'logs\painel.log' -Tail 25"
  pause
)
