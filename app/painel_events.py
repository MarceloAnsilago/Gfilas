"""Notificacoes do painel para um servidor com um processo e varias threads."""

from collections import deque
import json
from threading import Condition


class PainelEvents:
    def __init__(self):
        self.condition = Condition()
        self.revision = 0
        self.events = deque(maxlen=128)

    def publish(self, load_snapshot):
        with self.condition:
            payload = load_snapshot()
            self.revision += 1
            self.events.append((self.revision, payload))
            self.condition.notify_all()

    @staticmethod
    def encode(revision, payload):
        return f"id: {revision}\nevent: status\ndata: {json.dumps(payload)}\n\n"

    def stream(self, load_snapshot, heartbeat=15):
        # Reabrir uma conexao sempre sincroniza o estado atual, sem repetir
        # anuncios antigos que aconteceram enquanto o painel estava offline.
        with self.condition:
            revision = self.revision
            initial = load_snapshot()
        yield "retry: 3000\n" + self.encode(revision, initial)
        while True:
            with self.condition:
                changed = self.condition.wait_for(
                    lambda: self.revision != revision, timeout=heartbeat
                )
                pending = [event for event in self.events if event[0] > revision] if changed else []
                if pending:
                    revision = pending[-1][0]
            if pending:
                for event in pending:
                    yield self.encode(*event)
            else:
                # Mantem a conexao aberta, sem consultar o SQLite.
                yield ": keepalive\n\n"
