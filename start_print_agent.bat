@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo Ambiente virtual nao encontrado em venv\Scripts\python.exe
  exit /b 1
)

venv\Scripts\python.exe print_agent.py
