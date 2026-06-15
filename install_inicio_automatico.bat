@echo off
setlocal
cd /d "%~dp0"

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_VBS=%~dp0start_fly_painel_e_agente.vbs"
set "SHORTCUT_NAME=Painel Senhas Fly.vbs"

if not exist "%TARGET_VBS%" (
  echo Arquivo nao encontrado: %TARGET_VBS%
  pause
  exit /b 1
)

copy /Y "%TARGET_VBS%" "%STARTUP_DIR%\%SHORTCUT_NAME%" >nul
if errorlevel 1 (
  echo Falha ao copiar para a pasta de Inicializacao.
  pause
  exit /b 1
)

echo Inicializacao automatica configurada com sucesso.
echo Arquivo instalado em:
echo %STARTUP_DIR%\%SHORTCUT_NAME%
pause
endlocal
