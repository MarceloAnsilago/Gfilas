"""Login compartilhado por unidade e selecao do banco de atendimento."""
from contextlib import contextmanager
from pathlib import Path
import hmac
import os
import re
import secrets
import sqlite3
from threading import Lock

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .painel_events import PainelEvents

bp = Blueprint("auth", __name__)


@contextmanager
def accounts():
    # O cadastro fica no banco original; bancos das unidades nunca decidem a identidade.
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def unit_path(unit):
    original = Path(current_app.config["DB_PATH"])
    return str(original if unit["legacy"] else original.parent / (original.stem + "_unidades") / f"{unit['id']}.db")


def select_unit(unit):
    g.unidade = dict(unit)
    g.db_path = unit_path(unit)
    with current_app.extensions["unidades_lock"]:
        g.painel_events = current_app.extensions["unidades_events"].setdefault(unit["id"], PainelEvents())


def init_auth(app):
    if not app.secret_key or app.secret_key in {"supersecret", "troque-esta-chave-por-uma-nova"}:
        secret_path = Path(app.config["DB_PATH"]).with_suffix(".session_secret")
        try:
            with secret_path.open("x", encoding="ascii") as secret_file:
                secret_file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.secret_key = secret_path.read_text(encoding="ascii").strip()
    with accounts() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS unidade_login (
            id INTEGER PRIMARY KEY, nome TEXT NOT NULL, login TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL, legacy INTEGER NOT NULL DEFAULT 0,
            print_token TEXT NOT NULL UNIQUE)""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(unidade_login)")}
        if "is_admin" not in columns:
            conn.execute("ALTER TABLE unidade_login ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    app.extensions["unidades_lock"] = Lock()
    app.extensions["unidades_events"] = {}
    app.register_blueprint(bp)
    app.before_request(require_unit)
    app.after_request(private_response)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def private_response(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


def require_unit():
    if request.endpoint in {"auth.login", "static"} or request.endpoint is None:
        return None
    if request.path.startswith("/print-agent/"):
        token = (request.headers.get("X-Print-Agent-Token") or "").strip()
        if not token and request.authorization:
            token = (request.authorization.token if request.authorization.type.lower() == "bearer"
                     else request.authorization.password or request.authorization.username or "")
        with accounts() as conn:
            unit = conn.execute("SELECT * FROM unidade_login WHERE print_token = ?", (token,)).fetchone() if token else None
        if unit is None:
            return jsonify(ok=False, message="Token da unidade invalido."), 401
        select_unit(unit)
        return None
    with accounts() as conn:
        unit = conn.execute("SELECT * FROM unidade_login WHERE id = ?", (session.get("unidade_id"),)).fetchone()
    if unit is None:
        session.clear()
        if request.path.endswith(("/status", "/events")) or request.method != "GET":
            return jsonify(ok=False, message="Entre com o login da unidade."), 401
        return redirect(url_for("auth.login", next=request.full_path))
    select_unit(unit)
    if request.endpoint == "web.admin" and not unit["is_admin"]:
        return "Acesso exclusivo do administrador.", 403


def form_token():
    if "form_token" not in session:
        session["form_token"] = secrets.token_urlsafe(32)
    return session["form_token"]


def valid_form():
    return hmac.compare_digest(session.get("form_token", ""), request.form.get("form_token", "!"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not valid_form():
            flash("Atualize a pagina e tente novamente.", "warning")
        else:
            username = (request.form.get("login") or "").strip().lower()
            with accounts() as conn:
                unit = conn.execute("SELECT * FROM unidade_login WHERE login = ?", (username,)).fetchone()
            if unit and check_password_hash(unit["senha_hash"], request.form.get("senha") or ""):
                session.clear()
                session["unidade_id"] = unit["id"]
                session.permanent = True
                target = request.args.get("next", "")
                # Somente rotas locais conhecidas podem ser destino do login.
                allowed = {"/", "/chamar", "/painel", "/painel/compacto", "/gerar", "/senhas", "/historico", "/imprimir", "/admin"}
                return redirect(target if target.split("?", 1)[0] in allowed else url_for("web.admin" if unit["is_admin"] else "web.chamar"))
            flash("Login ou senha incorretos.", "warning")
    return render_template("login.html", form_token=form_token())


def admin_page():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        username = (request.form.get("login") or "").strip().lower()
        password = request.form.get("senha") or ""
        if not valid_form():
            flash("Atualize a pagina e tente novamente.", "warning")
        elif not nome or len(nome) > 100 or not re.fullmatch(r"[a-z0-9_.-]{3,50}", username) or not 6 <= len(password) <= 200:
            flash("Informe o nome, um login de 3 a 50 caracteres (letras sem acentos, numeros, ponto, hifen ou sublinhado) e uma senha de pelo menos 6 caracteres.", "warning")
        else:
            try:
                with accounts() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    first = conn.execute("SELECT 1 FROM unidade_login WHERE is_admin = 0 LIMIT 1").fetchone() is None
                    token = (os.getenv("PRINT_AGENT_TOKEN") or "").strip() if first else ""
                    cursor = conn.execute(
                        "INSERT INTO unidade_login (nome, login, senha_hash, legacy, print_token) VALUES (?, ?, ?, ?, ?)",
                        (nome, username, generate_password_hash(password), int(first), token or secrets.token_urlsafe(32)),
                    )
                    unit = conn.execute("SELECT * FROM unidade_login WHERE id = ?", (cursor.lastrowid,)).fetchone()
                administrator = dict(g.unidade)
                try:
                    select_unit(unit)
                    db.init_db()
                    db.salvar_unidade_padrao(nome)
                finally:
                    select_unit(administrator)
                flash("Unidade cadastrada com sucesso.", "success")
                return redirect(url_for("web.admin"))
            except sqlite3.IntegrityError:
                flash("Este login ja esta em uso. Escolha outro.", "warning")
    with accounts() as conn:
        unidades = [dict(row) for row in conn.execute("SELECT id, nome, login, print_token FROM unidade_login WHERE is_admin = 0 ORDER BY nome")]
    return render_template("admin.html", unidades=unidades, form_token=form_token())


@bp.post("/logout")
def logout():
    if not valid_form():
        return "Formulario expirado. Atualize a pagina.", 400
    session.clear()
    return redirect(url_for("auth.login"))


@bp.app_context_processor
def auth_context():
    return {"unidade_conectada": getattr(g, "unidade", None), "auth_form_token": form_token}
