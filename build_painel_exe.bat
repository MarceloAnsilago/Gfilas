@echo off
setlocal

set ROOT_DIR=%~dp0
cd /d "%ROOT_DIR%"

if not exist "venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado em venv\Scripts\python.exe
    echo Crie o ambiente com: python -m venv venv
    exit /b 1
)

call "venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

python -m pip install --upgrade pip
if errorlevel 1 exit /b 1

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

pyinstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --name Painel ^
    --hidden-import win32print ^
    --collect-all dotenv ^
    desktop_panel.py

echo.
echo Build concluido: dist\Painel.exe
endlocal
