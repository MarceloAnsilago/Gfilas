import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import Mock

from flask import Flask

from app import db
from app.painel_events import PainelEvents
from app.routes import bp


def payload(chunk):
    if isinstance(chunk, bytes):
        chunk = chunk.decode()
    return json.loads(next(line[6:] for line in chunk.splitlines() if line.startswith("data: ")))


class PainelEventsTests(unittest.TestCase):
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
