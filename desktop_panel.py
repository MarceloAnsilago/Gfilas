import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app import printer
from print_agent_client import PrintAgentConfig, PrintAgentConfigError, run_agent_loop

if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover
    msvcrt = None


LOGGER_NAME = "painel_desktop"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(slots=True)
class DesktopPanelConfig:
    base_url: str
    print_agent_token: str
    thermal_printer_name: str
    thermal_printer_encoding: str
    poll_interval: float
    open_panel: bool
    panel_url: str
    browser_mode: str


def main() -> int:
    base_dir = Path(get_runtime_dir())
    setup_logging(base_dir)

    try:
        lock_handle = acquire_single_instance_lock(base_dir)
    except RuntimeError as exc:
        logging.getLogger(LOGGER_NAME).error(str(exc))
        print(str(exc))
        return 1

    try:
        config = load_desktop_config(base_dir)
        apply_config_to_environment(config)
        validate_desktop_config(config)

        pronto, motivo = printer.printer_ready()
        if not pronto:
            raise PrintAgentConfigError(f"Impressora local indisponivel: {motivo}")

        stop_event = threading.Event()
        agent_config = PrintAgentConfig(
            base_url=config.base_url,
            token=config.print_agent_token,
            poll_interval=config.poll_interval,
        )
        agent_thread = threading.Thread(
            target=run_agent_loop,
            name="print-agent",
            args=(agent_config, stop_event),
            daemon=True,
        )
        agent_thread.start()
        logging.getLogger(LOGGER_NAME).info("Thread de impressao iniciada.")

        if not config.open_panel:
            logging.getLogger(LOGGER_NAME).info("OPEN_PANEL desativado; mantendo apenas o agente local.")
            agent_thread.join()
            return 0

        return run_panel_foreground(config, stop_event)
    except PrintAgentConfigError as exc:
        logging.getLogger(LOGGER_NAME).error(str(exc))
        print(str(exc))
        return 1
    except Exception:
        logging.getLogger(LOGGER_NAME).exception("Falha fatal no Painel desktop.")
        print("Falha fatal ao iniciar o Painel. Consulte logs/painel.log.")
        return 1
    finally:
        release_single_instance_lock(lock_handle)


def get_runtime_dir() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return str(Path(__file__).resolve().parent)


def setup_logging(base_dir: Path) -> None:
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "painel.log"

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def acquire_single_instance_lock(base_dir: Path):
    if sys.platform != "win32" or msvcrt is None:
        return None

    lock_path = base_dir / "painel.lock"
    handle = open(lock_path, "a+b")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        handle.close()
        raise RuntimeError("Outra instancia do Painel.exe ja esta em execucao.") from exc

    handle.seek(0)
    handle.write(str(os.getpid()).encode("ascii", errors="ignore")[:32].ljust(32, b" "))
    handle.flush()
    return handle


def release_single_instance_lock(lock_handle) -> None:
    if not lock_handle:
        return
    try:
        if sys.platform == "win32" and msvcrt is not None:
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        lock_handle.close()


def load_desktop_config(base_dir: Path) -> DesktopPanelConfig:
    env_path = base_dir / ".env"
    json_path = base_dir / "painel_config.json"

    load_dotenv(env_path)
    payload: dict[str, Any] = {}
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8-sig"))

    def get_value(name: str, default=None):
        if name in payload and payload[name] not in (None, ""):
            return payload[name]
        return os.getenv(name, default)

    base_url = str(get_value("BASE_URL") or get_value("PRINT_AGENT_BASE_URL") or "").strip().rstrip("/")
    token = str(get_value("PRINT_AGENT_TOKEN") or "").strip()
    printer_name = str(get_value("THERMAL_PRINTER_NAME") or "POS58 DRIVER (TESTADO)").strip()
    printer_encoding = str(get_value("THERMAL_PRINTER_ENCODING") or "cp850").strip()
    poll_interval_raw = str(get_value("POLL_INTERVAL") or get_value("PRINT_AGENT_POLL_INTERVAL") or "1.0").strip()
    open_panel = _as_bool(get_value("OPEN_PANEL"), True)
    browser_mode = str(get_value("BROWSER_MODE") or "edge_kiosk").strip().lower()
    panel_url = str(get_value("PANEL_URL") or (f"{base_url}/painel" if base_url else "")).strip()

    try:
        poll_interval = max(float(poll_interval_raw), 0.2)
    except ValueError as exc:
        raise PrintAgentConfigError("POLL_INTERVAL invalido em painel_config.json/.env.") from exc

    return DesktopPanelConfig(
        base_url=base_url,
        print_agent_token=token,
        thermal_printer_name=printer_name,
        thermal_printer_encoding=printer_encoding,
        poll_interval=poll_interval,
        open_panel=open_panel,
        panel_url=panel_url,
        browser_mode=browser_mode,
    )


def apply_config_to_environment(config: DesktopPanelConfig) -> None:
    os.environ["THERMAL_PRINTER_MODE"] = "local"
    os.environ["THERMAL_PRINTER_ENABLED"] = "1"
    os.environ["THERMAL_PRINTER_NAME"] = config.thermal_printer_name
    os.environ["THERMAL_PRINTER_ENCODING"] = config.thermal_printer_encoding
    os.environ["PRINT_AGENT_BASE_URL"] = config.base_url
    os.environ["PRINT_AGENT_TOKEN"] = config.print_agent_token
    os.environ["PRINT_AGENT_POLL_INTERVAL"] = str(config.poll_interval)


def validate_desktop_config(config: DesktopPanelConfig) -> None:
    if not config.base_url:
        raise PrintAgentConfigError("BASE_URL nao configurado em painel_config.json nem em .env.")
    if not config.print_agent_token:
        raise PrintAgentConfigError("PRINT_AGENT_TOKEN nao configurado em painel_config.json nem em .env.")
    if not config.thermal_printer_name:
        raise PrintAgentConfigError("THERMAL_PRINTER_NAME nao configurado.")
    if config.open_panel and not config.panel_url:
        raise PrintAgentConfigError("PANEL_URL nao configurado.")


def run_panel_foreground(config: DesktopPanelConfig, stop_event: threading.Event) -> int:
    logger = logging.getLogger(LOGGER_NAME)
    process = open_panel_process(config)
    try:
        logger.info("Painel aberto em %s usando modo %s.", config.panel_url, config.browser_mode)
        return process.wait()
    except KeyboardInterrupt:
        logger.info("Encerrando Painel desktop por interrupcao.")
        return 0
    finally:
        stop_event.set()
        if process.poll() is None:
            process.terminate()


def open_panel_process(config: DesktopPanelConfig) -> subprocess.Popen:
    mode = config.browser_mode
    if mode == "edge_kiosk":
        executable = resolve_browser_executable("msedge")
        return subprocess.Popen(
            [executable, "--kiosk", config.panel_url, "--edge-kiosk-type=fullscreen"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if mode == "chrome_kiosk":
        executable = resolve_browser_executable("chrome")
        return subprocess.Popen(
            [executable, "--kiosk", "--app=" + config.panel_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if mode == "pywebview":
        return open_panel_pywebview(config.panel_url)
    raise PrintAgentConfigError(
        "BROWSER_MODE invalido. Use edge_kiosk, chrome_kiosk ou pywebview."
    )


def open_panel_pywebview(panel_url: str) -> subprocess.Popen:
    try:
        import webview  # noqa: F401
    except ImportError as exc:
        raise PrintAgentConfigError("Modo pywebview requer a dependencia pywebview instalada.") from exc

    script = (
        "import webview;"
        f"webview.create_window('Painel', '{panel_url}', fullscreen=True);"
        "webview.start()"
    )
    try:
        return subprocess.Popen([sys.executable, "-c", script])
    except FileNotFoundError as exc:
        raise PrintAgentConfigError("Modo pywebview indisponivel neste ambiente.") from exc


def resolve_browser_executable(browser: str) -> str:
    candidates = {
        "msedge": [
            os.getenv("PROGRAMFILES(X86)", "") + r"\Microsoft\Edge\Application\msedge.exe",
            os.getenv("PROGRAMFILES", "") + r"\Microsoft\Edge\Application\msedge.exe",
            os.getenv("LOCALAPPDATA", "") + r"\Microsoft\Edge\Application\msedge.exe",
            "msedge.exe",
        ],
        "chrome": [
            os.getenv("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
            os.getenv("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
            os.getenv("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
            "chrome.exe",
        ],
    }
    for candidate in candidates.get(browser, []):
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists() or len(path.parts) == 1:
            return candidate
    raise PrintAgentConfigError(f"Navegador {browser} nao encontrado neste PC.")


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


if __name__ == "__main__":
    raise SystemExit(main())
