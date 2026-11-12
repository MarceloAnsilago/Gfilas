import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app, db
from app.auth import accounts
from werkzeug.security import generate_password_hash


class MultiUnidadeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {"THERMAL_PRINTER_MODE": "queue", "PRINT_AGENT_TOKEN": "legacy-agent-token"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "DB_PATH": str(Path(self.directory.name) / "original.db")})
        with self.app.app_context(), accounts() as conn:
            conn.execute("INSERT INTO unidade_login (nome, login, senha_hash, legacy, print_token, is_admin) VALUES (?, ?, ?, 0, ?, 1)", ("Administrador", "admin", generate_password_hash("admin123"), "admin-token"))
        self.administrator = self.app.test_client()
        with self.administrator.session_transaction() as sess:
            sess["unidade_id"] = 1
        self.a = self.app.test_client()
        self.b = self.app.test_client()

    def token(self, client, route):
        html = client.get(route).get_data(as_text=True)
        return re.search(r'name="form_token" value="([^"]+)"', html).group(1)

    def register(self, client, name, login):
        result = self.administrator.post("/admin", data={"nome": name, "senha": "senha-teste", "form_token": self.token(self.administrator, "/admin")})
        if result.status_code == 302:
            client.post("/login", data={"login": name, "senha": "senha-teste", "form_token": self.token(client, "/login")})
        return result

    def test_unit_selector_lists_units_only_and_preserves_failed_selection(self):
        empty = self.a.get("/login").get_data(as_text=True)
        self.assertIn("Nenhuma unidade cadastrada", empty)
        self.register(self.a, "Unidade Norte", "norte")
        self.register(self.b, "Unidade Sul", "sul")
        client = self.app.test_client()
        page = client.get("/login").get_data(as_text=True)
        self.assertIn('<select id="login" name="login" required', page)
        self.assertIn('value="unidade norte"', page)
        self.assertIn('value="unidade sul"', page)
        self.assertNotIn('value="admin"', page)
        self.assertNotIn('type="password" required minlength', page)
        failed = client.post("/login", data={"login": "unidade norte", "senha": "errada", "form_token": self.token(client, "/login")}).get_data(as_text=True)
        self.assertIn('value="unidade norte" selected', failed)
        admin_page = client.get("/admin/login").get_data(as_text=True)
        self.assertNotIn('<select', admin_page)
        self.assertIn('<input id="login"', admin_page)

    def test_unit_password_accepts_one_character_and_has_no_length_rule(self):
        for index, password in enumerate(("1", "x" * 250)):
            name = f"Unidade {index}"
            response = self.administrator.post("/admin", data={"nome": name, "senha": password, "form_token": self.token(self.administrator, "/admin")})
            self.assertEqual(response.status_code, 302)
            client = self.app.test_client()
            response = client.post("/login", data={"login": name, "senha": password, "form_token": self.token(client, "/login")})
            self.assertEqual(response.location, "/chamar")

    def test_admin_credentials_are_exclusive_to_admin_login(self):
        self.assertEqual(self.a.get("/admin").location, "/admin/login")
        token = self.token(self.a, "/login")
        response = self.a.post("/login", data={"login": "admin", "senha": "admin123", "form_token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.a.get("/chamar").status_code, 302)
        token = self.token(self.a, "/admin/login")
        response = self.a.post("/admin/login", data={"login": "admin", "senha": "admin123", "form_token": token})
        self.assertEqual(response.location, "/admin")
        self.assertEqual(self.a.get("/chamar").location, "/login?next=/chamar")
        self.assertEqual(self.a.get("/painel").location, "/login?next=/painel")
        page = self.a.get("/chamar", follow_redirects=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn('name="login" required', page.get_data(as_text=True))

    def test_admin_owns_registration_and_stays_logged_in(self):
        self.assertEqual(self.a.get("/cadastro").status_code, 404)
        self.assertEqual(self.a.post("/cadastro").status_code, 404)
        self.assertNotIn("Cadastrar minha unidade", self.a.get("/login").get_data(as_text=True))
        self.assertEqual(self.administrator.post("/admin", data={"nome": "Test", "login": "test", "senha": "123456"}).status_code, 200)
        self.register(self.a, "Unidade real", "unidade")
        self.assertEqual(self.a.get("/admin").status_code, 302)
        self.assertEqual(self.a.post("/admin", data={}).status_code, 302)
        with self.administrator.session_transaction() as sess:
            self.assertEqual(sess["unidade_id"], 1)
        page = self.administrator.get("/admin").get_data(as_text=True)
        self.assertIn("Unidade real", page)
        self.assertNotIn('href="/admin"', self.a.get("/chamar").get_data(as_text=True))

    def test_routes_require_login_and_credentials_are_hashed(self):
        for route in ("/", "/admin", "/chamar", "/painel", "/senhas", "/gerar", "/historico"):
            self.assertEqual(self.a.get(route).status_code, 302)
        self.assertEqual(self.a.get("/painel/status").status_code, 401)
        self.assertEqual(self.a.post("/gerar").status_code, 401)
        self.assertEqual(self.register(self.a, "São Miguel", "saomiguel").status_code, 302)
        with self.app.app_context(), accounts() as conn:
            row = conn.execute("SELECT * FROM unidade_login WHERE is_admin = 0").fetchone()
            self.assertNotEqual(row["senha_hash"], "senha-teste")
        token = self.token(self.a, "/chamar")
        self.assertEqual(self.a.post("/logout", data={"form_token": token}).status_code, 302)
        self.assertEqual(self.a.get("/chamar").status_code, 302)
        token = self.token(self.a, "/login")
        self.assertIn("incorretos", self.a.post("/login", data={"login": "São Miguel", "senha": "errada", "form_token": token}).get_data(as_text=True))
        self.assertEqual(self.a.post("/login?next=//example.com", data={"login": "São Miguel", "senha": "senha-teste", "form_token": token}).location, "/chamar")
        self.assertEqual(self.a.get("/painel").status_code, 200)

    def test_two_units_isolate_numbers_calls_events_and_print_jobs(self):
        self.register(self.a, "São Miguel", "saomiguel")
        self.register(self.b, "Santana", "santana")
        stream_a = self.a.get("/painel/events", buffered=False)
        stream_b = self.b.get("/painel/events", buffered=False)
        self.addCleanup(stream_a.close)
        self.addCleanup(stream_b.close)
        initial_b = next(iter(stream_b.response)).decode()
        self.assertIn('"senha_atual": null', initial_b)
        emitted_a = self.a.post("/senhas/imprimir/normal").get_json()
        emitted_b = self.b.post("/senhas/imprimir/normal").get_json()
        self.assertTrue(emitted_a["ok"])
        self.assertEqual(emitted_a["senha"], emitted_b["senha"])
        self.a.post("/chamar", data={"acao": "chamar", "terminal": "1", "usuario": "Operador A"})
        status_a = self.a.get("/painel/status").get_json()
        status_b = self.b.get("/painel/status").get_json()
        self.assertEqual(status_a["senha_atual"]["unidade"], "São Miguel")
        self.assertIsNone(status_b["senha_atual"])
        self.assertEqual(status_b["proximas_senhas"][0]["unidade"], "Santana")
        events = self.app.extensions["unidades_events"]
        self.assertEqual(events[2].revision, 2)
        self.assertEqual(events[3].revision, 1)
        # Mesmo com IDs iguais nos bancos, uma tentativa de encerrar nao afeta a outra unidade.
        self.b.post("/historico", data={"encerrar_id": emitted_a["id"], "acao": "compareceu"})
        self.assertEqual(self.a.get("/painel/status").get_json()["senha_atual"]["status"], "aberto")
        with self.app.app_context(), accounts() as conn:
            units = conn.execute("SELECT * FROM unidade_login WHERE is_admin = 0 ORDER BY id").fetchall()
        for unit in units:
            agent = self.app.test_client()
            result = agent.post("/print-agent/jobs/claim", headers={"X-Print-Agent-Token": unit["print_token"]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.get_json()["job"]["unidade"], unit["nome"])
        self.assertEqual(self.app.test_client().post("/print-agent/jobs/claim", headers={"X-Print-Agent-Token": "invalid"}).status_code, 401)

    def test_first_unit_keeps_existing_data_and_duplicate_registration_preserves_it(self):
        with self.app.app_context():
            db.inserir_senha(45, "Unidade antiga")
        self.register(self.a, "São Miguel", "saomiguel")
        self.assertEqual(self.a.get("/painel/status").get_json()["proximas_senhas"][0]["senha"], 45)
        self.register(self.b, "Santana", "santana")
        self.assertEqual(self.b.get("/painel/status").get_json()["proximas_senhas"], [])
        anonymous = self.app.test_client()
        self.assertIn("ja esta em uso", self.register(anonymous, "SÃO MIGUEL", "saomiguel").get_data(as_text=True))
        with self.app.app_context(), accounts() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM unidade_login").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
