@echo off
setlocal

set "STARTUP_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Painel Senhas Fly.vbs"

if exist "%STARTUP_FILE%" (
  del /F /Q "%STARTUP_FILE%"
  echo Inicializacao automatica removida.
) else (
  echo Nenhum atalho automatico encontrado.
)

pause
endlocal
