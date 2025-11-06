from datetime import date, datetime
from collections import Counter
import os
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for, session, jsonify

from . import db

DEFAULT_UNIDADE = "UNIDADE"
DEFAULT_USUARIO = "admin"
DEFAULT_PLAYLIST_ID = "PLrBhE4oLMMj95y5nobzQgDT8ygY-Pqbk3"
MAX_PAINEL_ULTIMAS = int(os.getenv("PAINEL_MAX_ULTIMAS", "8"))

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
    proxima_senha = db.proxima_senha_aguardando()
    aguardando = db.listar_senhas(status="aguardando")

    return render_template(
        "chamar.html",
        usuario=usuario,
        terminal=terminal,
        chamada_aberta=chamada_aberta,
        proxima_senha=proxima_senha,
        total_aguardando=len(aguardando),
    )

@bp.route("/gerar", methods=["GET", "POST"])
def gerar_senhas():
    if request.method == "POST":
        unidade = request.form.get("unidade", DEFAULT_UNIDADE).strip() or DEFAULT_UNIDADE
        senha_inicial = int(request.form.get("senha_inicial", 1))
        senha_final = int(request.form.get("senha_final", 50))
        data_str = request.form.get("data_execucao") or date.today().isoformat()

        try:
            data_escolhida = datetime.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Aviso: informe uma data valida.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        if senha_final < senha_inicial:
            flash("Aviso: a senha final deve ser maior ou igual a inicial.", "warning")
            return redirect(url_for("web.gerar_senhas"))

        inseridas, duplicadas = 0, 0
        for numero in range(senha_inicial, senha_final + 1):
            if db.senha_existe(numero):
                duplicadas += 1
                continue
            db.inserir_senha(numero, unidade, data_execucao=data_escolhida)
            inseridas += 1

        if inseridas:
            flash(f"Sucesso: {inseridas} senhas geradas com sucesso!", "success")
        if duplicadas:
            flash(f"Info: {duplicadas} senhas ja existiam.", "info")

        return redirect(url_for("web.gerar_senhas"))

    total_senhas = db.contar_senhas()
    data_padrao = date.today().isoformat()
    return render_template("gerar.html", total_senhas=total_senhas, data_padrao=data_padrao)


@bp.route("/imprimir", methods=["GET"])
def imprimir():
    todas_senhas = db.listar_senhas(status="aguardando")

    datas_disponiveis = sorted(
        {_extrair_data_iso(item.get("hora")) for item in todas_senhas if item.get("hora")}
    )
    datas_fmt = [
        {"valor": valor, "label": datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")}
        for valor in datas_disponiveis
    ]

    data_selecionada = request.args.get("data")
    if data_selecionada not in datas_disponiveis:
        data_selecionada = datas_disponiveis[-1] if datas_disponiveis else None

    if data_selecionada:
        senhas_raw = [
            item for item in todas_senhas if _extrair_data_iso(item.get("hora")) == data_selecionada
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

    confirmando_exclusao = request.args.get("confirmar_exclusao") == "1" and bool(datas_disponiveis)
    datas_legiveis = [item["label"] for item in datas_fmt]

    return render_template(
        "imprimir.html",
        titulo=titulo,
        senhas=senhas,
        datas_disponiveis=datas_fmt,
        data_selecionada=data_selecionada,
        confirmando_exclusao=confirmando_exclusao,
        datas_legiveis=datas_legiveis,
    )


@bp.route("/imprimir/excluir", methods=["POST"])
def excluir_todas_senhas():
    db.excluir_todas_senhas()
    flash("Todas as senhas foram excluidas do banco.", "success")
    return redirect(url_for("web.imprimir"))


@bp.route("/historico", methods=["GET", "POST"])
def historico():
    registros = db.listar_todas_senhas()

    if request.method == "POST":
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

        db.encerrar_senha(encerrar_id)
        flash("Senha encerrada como nao compareceu.", "success")
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
    )


@bp.route("/painel")
def painel():
    return render_template("painel.html", video_embed=_montar_video_embed())


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
