import json
import os
import sys
import time
import traceback
from pathlib import Path
from urllib import error, request

from dotenv import load_dotenv

from app import printer


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env")

    base_url = (os.getenv("PRINT_AGENT_BASE_URL") or "").strip().rstrip("/")
    token = (os.getenv("PRINT_AGENT_TOKEN") or "").strip()
    poll_interval = float((os.getenv("PRINT_AGENT_POLL_INTERVAL") or "1.0").strip())

    if not base_url:
        print("PRINT_AGENT_BASE_URL nao configurado.")
        return 1
    if not token:
        print("PRINT_AGENT_TOKEN nao configurado.")
        return 1

    pronto, motivo = printer.printer_ready()
    if not pronto:
        print(f"Impressora local indisponivel: {motivo}")
        return 1

    print(f"Agente de impressao conectado em {base_url}")
    while True:
        try:
            job = claim_job(base_url, token)
            if not job:
                time.sleep(poll_interval)
                continue

            job_id = int(job["id"])
            data_hora = _parse_datetime(job.get("data_hora"))
            metadata = printer.imprimir_senha(
                numero=str(job.get("numero") or "000"),
                tipo=str(job.get("tipo") or "Senha normal"),
                unidade=str(job.get("unidade") or "UNIDADE"),
                data_hora=data_hora,
                teste=bool(job.get("teste")),
            )
            complete_job(base_url, token, job_id, metadata)
            print(f"Job {job_id} impresso com sucesso.")
        except KeyboardInterrupt:
            print("Agente interrompido.")
            return 0
        except Exception as exc:
            print(f"Falha no agente: {exc}")
            traceback.print_exc()
            if "job_id" in locals():
                try:
                    error_job(base_url, token, job_id, str(exc))
                except Exception:
                    traceback.print_exc()
            time.sleep(max(poll_interval, 1.0))


def claim_job(base_url: str, token: str):
    response = _request_json(
        f"{base_url}/print-agent/jobs/claim",
        token,
        method="POST",
    )
    if response is None:
        return None
    return response.get("job")


def complete_job(base_url: str, token: str, job_id: int, metadata: dict):
    _request_json(
        f"{base_url}/print-agent/jobs/{job_id}/complete",
        token,
        method="POST",
        payload={"printer_info": metadata},
    )


def error_job(base_url: str, token: str, job_id: int, message: str):
    _request_json(
        f"{base_url}/print-agent/jobs/{job_id}/error",
        token,
        method="POST",
        payload={"message": message},
    )


def _request_json(url: str, token: str, method: str = "GET", payload: dict | None = None):
    headers = {
        "Accept": "application/json",
        "X-Print-Agent-Token": token,
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code == 204:
            return None
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} em {url}: {body}") from exc


def _parse_datetime(valor: str | None):
    if not valor:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(valor)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
