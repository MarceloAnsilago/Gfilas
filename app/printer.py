import logging
import os
import re
import sys
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import win32print
    import win32ui
    import win32con
except ImportError:  # pragma: no cover - depends on Windows runtime
    win32print = None
    win32ui = None
    win32con = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageWin
except ImportError:  # pragma: no cover - depends on runtime packaging
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageWin = None


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
        "line_ending": (os.getenv("THERMAL_PRINTER_LINE_ENDING") or "crlf").strip().lower(),
        "codepage_command": (os.getenv("THERMAL_PRINTER_CODEPAGE_COMMAND") or "").strip(),
        "cut_enabled": (os.getenv("THERMAL_PRINTER_CUT") or "0").strip().lower() in {"1", "true", "yes", "on"},
        "datatype": (os.getenv("THERMAL_PRINTER_DATATYPE") or "RAW").strip().upper(),
        "protocol": (os.getenv("THERMAL_PRINTER_PROTOCOL") or "escpos_raster").strip().lower(),
        "raster_width": int((os.getenv("THERMAL_PRINTER_RASTER_WIDTH") or "384").strip()),
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
        config=cfg,
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
        if cfg["protocol"] == "escpos_raster":
            logger.info(
                "Enviando job para impressora=%s datatype=RAW protocol=%s",
                printer_name,
                cfg["protocol"],
            )
            return _imprimir_via_escpos_raster(
                printer_name=printer_name,
                job_name=job_name,
                numero=numero,
                tipo=tipo,
                unidade=unidade,
                data_hora=data_hora,
                teste=teste,
                width=cfg["raster_width"],
            )
        if cfg["protocol"] == "bitmap":
            logger.info(
                "Enviando job para impressora=%s datatype=BITMAP protocol=%s",
                printer_name,
                cfg["protocol"],
            )
            return _imprimir_via_bitmap(
                printer_name=printer_name,
                job_name=job_name,
                numero=numero,
                tipo=tipo,
                unidade=unidade,
                data_hora=data_hora,
                teste=teste,
            )
        if cfg["protocol"] == "gdi_text":
            logger.info(
                "Enviando job para impressora=%s datatype=GDI protocol=%s",
                printer_name,
                cfg["protocol"],
            )
            return _imprimir_via_gdi(
                printer_name=printer_name,
                job_name=job_name,
                numero=numero,
                tipo=tipo,
                unidade=unidade,
                data_hora=data_hora,
                teste=teste,
            )

        datatype = cfg["datatype"] or "RAW"
        logger.info(
            "Enviando job para impressora=%s datatype=%s protocol=%s bytes=%s",
            printer_name,
            datatype,
            cfg["protocol"],
            len(payload),
        )
        job_id = win32print.StartDocPrinter(handle, 1, (job_name, None, datatype))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, payload)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        return {
            "printer": printer_name,
            "job_id": job_id,
            "bytes": len(payload),
            "datatype": datatype,
            "protocol": cfg["protocol"],
        }
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
    config: dict,
    teste: bool,
) -> bytes:
    encoding = config["encoding"]
    newline = "\r\n" if config.get("line_ending") != "lf" else "\n"
    if config.get("protocol") == "text":
        return _montar_payload_texto(numero, tipo, unidade, data_hora, encoding, teste, newline)

    unidade_txt = _sanitize(unidade).upper()
    tipo_txt = _sanitize(tipo).upper()
    tipo_curto = _tipo_curto(tipo_txt)
    titulo = "CUPOM DE TESTE" if teste else "SENHA DE ATENDIMENTO"
    aviso = "NAO CONSUME SENHA REAL" if teste else "AGUARDE O CHAMADO NO PAINEL"
    codepage_command = _build_codepage_command(config.get("codepage_command"))
    linhas = ["\x1b@"]
    if codepage_command:
        linhas.append(codepage_command)
    linhas.extend(
        [
            "\x1ba\x01",
            "\x1bE\x01",
            f"{unidade_txt}{newline}",
            "\x1bE\x00",
            f"{titulo}{newline}",
            "=" * 32 + newline,
            "\x1bE\x01",
            f"{tipo_txt}{newline}",
            "\x1bE\x00",
            f"{tipo_curto}{newline}",
            "-" * 32 + newline,
            "SENHA" + newline,
            "\x1d!\x11",
            f"{numero}{newline}",
            "\x1d!\x00",
            "-" * 32 + newline,
            "\x1ba\x00",
            f"DATA: {data_hora.strftime('%d/%m/%Y')}{newline}",
            f"HORA: {data_hora.strftime('%H:%M:%S')}{newline}",
            "\x1ba\x01",
            "-" * 32 + newline,
            f"{aviso}{newline}",
            f"DIRIJA-SE AO PAINEL{newline}",
            newline,
            "\x1ba\x00",
            f"PROTOCOLO GERADO PELO SISTEMA{newline}",
            "\x1ba\x01",
            newline * 4,
        ]
    )
    if config.get("cut_enabled"):
        linhas.append("\x1dV\x00")

    texto = "".join(linhas)
    return texto.encode(encoding, errors="replace")


def _montar_payload_texto(
    numero: str,
    tipo: str,
    unidade: str,
    data_hora: datetime,
    encoding: str,
    teste: bool,
    newline: str,
) -> bytes:
    unidade_txt = _sanitize(unidade).upper()
    tipo_txt = _sanitize(tipo).upper()
    tipo_curto = _tipo_curto(tipo_txt)
    titulo = "CUPOM DE TESTE" if teste else "SENHA DE ATENDIMENTO"
    aviso = "NAO CONSUME SENHA REAL" if teste else "AGUARDE O CHAMADO NO PAINEL"
    linhas = [
        unidade_txt,
        titulo,
        "=" * 32,
        tipo_txt,
        tipo_curto,
        "-" * 32,
        "SENHA",
        numero,
        "-" * 32,
        f"DATA: {data_hora.strftime('%d/%m/%Y')}",
        f"HORA: {data_hora.strftime('%H:%M:%S')}",
        "-" * 32,
        aviso,
        "DIRIJA-SE AO PAINEL",
        "",
        "PROTOCOLO GERADO PELO SISTEMA",
        "",
        "",
        "",
    ]
    return newline.join(linhas).encode(encoding, errors="replace")


def _imprimir_via_gdi(
    printer_name: str,
    job_name: str,
    numero: str,
    tipo: str,
    unidade: str,
    data_hora: datetime,
    teste: bool,
) -> dict:
    if win32ui is None or win32con is None:
        raise PrinterError("Dependencias win32ui/win32con nao disponiveis para GDI.")

    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(printer_name)
        hdc.StartDoc(job_name)
        hdc.StartPage()

        largura = hdc.GetDeviceCaps(8)
        margem_x = 40
        y = 30

        fonte_titulo = win32ui.CreateFont(
            {
                "name": "Courier New",
                "height": 46,
                "weight": 700,
            }
        )
        fonte_normal = win32ui.CreateFont(
            {
                "name": "Courier New",
                "height": 28,
                "weight": 400,
            }
        )
        fonte_numero = win32ui.CreateFont(
            {
                "name": "Courier New",
                "height": 72,
                "weight": 800,
            }
        )

        y = _draw_centered_line(hdc, unidade.upper(), fonte_titulo, largura, y)
        y = _draw_centered_line(hdc, "CUPOM DE TESTE" if teste else "SENHA DE ATENDIMENTO", fonte_normal, largura, y)
        y = _draw_centered_line(hdc, "=" * 24, fonte_normal, largura, y)
        y = _draw_centered_line(hdc, tipo.upper(), fonte_titulo, largura, y)
        y = _draw_centered_line(hdc, _tipo_curto(tipo.upper()), fonte_normal, largura, y)
        y = _draw_centered_line(hdc, "-" * 24, fonte_normal, largura, y)
        y = _draw_centered_line(hdc, "SENHA", fonte_normal, largura, y)
        y = _draw_centered_line(hdc, numero, fonte_numero, largura, y + 10)
        y = _draw_centered_line(hdc, "-" * 24, fonte_normal, largura, y)

        linhas = [
            f"DATA: {data_hora.strftime('%d/%m/%Y')}",
            f"HORA: {data_hora.strftime('%H:%M:%S')}",
            "-" * 24,
            "NAO CONSUME SENHA REAL" if teste else "AGUARDE O CHAMADO NO PAINEL",
            "DIRIJA-SE AO PAINEL",
            "",
            "PROTOCOLO GERADO PELO SISTEMA",
        ]
        for linha in linhas:
            hdc.SelectObject(fonte_normal)
            hdc.TextOut(margem_x, y, _sanitize(linha))
            y += 34

        hdc.EndPage()
        hdc.EndDoc()
        return {"printer": printer_name, "job_id": None, "bytes": 0, "datatype": "GDI", "protocol": "gdi_text"}
    except Exception as exc:  # pragma: no cover - Windows-specific
        logger.exception("Falha ao imprimir via GDI em %s", printer_name)
        raise PrinterError(f"Falha ao imprimir via driver Windows na impressora '{printer_name}'.") from exc
    finally:
        try:
            hdc.DeleteDC()
        except Exception:  # pragma: no cover
            logger.exception("Falha ao liberar DC da impressora %s", printer_name)


def _imprimir_via_bitmap(
    printer_name: str,
    job_name: str,
    numero: str,
    tipo: str,
    unidade: str,
    data_hora: datetime,
    teste: bool,
) -> dict:
    if Image is None or ImageDraw is None or ImageFont is None or ImageWin is None:
        raise PrinterError("Dependencias PIL/Pillow nao disponiveis para impressao bitmap.")
    if win32ui is None or win32con is None:
        raise PrinterError("Dependencias win32ui/win32con nao disponiveis para impressao bitmap.")

    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(printer_name)
        hdc.StartDoc(job_name)
        hdc.StartPage()

        width = hdc.GetDeviceCaps(win32con.HORZRES)
        if width < 300:
            width = 384
        margin = 20
        content_width = max(width - (margin * 2), 200)

        lines = _build_receipt_lines(numero, tipo, unidade, data_hora, teste)
        image = _render_receipt_image(lines, content_width)
        dib = ImageWin.Dib(image)
        dib.draw(hdc.GetHandleOutput(), (0, 0, image.width, image.height))

        hdc.EndPage()
        hdc.EndDoc()
        return {
            "printer": printer_name,
            "job_id": None,
            "bytes": image.width * image.height,
            "datatype": "BITMAP",
            "protocol": "bitmap",
        }
    except Exception as exc:  # pragma: no cover - Windows-specific
        logger.exception("Falha ao imprimir bitmap em %s", printer_name)
        raise PrinterError(f"Falha ao imprimir bitmap na impressora '{printer_name}'.") from exc
    finally:
        try:
            hdc.DeleteDC()
        except Exception:  # pragma: no cover
            logger.exception("Falha ao liberar DC da impressora %s", printer_name)


def _imprimir_via_escpos_raster(
    printer_name: str,
    job_name: str,
    numero: str,
    tipo: str,
    unidade: str,
    data_hora: datetime,
    teste: bool,
    width: int,
) -> dict:
    if Image is None:
        raise PrinterError("Dependencia PIL/Pillow nao disponivel para raster ESC/POS.")

    lines = _build_receipt_lines(numero, tipo, unidade, data_hora, teste)
    image = _render_receipt_image(lines, width)
    payload = _image_to_escpos_raster(image)

    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        job_id = win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, payload)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        return {
            "printer": printer_name,
            "job_id": job_id,
            "bytes": len(payload),
            "datatype": "RAW",
            "protocol": "escpos_raster",
        }
    except Exception as exc:  # pragma: no cover - Windows-specific
        logger.exception("Falha ao imprimir raster ESC/POS em %s", printer_name)
        raise PrinterError(f"Falha ao imprimir raster ESC/POS na impressora '{printer_name}'.") from exc
    finally:
        if handle is not None:
            try:
                win32print.ClosePrinter(handle)
            except Exception:  # pragma: no cover
                logger.exception("Falha ao fechar handle da impressora %s", printer_name)


def _draw_centered_line(hdc, text: str, font, page_width: int, y: int) -> int:
    clean = _sanitize(text)
    hdc.SelectObject(font)
    width, height = hdc.GetTextExtent(clean)
    x = max(int((page_width - width) / 2), 0)
    hdc.TextOut(x, y, clean)
    return y + height + 10


def _build_receipt_lines(numero: str, tipo: str, unidade: str, data_hora: datetime, teste: bool) -> list[str]:
    unidade_txt = _sanitize(unidade).upper()
    tipo_txt = _sanitize(tipo).upper()
    tipo_curto = _tipo_curto(tipo_txt)
    titulo = "CUPOM DE TESTE" if teste else "SENHA DE ATENDIMENTO"
    aviso = "NAO CONSUME SENHA REAL" if teste else "AGUARDE O CHAMADO NO PAINEL"
    return [
        unidade_txt,
        "",
        titulo,
        "",
        "=" * 24,
        tipo_txt,
        tipo_curto,
        "-" * 24,
        "SENHA",
        numero,
        "-" * 24,
        f"DATA: {data_hora.strftime('%d/%m/%Y')}",
        f"HORA: {data_hora.strftime('%H:%M:%S')}",
        "",
        aviso,
        "DIRIJA-SE AO PAINEL",
        "",
        "PROTOCOLO GERADO PELO SISTEMA",
    ]


def _render_receipt_image(lines: list[str], width: int):
    bg = "white"
    fg = "black"
    margin = 18
    font_title = _load_font(30, bold=True)
    font_label = _load_font(22, bold=False)
    font_number = _load_font(54, bold=True)

    # Primeiro calcula a altura necessária com uma versão temporária do desenho.
    temp = Image.new("RGB", (width, 2000), bg)
    draw = ImageDraw.Draw(temp)
    y = margin
    for line in lines:
        font = font_number if line == lines[9] else font_title if line in {"CUPOM DE TESTE", "SENHA DE ATENDIMENTO", "SENHA"} else font_label
        wrapped = _wrap_for_width(draw, line, font, width - (margin * 2))
        if not wrapped:
            y += 10
            continue
        for part in wrapped:
            bbox = draw.textbbox((0, 0), part, font=font)
            line_height = bbox[3] - bbox[1]
            y += line_height + 8
    height = y + margin + 40

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    y = margin
    for line in lines:
        if line == "SENHA":
            font = font_title
        elif line == lines[9]:
            font = font_number
        elif line in {"CUPOM DE TESTE", "SENHA DE ATENDIMENTO"}:
            font = font_title
        else:
            font = font_label

        wrapped = _wrap_for_width(draw, line, font, width - (margin * 2))
        if not wrapped:
            y += 10
            continue
        for part in wrapped:
            bbox = draw.textbbox((0, 0), part, font=font)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]
            x = max(int((width - line_width) / 2), margin)
            draw.text((x, y), part, font=font, fill=fg)
            y += line_height + 8

    draw.rectangle((margin, 0, width - margin, 4), fill=fg)
    draw.rectangle((margin, height - 6, width - margin, height - 2), fill=fg)
    return image.convert("RGB")


def _wrap_for_width(draw, text: str, font, max_width: int) -> list[str]:
    clean = _sanitize(text)
    if not clean:
        return []
    if draw.textbbox((0, 0), clean, font=font)[2] <= max_width:
        return [clean]

    parts = []
    current = ""
    for word in clean.split():
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        if current:
            parts.append(current)
        current = word
    if current:
        parts.append(current)
    return parts or [clean]


def _load_font(size: int, bold: bool = False):
    candidates = []
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    fonts_dir = os.path.join(windir, "Fonts")
    if bold:
        candidates.extend(
            [
                os.path.join(fonts_dir, "arialbd.ttf"),
                os.path.join(fonts_dir, "courbd.ttf"),
                os.path.join(fonts_dir, "luconbd.ttf"),
            ]
        )
    else:
        candidates.extend(
            [
                os.path.join(fonts_dir, "arial.ttf"),
                os.path.join(fonts_dir, "cour.ttf"),
                os.path.join(fonts_dir, "lucon.ttf"),
            ]
        )

    for candidate in candidates:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _image_to_escpos_raster(image) -> bytes:
    """Converte uma imagem PIL para o comando GS v 0 da ESC/POS."""
    dither_none = getattr(Image, "Dither", None)
    if dither_none is not None:
        bw = image.convert("1", dither=Image.Dither.NONE)
    else:  # pragma: no cover - compatibilidade com Pillow antigo
        bw = image.convert("1", dither=Image.NONE)
    width, height = bw.size
    width_bytes = (width + 7) // 8
    payload = bytearray()
    payload.extend(b"\x1b@")
    payload.extend(b"\x1dv0\x00")
    payload.extend(bytes((width_bytes & 0xFF, (width_bytes >> 8) & 0xFF, height & 0xFF, (height >> 8) & 0xFF)))

    pixels = bw.load()
    for y in range(height):
        for x_byte in range(width_bytes):
            value = 0
            for bit in range(8):
                x = (x_byte * 8) + bit
                value <<= 1
                if x < width and pixels[x, y] == 0:
                    value |= 1
            payload.append(value)

    payload.extend(b"\n\n\n")
    return bytes(payload)


def _build_codepage_command(raw_value: str | None) -> str:
    """Monta ESC t n apenas quando explicitamente configurado."""
    if not raw_value:
        return ""
    try:
        codepage = int(str(raw_value).strip(), 0)
    except ValueError:
        logger.warning("THERMAL_PRINTER_CODEPAGE_COMMAND invalido: %r", raw_value)
        return ""
    if codepage < 0 or codepage > 255:
        logger.warning("THERMAL_PRINTER_CODEPAGE_COMMAND fora da faixa: %r", raw_value)
        return ""
    return "\x1bt" + chr(codepage)


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
