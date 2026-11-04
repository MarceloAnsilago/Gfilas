import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask import Flask
from app import db
from app.painel_events import PainelEvents
from app.routes import bp


class UnidadeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        templates = Path(__file__).resolve().parents[1] / "app" / "templates"
        self.app = Flask(__name__, template_folder=str(templates))
        self.app.config.update(TESTING=True, SECRET_KEY="test",
                               DEFAULT_UNIDADE="UNIDADE",
                               DB_PATH=str(Path(self.directory.name) / "test.db"))
        self.app.extensions["painel_events"] = PainelEvents()
        self.app.register_blueprint(bp)
        with self.app.app_context():
            db.init_db()
        self.client = self.app.test_client()

    def test_default_and_saved_name_reach_print_queue(self):
        self.assertIn('value="ULSAV SMG"', self.client.get("/gerar").get_data(as_text=True))
        with patch.dict(os.environ, {"THERMAL_PRINTER_MODE": "queue"}):
            self.assertEqual(self.client.post("/senhas/imprimir/teste").status_code, 200)
            response = self.client.post("/gerar/salvar-unidade", data={"unidade": "  Nova Unidade  "})
            self.assertEqual(response.status_code, 302)
            # A different browser session reads the same persisted setting.
            self.assertIn('value="Nova Unidade"', self.app.test_client().get("/gerar").get_data(as_text=True))
            self.assertEqual(self.client.post("/senhas/imprimir/normal").status_code, 200)
            self.assertEqual(self.client.post("/senhas/imprimir/teste").status_code, 200)
        with self.app.app_context(), db.conectar() as conn:
            jobs = conn.execute("SELECT unidade FROM print_job ORDER BY id").fetchall()
            self.assertEqual([row["unidade"] for row in jobs], ["ULSAV SMG", "Nova Unidade", "Nova Unidade"])
            self.assertEqual(conn.execute("SELECT unidade FROM senha").fetchone()["unidade"], "Nova Unidade")

    def test_blank_save_keeps_name_and_batch_uses_saved_default(self):
        self.client.post("/gerar/salvar-unidade", data={"unidade": "Unidade Salva"})
        self.client.post("/gerar/salvar-unidade", data={"unidade": "   "})
        self.client.post("/gerar", data={"senha_inicial": "1", "senha_final": "1", "data_execucao": "2026-11-04"})
        with self.app.app_context(), db.conectar() as conn:
            self.assertEqual(db.obter_unidade_padrao(), "Unidade Salva")
            self.assertEqual(conn.execute("SELECT unidade FROM senha").fetchone()["unidade"], "Unidade Salva")
        page = self.client.get("/imprimir?data=2026-11-04").get_data(as_text=True)
        self.assertIn("Unidade Salva", page)

