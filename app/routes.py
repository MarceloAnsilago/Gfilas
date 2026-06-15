from datetime import date, datetime
from collections import Counter
import logging
import os
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for, session, jsonify

from . import db, printer

logger = logging.getLogger(__name__)


def _read_env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Invalid value %r for %s; using fallback %s", raw, name, fallback)
        return fallback


DEFAULT_UNIDADE = "UNIDADE"
DEFAULT_USUARIO = "admin"
DEFAULT_PLAYLIST_ID = "PLrBhE4oLMMj95y5nobzQgDT8ygY-Pqbk3"
FIELD_LABELS = {
    "senha_inicial": "senha inicial",
    "senha_final": "senha final",
}
MAX_PAINEL_ULTIMAS = _read_env_int("PAINEL_MAX_ULTIMAS", 8)
PRIORIDADE_LABELS = {
    "normal": "Senha normal",
    "preferencial": "Senha preferencial",
}

bp = Blueprint("web", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/chamar", methods=["GET", "POST"])
def chamar():
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        terminal = (request.form.get("terminal") or "").strip()
        session["usuario_chamar"] = usuario
        session["terminal_chamar"] = terminal
    else:
        usuario = (request.args.get("usuario") or "").strip() or session.get("usuario_chamar", "")
        terminal = (request.args.get("terminal") or "").strip() or session.get("terminal_chamar", "")

    if request.method == "POST":
        acao = request.form.get("acao")

        if acao == "chamar":
            if not terminal.isdigit():
                flash("O campo Terminal deve conter apenas numeros.", "warning")
                return redirect(url_for("web.chamar"))

            chamada_aberta = db.obter_chamada_aberta()
            if chamada_aberta:
                flash(
                    f"Aguarde o usuario {chamada_aberta.get('usuario', 'N/A')} finalizar no terminal {chamada_aberta.get('terminal', 'N/A')}.",
                    "warning",
                )
                return redirect(url_for("web.chamar"))

            proxima = db.proxima_senha_aguardando()
            if not proxima:
                flash("Nenhuma senha aguardando para chamada.", "info")
                return redirect(url_for("web.chamar"))

            hora_atual = datetime.now(db.FUSO_HORARIO).isoformat()
            db.atualizar_senha(
                proxima["id"],
                {
                    "hora": hora_atual,
                    "resposta": "chamando 1",
                    "status": "aberto",
                    "usuario": usuario or DEFAULT_USUARIO,
                    "terminal": int(terminal),
                },
            )
            flash(f"Senha {int(proxima['senha']):03} chamada no terminal {terminal}.", "success")
            return redirect(url_for("web.chamar"))

        chamada_atual = db.obter_chamada_aberta()
        if not chamada_atual:
            flash("Nenhuma senha esta em atendimento no momento.", "info")
            return redirect(url_for("web.chamar"))

        if acao == "chamar_novamente":
            atual = (chamada_atual.get("resposta") or "chamando 1").split()
            try:
                numero_atual = int(atual[-1])
            except (ValueError, IndexError):
                numero_atual = 1
            novo_valor = f"chamando {numero_atual + 1}"
            db.atualizar_senha(chamada_atual["id"], {"resposta": novo_valor, "hora": datetime.now(db.FUSO_HORARIO).isoformat()})
            flash("Senha chamada novamente.", "success")
        elif acao == "compareceu":
            db.atualizar_senha(
                chamada_atual["id"],
                {"resposta": "compareceu", "status": "encerrado", "hora": datetime.now(db.FUSO_HORARIO).isoformat()},
            )
            flash("Senha encerrada como compareceu.", "success")
        elif acao == "nao_compareceu":
            db.atualizar_senha(
                chamada_atual["id"],
                {"resposta": "nao compareceu", "status": "encerrado", "hora": datetime.now(db.FUSO_HORARIO).isoformat()},
            )
            flash("Senha encerrada como nao compareceu.", "info")

        return redirect(url_for("web.chamar"))

    chamada_aberta = db.obter_chamada_aberta()
    fila_ativa = db.obter_fila_ativa()
    data_producao = fila_ativa["data"] if fila_ativa else None
    proxima_senha = db.proxima_senha_aguardando()
    aguardando = db.listar_senhas(
        status="aguardando",
        data_iso=data_producao,
        origem=fila_ativa["origem"] if fila_ativa else None,
    )

    return render_template(
        "chamar.html",
        usuario=usuario,
        terminal=terminal,
        chamada_aberta=chamada_aberta,
        proxima_senha=proxima_senha,
        aguardando=aguardando,
        total_aguardando=len(aguardando),
        data_producao=data_producao,
        origem_fila_ativa=fila_ativa["origem"] if fila_ativa else None,
        prioridade_labels=PRIORIDADE_LABELS,
    )

@bp.route("/gerar", methods=["GET", "POST"])
def gerar_senhas():
    if request.method == "POST":
        unidade = request.form.get("unidade", DEFAULT_UNIDADE).strip() or DEFAULT_UNIDADE
        try:
            senha_inicial = _parse_int_from_form(request.form, "senha_inicial", 1)
            senha_final = _parse_int_from_form(request.form, "senha_final", 50)
        except ValueError as exc:
            field_label = FIELD_LABELS.get(exc.args[0], exc.args[0])
            flash(
                f"O campo {field_label} precisa ser um número inteiro válido.",
                "warning",
            )
            return redirect(url_for("web.gerar_senhas"))
        data_str = request.form.get("data_execucao") or date.today().isoformat()

        try:
            data_escolhida = datetime.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Aviso: informe uma data valida.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        if senha_final < senha_inicial:
            flash("Aviso: a senha final deve ser maior ou igual a inicial.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        if senha_inicial < 1 or senha_final < 1:
            flash("Informe valores positivos para a faixa de senhas.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        inseridas, duplicadas = 0, 0
        iso_data = data_escolhida.isoformat()
        for numero in range(senha_inicial, senha_final + 1):
            if db.senha_existe(numero, iso_data):
                duplicadas += 1
                continue
            db.inserir_senha(numero, unidade, data_execucao=data_escolhida, origem="lote")
            inseridas += 1

        formatted_date = data_escolhida.strftime("%d/%m/%Y")
        if inseridas and db.obter_origem_padrao() != "totem" and not db.obter_data_producao():
            db.definir_data_producao(iso_data)
            db.definir_origem_padrao("lote")
        if inseridas:
            flash(
                f"Sucesso: {inseridas} senhas geradas com sucesso para {formatted_date}.",
                "success",
            )
        if duplicadas:
            flash(
                f"Info: {duplicadas} senhas ja existiam para {formatted_date}.",
                "info",
            )

        return redirect(url_for("web.gerar_senhas"))

    total_senhas = db.contar_senhas()
    data_padrao = date.today().isoformat()
    data_producao = db.obter_data_producao_ativa()
    origem_padrao = db.obter_origem_padrao()
    sessoes_brutas = db.listar_sessoes_por_data(origem="lote")
    sessoes = []
    for sessao in sessoes_brutas:
        data_iso = sessao.get("data")
        sessoes.append(
            {
                **sessao,
                "data_legivel": _formatar_data_local(data_iso) if data_iso else "",
                "em_producao": origem_padrao == "lote" and data_iso == data_producao,
            }
        )
    return render_template(
        "gerar.html",
        total_senhas=total_senhas,
        data_padrao=data_padrao,
        sessoes=sessoes,
        data_producao=data_producao,
    )


@bp.route("/gerar/definir-producao", methods=["POST"])
def definir_sessao_producao():
    data_str = (request.form.get("data_execucao") or "").strip()
    if not data_str:
        flash("Informe a data da sessao que entrara em producao.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    sessoes = db.listar_sessoes_por_data(origem="lote")
    datas_validas = {sessao.get("data") for sessao in sessoes}
    if data_str not in datas_validas:
        flash("A sessao selecionada nao foi encontrada.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    db.definir_data_producao(data_str)
    db.definir_origem_padrao("lote")
    flash(
        f"Sessao de {datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')} marcada como em producao.",
        "success",
    )
    return redirect(url_for("web.gerar_senhas"))


@bp.route("/gerar/excluir-sessao", methods=["POST"])
def excluir_sessao_senhas():
    data_str = (request.form.get("data_execucao") or "").strip()
    if not data_str:
        flash("Informe a data da sessão que deseja remover.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    try:
        data_formatada = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Informe uma data válida.", "warning")
        return redirect(url_for("web.gerar_senhas"))

    removidas = db.excluir_senhas_por_data(data_str)
    if removidas:
        flash(
            f"Sessão de {data_formatada.strftime('%d/%m/%Y')} removida ({removidas} senhas).",
            "success",
        )
    else:
        flash("Nenhuma senha encontrada para essa data.", "info")

    return redirect(url_for("web.gerar_senhas"))


@bp.route("/imprimir", methods=["GET"])
def imprimir():
    todas_senhas = db.listar_senhas(status="aguardando")

    datas_disponiveis = sorted(
        {
            item.get("data_execucao") or _extrair_data_iso(item.get("hora"))
            for item in todas_senhas
            if item.get("data_execucao") or item.get("hora")
        }
    )
    datas_fmt = [
        {"valor": valor, "label": datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")}
        for valor in datas_disponiveis
    ]

    data_selecionada = request.args.get("data")
    if data_selecionada not in datas_disponiveis:
        data_selecionada = db.obter_data_producao_ativa()
        if data_selecionada not in datas_disponiveis:
            data_selecionada = datas_disponiveis[-1] if datas_disponiveis else None

    if data_selecionada:
        senhas_raw = [
            item
            for item in todas_senhas
            if (item.get("data_execucao") or _extrair_data_iso(item.get("hora"))) == data_selecionada
        ]
        titulo = f"Senhas de {datetime.strptime(data_selecionada, '%Y-%m-%d').strftime('%d/%m/%Y')}"
    else:
        senhas_raw = []
        titulo = "Nenhuma data com senhas aguardando"

    senhas = [
        {
            "unidade": item.get("unidade") or DEFAULT_UNIDADE,
            "senha": f"{int(item.get('senha', 0)):03}",
            "data_formatada": _formatar_data_local(item.get("hora")),
        }
        for item in senhas_raw
    ]

    if data_selecionada and not senhas:
        flash("Nenhuma senha encontrada para a data selecionada.", "info")
    elif not datas_disponiveis:
        flash("Nao ha senhas aguardando para imprimir.", "info")

    return render_template(
        "imprimir.html",
        titulo=titulo,
        senhas=senhas,
        datas_disponiveis=datas_fmt,
        data_selecionada=data_selecionada,
    )


@bp.route("/historico", methods=["GET", "POST"])
def historico():
    registros = db.listar_todas_senhas()
    sessoes_brutas = db.listar_sessoes_por_data(origem="lote")
    sessoes = []
    for sessao in sessoes_brutas:
        data_iso = sessao.get("data")
        sessoes.append(
            {
                **sessao,
                "data_legivel": _formatar_data_local(data_iso) if data_iso else "",
            }
        )
    sessao_padrao = sessoes[0]["data"] if sessoes else None
    sessao_data = request.args.get("sessao_data") or sessao_padrao

    if request.method == "POST":
        acao = (request.form.get("acao") or "").strip().lower()
        if acao == "encerrar_sequencia":
            inicio_raw = (request.form.get("senha_inicio") or "").strip()
            final_raw = (request.form.get("senha_final") or "").strip()
            if not inicio_raw.isdigit() or not final_raw.isdigit():
                flash("Informe valores inteiros válidos para o intervalo.", "warning")
                return redirect(url_for("web.historico"))

            inicio = int(inicio_raw)
            final = int(final_raw)
            if inicio < 1 or final < 1:
                flash("Os números devem ser positivos.", "warning")
                return redirect(url_for("web.historico"))
            if final < inicio:
                flash("A senha final precisa ser maior que a inicial.", "warning")
                return redirect(url_for("web.historico"))

            sessao_data = (request.form.get("sessao_data") or sessao_padrao)
            if not sessao_data:
                flash("Selecione a sessão que deseja encerrar.", "warning")
                return redirect(url_for("web.historico"))

            encerradas = db.encerrar_sequencia_senhas(inicio, final, data_iso=sessao_data)
            if not encerradas:
                flash(
                    "Nenhuma senha aguardando foi encontrada nesse intervalo.",
                    "info",
                )
            else:
                flash(
                    f"{encerradas} senhas encerradas da faixa {inicio}-{final} do dia {datetime.strptime(sessao_data, '%Y-%m-%d').strftime('%d/%m/%Y')}",
                    "success",
                )
            return redirect(url_for("web.historico", sessao_data=sessao_data))

        encerrar_id = (request.form.get("encerrar_id") or "").strip()
        if not encerrar_id.isdigit():
            flash("Informe um ID valido para encerrar.", "warning")
            return redirect(url_for("web.historico"))

        encerrar_id = int(encerrar_id)
        alvo = next((r for r in registros if r["id"] == encerrar_id), None)
        if not alvo:
            flash("Senha nao encontrada.", "warning")
            return redirect(url_for("web.historico"))
        if (alvo.get("status") or "").lower() != "aberto":
            flash("A senha selecionada ja estava encerrada.", "info")
            return redirect(url_for("web.historico"))

        acao = (acao or "nao_compareceu").strip().lower()
        if acao != "compareceu":
            acao = "nao_compareceu"
        resposta_padrao = "compareceu" if acao == "compareceu" else "nao compareceu"
        mensagem = (
            "Senha encerrada como compareceu."
            if acao == "compareceu"
            else "Senha encerrada como nao compareceu."
        )
        db.encerrar_senha(encerrar_id, resposta_padrao=resposta_padrao)
        flash(mensagem, "success")
        return redirect(url_for("web.historico"))

    status_counts = Counter(
        (registro.get("status") or "sem status").capitalize() for registro in registros
    )
    resposta_counts = Counter(
        (registro.get("resposta") or "sem resposta").capitalize() for registro in registros
        if registro.get("resposta")
    )
    usuario_counts = Counter(
        registro.get("usuario").strip()
        for registro in registros
        if registro.get("usuario")
        and registro.get("usuario").strip().lower() != DEFAULT_USUARIO
    )

    abertas = [
        {
            **registro,
            "hora_legivel": _formatar_data_hora(registro.get("hora")),
        }
        for registro in registros
        if (registro.get("status") or "").lower() == "aberto"
    ]
    encerradas = [
        {
            **registro,
            "hora_legivel": _formatar_data_hora(registro.get("hora")),
        }
        for registro in registros
        if (registro.get("status") or "").lower() == "encerrado"
    ][:20]

    sessao_data_label = _formatar_data_local(sessao_data) if sessao_data else ""
    return render_template(
        "historico.html",
        status_labels=list(status_counts.keys()),
        status_values=list(status_counts.values()),
        resposta_labels=list(resposta_counts.keys()),
        resposta_values=list(resposta_counts.values()),
        usuario_labels=list(usuario_counts.keys()),
        usuario_values=list(usuario_counts.values()),
        abertas=abertas,
        encerradas=encerradas,
        sessoes=sessoes,
        sessao_data=sessao_data,
        sessao_data_label=sessao_data_label,
    )


@bp.route("/painel")
def painel():
    return render_template("painel.html", video_embed=_montar_video_embed())


@bp.route("/senhas")
def senhas():
    printer_ok, printer_message = printer.printer_ready()
    return render_template(
        "senhas.html",
        printer_ok=printer_ok,
        printer_message=printer_message,
    )


@bp.route("/senhas/imprimir/<prioridade>", methods=["POST"])
def imprimir_senha(prioridade: str):
    return _emitir_e_imprimir_senha(prioridade)


@bp.route("/senhas/imprimir/teste", methods=["POST"])
def imprimir_teste():
    return _imprimir_teste()


@bp.route("/painel/status")
def painel_status():
    atual = db.obter_chamada_aberta()
    ultimas = db.listar_ultimas_encerradas(MAX_PAINEL_ULTIMAS)
    if not atual and ultimas:
        atual = ultimas[0]

    return jsonify(
        {
            "senha_atual": atual,
            "ultimas_senhas": ultimas,
        }
    )


def _formatar_data_local(valor_iso: str | None) -> str:
    """Formata data ISO armazenada no banco para exibicao local."""
    dt = _converter_para_local(valor_iso)
    return dt.strftime("%d/%m/%Y")

def _formatar_data_hora(valor_iso: str | None) -> str:
    """Formata data e hora para exibição completa."""
    dt = _converter_para_local(valor_iso)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def _extrair_data_iso(valor_iso: str | None) -> str:
    """Retorna a data YYYY-MM-DD correspondente ao registro."""
    return _converter_para_local(valor_iso).date().isoformat()


def _converter_para_local(valor_iso: str | None) -> datetime:
    """Converte uma string ISO do banco para datetime no fuso configurado."""
    if not valor_iso:
        return datetime.now(db.FUSO_HORARIO)

    try:
        dt = datetime.fromisoformat(valor_iso)
    except ValueError:
        return datetime.now(db.FUSO_HORARIO)

    if dt.tzinfo is None:
        dt = db.FUSO_HORARIO.localize(dt)
    else:
        dt = dt.astimezone(db.FUSO_HORARIO)

    return dt


def _parse_int_from_form(form, campo, default):
    """Retorna um inteiro simples do formulario com fallback."""
    raw = (form.get(campo) or str(default)).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(campo)


def _emitir_e_imprimir_senha(prioridade: str):
    prioridade = (prioridade or "").strip().lower()
    if prioridade not in PRIORIDADE_LABELS:
        return jsonify({"ok": False, "message": "Tipo de senha invalido."}), 400

    unidade = os.getenv("PAINEL_UNIDADE_PADRAO", DEFAULT_UNIDADE).strip() or DEFAULT_UNIDADE
    data_execucao = date.today().isoformat()
    numero_int = db.proximo_numero_senha(data_execucao)
    numero = f"{numero_int:03}"
    horario_local = datetime.now(db.FUSO_HORARIO)
    try:
        metadata = printer.imprimir_senha(
            numero=numero,
            tipo=PRIORIDADE_LABELS[prioridade],
            unidade=unidade,
            data_hora=horario_local,
            teste=False,
        )
        identificador = db.inserir_senha(
            numero_int,
            unidade,
            usuario="totem",
            data_execucao=datetime.strptime(data_execucao, "%Y-%m-%d").date(),
            prioridade=prioridade,
            origem="totem",
        )
        db.definir_data_producao(None)
        db.definir_origem_padrao("totem")
    except printer.PrinterError as exc:
        logger.exception("Falha ao imprimir senha %s", prioridade)
        return jsonify({"ok": False, "message": str(exc)}), 503
    except Exception:
        logger.exception("Falha inesperada ao emitir/imprimir senha %s", prioridade)
        return jsonify({"ok": False, "message": "Erro interno ao emitir a senha."}), 500

    return jsonify(
        {
            "ok": True,
            "message": f"{PRIORIDADE_LABELS[prioridade]} {numero} enviada para impressora.",
            "senha": numero,
            "prioridade": prioridade,
            "id": identificador,
            "printer_job": metadata,
        }
    )


def _imprimir_teste():
    unidade = os.getenv("PAINEL_UNIDADE_PADRAO", DEFAULT_UNIDADE).strip() or DEFAULT_UNIDADE
    agora = datetime.now(db.FUSO_HORARIO)
    try:
        metadata = printer.imprimir_senha(
            numero="000",
            tipo="Senha normal",
            unidade=unidade,
            data_hora=agora,
            teste=True,
        )
    except printer.PrinterError as exc:
        logger.exception("Falha ao imprimir teste da impressora")
        return jsonify({"ok": False, "message": str(exc)}), 503
    except Exception:
        logger.exception("Falha inesperada ao imprimir teste")
        return jsonify({"ok": False, "message": "Erro interno ao imprimir teste."}), 500

    return jsonify(
        {
            "ok": True,
            "message": "Impressao de teste enviada para a impressora.",
            "printer_job": metadata,
        }
    )


def _resolver_playlist_id(valor: str | None) -> str:
    if not valor:
        return DEFAULT_PLAYLIST_ID
    alvo = valor.strip()
    if "://" in alvo:
        parsed = urlparse(alvo)
        query = parse_qs(parsed.query)
        candidato = query.get("list", [None])[0]
        if candidato:
            return candidato
        segmentos = [seg for seg in parsed.path.split("/") if seg]
        if segmentos:
            return segmentos[-1]
        ident = parsed.path.rstrip("/").split("/")[-1]
        if ident:
            return ident
    return alvo


def _montar_video_embed() -> str:
    url = (os.getenv("PAINEL_VIDEO_URL") or "").strip()
    if url:
        lower = url.lower()
        if lower.endswith((".mp4", ".webm", ".ogg")):
            muted_flag = os.getenv("PAINEL_VIDEO_MUTED", "1") not in {"0", "false", "no", "off"}
            mute_attr = " muted" if muted_flag else ""
            return (
                '<video src="{url}" autoplay loop playsinline{mute} '
                'style="width:100%;height:100%;object-fit:cover;background:#000;" controls></video>'
            ).format(url=url, mute=mute_attr)
        return (
            '<iframe src="{url}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture; fullscreen" allowfullscreen '
            'style="width:100%;height:100%;border:0;background:#000;"></iframe>'
        ).format(url=url)

    playlist = _resolver_playlist_id(
        os.getenv("PAINEL_YT_PLAYLIST_URL")
        or os.getenv("PAINEL_YT_PLAYLIST_ID")
        or DEFAULT_PLAYLIST_ID
    )
    yt_muted_flag = os.getenv("PAINEL_YT_MUTED", "1")
    yt_muted = yt_muted_flag not in {"0", "false", "no", "off"}
    mute_param = "&mute=1" if yt_muted else "&mute=0"
    return (
        '<iframe '
        'src="https://www.youtube-nocookie.com/embed/videoseries?list={playlist}&autoplay=1&loop=1&playsinline=1&rel=0&modestbranding=1{mute}" '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen" '
        'allowfullscreen '
        'style="width:100%;height:100%;border:0;background:#000;" '
        'title="Painel - Playlist YouTube"></iframe>'
    ).format(playlist=playlist, mute=mute_param)
