import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib import error, request

from dotenv import load_dotenv

from app import printer

logger = logging.getLogger(__name__)


class PrintAgentConfigError(RuntimeError):
    """Erro de configuracao do agente local."""


class PrintAgentRequestError(RuntimeError):
    """Erro ao comunicar com o servidor de impressao."""


@dataclass(slots=True)
class PrintAgentConfig:
    base_url: str
    token: str
    poll_interval: float = 1.0

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "PrintAgentConfig":
        if env_path is not None:
            load_dotenv(env_path)

        base_url = (
            os.getenv("PRINT_AGENT_BASE_URL")
            or os.getenv("BASE_URL")
            or ""
        ).strip().rstrip("/")
        token = (os.getenv("PRINT_AGENT_TOKEN") or "").strip()
        poll_interval_raw = (
            os.getenv("PRINT_AGENT_POLL_INTERVAL")
            or os.getenv("POLL_INTERVAL")
            or "1.0"
        ).strip()

        try:
            poll_interval = max(float(poll_interval_raw), 0.2)
        except ValueError as exc:
            raise PrintAgentConfigError("POLL_INTERVAL/PRINT_AGENT_POLL_INTERVAL invalido.") from exc

        if not base_url:
            raise PrintAgentConfigError("BASE_URL/PRINT_AGENT_BASE_URL nao configurado.")
        if not token:
            raise PrintAgentConfigError("PRINT_AGENT_TOKEN nao configurado.")

        return cls(base_url=base_url, token=token, poll_interval=poll_interval)


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


def run_agent_loop(
    config: PrintAgentConfig,
    stop_event=None,
    on_idle=None,
    on_job=None,
) -> int:
    pronto, motivo = printer.printer_ready()
    if not pronto:
        raise PrintAgentConfigError(f"Impressora local indisponivel: {motivo}")

    logger.info("Agente de impressao conectado em %s", config.base_url)
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Agente de impressao interrompido.")
            return 0

        job_id = None
        try:
            job = claim_job(config.base_url, config.token)
            if not job:
                if on_idle is not None:
                    on_idle()
                _sleep_interruptible(config.poll_interval, stop_event)
                continue

            if on_job is not None:
                on_job(job)

            job_id = int(job["id"])
            data_hora = _parse_datetime(job.get("data_hora"))
            metadata = printer.imprimir_senha(
                numero=str(job.get("numero") or "000"),
                tipo=str(job.get("tipo") or "Senha normal"),
                unidade=str(job.get("unidade") or "UNIDADE"),
                data_hora=data_hora,
                teste=bool(job.get("teste")),
            )
            complete_job(config.base_url, config.token, job_id, metadata)
            logger.info("Job %s impresso com sucesso.", job_id)
        except KeyboardInterrupt:
            logger.info("Agente interrompido pelo teclado.")
            return 0
        except Exception as exc:
            logger.exception("Falha no agente de impressao: %s", exc)
            if job_id is not None:
                try:
                    error_job(config.base_url, config.token, job_id, str(exc))
                except Exception:
                    logger.exception("Falha ao marcar job %s como erro.", job_id)
            _sleep_interruptible(max(config.poll_interval, 1.0), stop_event)


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
        raise PrintAgentRequestError(f"HTTP {exc.code} em {url}: {body}") from exc
    except error.URLError as exc:
        raise PrintAgentRequestError(f"Falha de rede ao acessar {url}: {exc.reason}") from exc


def _parse_datetime(valor: str | None):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def _sleep_interruptible(seconds: float, stop_event) -> None:
    if stop_event is None:
        time.sleep(seconds)
        return
    stop_event.wait(seconds)
