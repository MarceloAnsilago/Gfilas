import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega o .env da raiz
load_dotenv()

# Pasta base do projeto
BASE_DIR = Path(__file__).resolve().parent

class Config:
    # Chave secreta do Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")

    # Caminho do banco — relativo ou absoluto
    ENV_DB = os.getenv("PAINEL_DB_PATH", "ultima_senha.db")
    if os.path.isabs(ENV_DB):
        DB_PATH = ENV_DB
    else:
        DB_PATH = str((BASE_DIR / ENV_DB).resolve())

    # Configurações opcionais / defaults
    DEFAULT_UNIDADE = os.getenv("PAINEL_UNIDADE_PADRAO", "UNIDADE")
    DEFAULT_USUARIO = os.getenv("PAINEL_USUARIO_PADRAO", "admin")

    # Fuso horário padrão
    TIMEZONE = os.getenv("PAINEL_FUSO_HORARIO", "Etc/GMT+3")
