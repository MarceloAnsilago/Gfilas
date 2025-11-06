@echo off
setlocal enabledelayedexpansion
REM === Vai para a pasta do script ===
cd /d %~dp0

REM === Detecta Python ===
where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERRO] Python não encontrado no PATH.
  echo Instale Python 3.9+ e marque "Add to PATH".
  pause
  exit /b 1
)

REM === Cria venv se não existir ===
if not exist venv (
  echo [INFO] Criando ambiente virtual...
  python -m venv venv
  if %errorlevel% neq 0 (
    echo [ERRO] Falha ao criar venv.
    pause
    exit /b 1
  )
)

REM === Atualiza pip e instala dependencias ===
echo [INFO] Instalando dependencias...
venv\Scripts\python.exe -m pip install --upgrade pip
if exist requirements.txt (
  venv\Scripts\python.exe -m pip install -r requirements.txt
) else (
  echo [AVISO] requirements.txt nao encontrado. Instalando pacotes padrao...
  venv\Scripts\python.exe -m pip install flask flask-bootstrap python-dotenv waitress pandas matplotlib pytz
)

REM === Cria .env se nao existir ===
if not exist ".env" (
  echo [INFO] Criando .env padrao...
  copy /y .env.example .env >nul 2>&1
  if not exist ".env" (
    echo SECRET_KEY=troque-esta-chave> .env
    echo PAINEL_DB_PATH=%cd%\ultima_senha.db>> .env
    echo PAINEL_UNIDADE_PADRAO=UNIDADE>> .env
    echo PAINEL_USUARIO_PADRAO=admin>> .env
  )
)

echo [OK] Ambiente pronto.
endlocal
exit /b 0
