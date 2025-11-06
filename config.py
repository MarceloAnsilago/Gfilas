import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
    DB_PATH = os.getenv("PAINEL_DB_PATH", os.path.join(os.getcwd(), "ultima_senha.db"))
