import logging
import os
import re
import sys
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import win32print
except ImportError:  # pragma: no cover - depends on Windows runtime
    win32print = None


class PrinterError(RuntimeError):
    """Erro operacional ao enviar dados para a impressora."""


def printer_mode() -> str:
    """Define o modo de entrega da impressao: local ou queue."""
    raw = (os.getenv("THERMAL_PRINTER_MODE") or "").strip().lower()
    if raw in {"queue", "remote", "agent"}:
        return "queue"
    return "local"


def printer_config():
    """Retorna configuracao efetiva da impressora termica."""
    return {
        "enabled": os.getenv("THERMAL_PRINTER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
        "name": (os.getenv("THERMAL_PRINTER_NAME") or "POS58 DRIVER (TESTADO)").strip(),
        "encoding": (os.getenv("THERMAL_PRINTER_ENCODING") or "cp850").strip(),
        "mode": printer_mode(),
    }


def list_printer_names() -> list[str]:
    """Lista impressoras disponiveis para o processo atual."""
    if win32print is None or sys.platform != "win32":
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        return [item[2] for item in win32print.EnumPrinters(flags)]
    except Exception:  # pragma: no cover - Windows-specific
        logger.exception("Falha ao listar impressoras instaladas")
        return []


def printer_ready() -> tuple[bool, str | None]:
    """Valida se a impressora pode ser usada neste ambiente."""
    cfg = printer_config()
    if not cfg["enabled"]:
        return False, "Impressora termica desativada por configuracao."
    if cfg["mode"] == "queue":
        return True, "Impressao remota via fila/agente local."
    if sys.platform != "win32":
        return False, "Impressao termica direta suportada apenas no Windows."
    if win32print is None:
        return False, "Dependencia pywin32/win32print nao encontrada."
    if not cfg["name"]:
        return False, "Nome da impressora termica nao configurado."
    resolved_name = _resolve_printer_name(cfg["name"])
    if not resolved_name:
        available = ", ".join(list_printer_names()) or "nenhuma impressora encontrada"
        return False, f"Impressora '{cfg['name']}' nao encontrada. Disponiveis: {available}."
    return True, None


def imprimir_senha(
    numero: str,
    tipo: str,
    unidade: str,
    data_hora: datetime | None = None,
    teste: bool = False,
) -> dict:
    """Gera ESC/POS e envia os bytes diretamente para a impressora."""
    pronto, motivo = printer_ready()
    if not pronto:
        raise PrinterError(motivo or "Impressora indisponivel.")

    cfg = printer_config()
    data_hora = data_hora or datetime.now()
    payload = _montar_payload(
        numero=numero,
        tipo=tipo,
        unidade=unidade,
        data_hora=data_hora,
        encoding=cfg["encoding"],
        teste=teste,
    )

    job_name = f"Senha {tipo} {numero}"
    printer_name = _resolve_printer_name(cfg["name"]) or cfg["name"]
    try:
        handle = win32print.OpenPrinter(printer_name)
    except Exception as exc:  # pragma: no cover - Windows-specific
        logger.exception("Falha ao abrir a impressora %s", printer_name)
        raise PrinterError(f"Nao foi possivel abrir a impressora '{printer_name}'.") from exc

    try:
        job_id = win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, payload)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        return {"printer": printer_name, "job_id": job_id, "bytes": len(payload)}
    except Exception as exc:  # pragma: no cover - Windows-specific
        logger.exception("Falha ao enviar bytes ESC/POS para %s", printer_name)
        raise PrinterError(f"Falha ao imprimir na impressora '{printer_name}'.") from exc
    finally:
        try:
            win32print.ClosePrinter(handle)
        except Exception:  # pragma: no cover - Windows-specific
            logger.exception("Falha ao fechar handle da impressora %s", printer_name)


def _montar_payload(
    numero: str,
    tipo: str,
    unidade: str,
    data_hora: datetime,
    encoding: str,
    teste: bool,
) -> bytes:
    unidade_txt = _sanitize(unidade).upper()
    tipo_txt = _sanitize(tipo).upper()
    tipo_curto = _tipo_curto(tipo_txt)
    titulo = "CUPOM DE TESTE" if teste else "SENHA DE ATENDIMENTO"
    aviso = "NAO CONSUME SENHA REAL" if teste else "AGUARDE O CHAMADO NO PAINEL"
    linhas = [
        "\x1b@",
        "\x1bt\x02",
        "\x1ba\x01",
        "\x1bE\x01",
        "\x1d!\x11",
        f"{unidade_txt}\n",
        "\x1d!\x00",
        "\x1bE\x00",
        f"{titulo}\n",
        "=" * 32 + "\n",
        "\x1bE\x01",
        f"{tipo_txt}\n",
        "\x1bE\x00",
        f"{tipo_curto}\n",
        "-" * 32 + "\n",
        "SENHA\n",
        "\x1d!\x22",
        f"{numero}\n",
        "\x1d!\x00",
        "-" * 32 + "\n",
        "\x1ba\x00",
        f"DATA: {data_hora.strftime('%d/%m/%Y')}\n",
        f"HORA: {data_hora.strftime('%H:%M:%S')}\n",
        "\x1ba\x01",
        "-" * 32 + "\n",
        f"{aviso}\n",
        "DIRIJA-SE AO PAINEL\n",
        "\n",
        "\x1ba\x00",
        "PROTOCOLO GERADO PELO SISTEMA\n",
        "\x1ba\x01",
        "\n\n\n",
        "\x1dV\x00",
    ]

    texto = "".join(linhas)
    return texto.encode(encoding, errors="replace")


def _sanitize(valor: str) -> str:
    """Normaliza texto para evitar caracteres nao suportados pela impressora."""
    normalized = unicodedata.normalize("NFKD", valor or "")
    return normalized.encode("ascii", "ignore").decode("ascii")


def _resolve_printer_name(configured_name: str) -> str | None:
    """Tenta localizar a impressora por nome exato ou similar."""
    available = list_printer_names()
    if not available:
        return None

    if configured_name in available:
        return configured_name

    lower_name = configured_name.casefold()
    for candidate in available:
        if candidate.casefold() == lower_name:
            return candidate

    normalized_name = _normalize_name(configured_name)
    for candidate in available:
        candidate_normalized = _normalize_name(candidate)
        if normalized_name and (
            normalized_name in candidate_normalized or candidate_normalized in normalized_name
        ):
            return candidate

    configured_tokens = set(_tokenize_name(configured_name))
    if configured_tokens:
        ranked = []
        for candidate in available:
            tokens = set(_tokenize_name(candidate))
            overlap = len(configured_tokens & tokens)
            if overlap:
                ranked.append((overlap, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
            return ranked[0][1]

    return None


def _normalize_name(value: str) -> str:
    base = unicodedata.normalize("NFKD", value or "")
    ascii_only = base.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_only.casefold() if ch.isalnum())


def _tokenize_name(value: str) -> list[str]:
    base = unicodedata.normalize("NFKD", value or "")
    ascii_only = base.encode("ascii", "ignore").decode("ascii").casefold()
    return [token for token in re.split(r"[^a-z0-9]+", ascii_only) if token]


def _tipo_curto(tipo: str) -> str:
    if "PREFERENCIAL" in tipo:
        return "ATENDIMENTO PRIORITARIO"
    if "NORMAL" in tipo:
        return "ATENDIMENTO PADRAO"
    return tipo
