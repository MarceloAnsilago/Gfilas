from flask import Flask
try:
    from flask_bootstrap import Bootstrap
except Exception:  # Tolerate absence/incompatibility in production
    Bootstrap = None
from dotenv import load_dotenv
from pathlib import Path
from . import db

def create_app():
    # carrega o .env da RAIZ do projeto (…/SenhasFlask/.env)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    app = Flask(__name__)
    app.config.from_object("config.Config")

    if Bootstrap is not None:
        try:
            Bootstrap(app)
        except Exception:
            pass

    with app.app_context():
        db.init_db()
        from .routes import bp
        app.register_blueprint(bp)  # sem prefixo, rotas já ficam em /, /gerar, /imprimir, etc.
        return app
