import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from app import db
from app.painel_events import PainelEvents
from app.routes import bp


def payload(chunk):
    if isinstance(chunk, bytes):
        chunk = chunk.decode()
    return json.loads(next(line[6:] for line in chunk.splitlines() if line.startswith("data: ")))


class PainelEventsTests(unittest.TestCase):
    def test_queue_fragment_tracks_totem_emissions_and_calls(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"THERMAL_PRINTER_MODE": "queue"}):
            templates = Path(__file__).resolve().parents[1] / "app" / "templates"
            app = Flask(__name__, template_folder=str(templates))
            app.config.update(TESTING=True, SECRET_KEY="test", DB_PATH=str(Path(directory) / "test.db"))
            app.extensions["painel_events"] = PainelEvents()
            app.register_blueprint(bp)
            with app.app_context():
                db.init_db()
            client = app.test_client()
            page = client.get("/chamar?usuario=Operador&terminal=3").get_data(as_text=True)
            self.assertIn('id="fila-live"', page)
            self.assertIn('value="Operador"', page)
            self.assertIn('chamar-live.js', page)
            response = client.get("/painel/events", buffered=False)
            stream = iter(response.response)
            next(stream)
            try:
                for priority in ("normal", "preferencial"):
                    emitted = client.post(f"/senhas/imprimir/{priority}")
                    self.assertEqual(emitted.status_code, 200)
                    snapshot = payload(next(stream))
                    self.assertTrue(snapshot["proximas_senhas"])
                    self.assertEqual(snapshot["proximas_senhas"][0]["prioridade"],
                                     "normal" if priority == "normal" else "preferencial")
                fragment = client.get("/chamar?fragment=fila").get_data(as_text=True)
                self.assertIn("2 aguardando", fragment)
                self.assertIn('fila-totem-card normal', fragment)
                self.assertIn('fila-totem-card preferencial', fragment)
                self.assertNotIn('<html', fragment)
                self.assertNotIn('name="usuario"', fragment)
                self.assertNotIn('window.location.reload()', fragment)
                client.post("/chamar", data={"acao": "chamar", "usuario": "Operador", "terminal": "3"})
                after_call = payload(next(stream))
                self.assertEqual(len(after_call["proximas_senhas"]), 1)
                self.assertNotEqual(after_call["proximas_senhas"][0]["senha"],
                                    after_call["senha_atual"]["senha"])
                fragment = client.get("/chamar?fragment=fila").get_data(as_text=True)
                self.assertIn("1 aguardando", fragment)
            finally:
                response.close()

    def test_idle_heartbeat_does_not_read_database(self):
        events = PainelEvents()
        load = Mock(return_value={"senha_atual": None})
        stream = events.stream(load, heartbeat=0.01)
        next(stream)
        self.assertEqual(next(stream), ": keepalive\n\n")
        self.assertEqual(next(stream), ": keepalive\n\n")
        load.assert_called_once()
        stream.close()

    def test_publish_wakes_all_panels_and_preserves_rapid_updates(self):
        events = PainelEvents()
        streams = [events.stream(lambda: {"senha": 0}) for _ in range(2)]
        for stream in streams:
            next(stream)
        received = []
        threads = [Thread(target=lambda s=s: received.append(payload(next(s)))) for s in streams]
        for thread in threads:
            thread.start()
        events.publish(lambda: {"senha": 1})
        events.publish(lambda: {"senha": 2})
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(received, [{"senha": 1}, {"senha": 1}])
        for stream in streams:
            self.assertEqual(payload(next(stream)), {"senha": 2})
            stream.close()

    def test_routes_call_recall_complete_and_reconnect(self):
        with TemporaryDirectory() as directory:
            app = Flask(__name__)
            app.config.update(TESTING=True, SECRET_KEY="test", DB_PATH=str(Path(directory) / "test.db"))
            app.extensions["painel_events"] = PainelEvents()
            app.register_blueprint(bp)
            with app.app_context():
                db.init_db()
            client = app.test_client()
            response = client.get("/painel/events", buffered=False)
            stream = iter(response.response)
            self.assertEqual(response.mimetype, "text/event-stream")
            self.assertEqual(response.headers["X-Accel-Buffering"], "no")
            self.assertIsNone(payload(next(stream))["senha_atual"])
            client.post("/gerar", data={"senha_inicial": 1, "senha_final": 2})
            next(stream)
            client.post("/chamar", data={"acao": "chamar", "usuario": "Teste", "terminal": "1"})
            called = payload(next(stream))["senha_atual"]
            self.assertEqual(called["senha"], 1)
            self.assertEqual(called["resposta"], "chamando 1")
            client.post("/chamar", data={"acao": "chamar_novamente"})
            self.assertEqual(payload(next(stream))["senha_atual"]["resposta"], "chamando 2")
            response.close()
            reconnected = client.get("/painel/events", headers={"Last-Event-ID": "0"}, buffered=False)
            self.assertEqual(payload(next(iter(reconnected.response)))["senha_atual"]["resposta"], "chamando 2")
            client.post("/chamar", data={"acao": "compareceu"})
            final = payload(next(iter(reconnected.response)))
            self.assertEqual(final["ultimas_senhas"][0]["status"], "encerrado")
            self.assertEqual(client.get("/painel/status").get_json(), final)
            reconnected.close()


if __name__ == "__main__":
    unittest.main()
