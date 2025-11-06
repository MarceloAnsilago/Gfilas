from flask import Flask
from flask_bootstrap import Bootstrap
from dotenv import load_dotenv
import os
from . import db

def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config.from_object("config.Config")

    Bootstrap(app)

    with app.app_context():
        db.init_db()

        # Importa e registra as rotas
        from .routes import bp
        app.register_blueprint(bp)

        return app
