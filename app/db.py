import sqlite3
from flask import current_app as app
from datetime import datetime, timedelta, time
import pytz

# Definições básicas
FUSO_HORARIO = pytz.timezone("Etc/GMT+4")
COLUNAS = (
    "id",
    "senha",
    "hora",
    "usuario",
    "resposta",
    "status",
    "terminal",
    "unidade",
    "prioridade",
    "atualizado_em",
)

def conectar():
    """Abre conexão SQLite"""
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Cria tabela se não existir"""
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS senha (
                id INTEGER PRIMARY KEY,
                senha INTEGER,
                hora TEXT,
                usuario TEXT,
                resposta TEXT,
                status TEXT,
                terminal INTEGER,
                unidade TEXT,
                prioridade TEXT,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_senha_status ON senha(status, senha)")
        conn.commit()

def senha_existe(senha_valor: int) -> bool:
    """Verifica se uma senha já existe"""
    with conectar() as conn:
        linha = conn.execute(
            "SELECT 1 FROM senha WHERE senha = ? LIMIT 1", (senha_valor,)
        ).fetchone()
    return linha is not None

def inserir_senha(numero: int, unidade: str, usuario: str = "admin", data_execucao=None) -> None:
    """Insere nova senha no banco na data informada (ou dia atual)."""
    if data_execucao is None:
        data_execucao = datetime.now().date()
    hora_base = datetime.combine(data_execucao, time.min)
    hora_local = FUSO_HORARIO.localize(hora_base + timedelta(seconds=numero))
    dados = (
        numero,
        hora_local.isoformat(),
        usuario,
        "",
        "aguardando",
        0,
        unidade,
        "normal"
    )
    with conectar() as conn:
        conn.execute("""
            INSERT INTO senha (senha, hora, usuario, resposta, status, terminal, unidade, prioridade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, dados)
        conn.commit()

def contar_senhas():
    with conectar() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM senha").fetchone()
        return total["c"] if total else 0

def listar_senhas(status: str | None = None):
    """Retorna senhas (opcionalmente filtradas por status) ordenadas pelo numero."""
    sql = "SELECT senha, unidade, hora, status FROM senha"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY senha ASC"

    with conectar() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "senha": row["senha"],
            "unidade": row["unidade"] or "UNIDADE",
            "hora": row["hora"],
            "status": row["status"],
        }
        for row in rows
    ]

def listar_ultimas_encerradas(limite: int = 8):
    """Retorna as últimas senhas encerradas."""
    with conectar() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM senha
            WHERE status = 'encerrado'
            ORDER BY atualizado_em DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
    return [dict(row) for row in rows]

def listar_sessoes_por_data():
    """Agrupa as senhas existentes por data."""
    with conectar() as conn:
        rows = conn.execute("SELECT senha, hora, status FROM senha").fetchall()

    sessoes: dict[str, dict] = {}
    for row in rows:
        data_iso = _extrair_data_iso(row["hora"])
        if not data_iso:
            continue
        sessao = sessoes.setdefault(
            data_iso,
            {
                "data": data_iso,
                "total": 0,
                "menor": None,
                "maior": None,
                "aguardando": 0,
                "aberto": 0,
                "encerradas": 0,
            },
        )
        sessao["total"] += 1
        senha_valor = row["senha"]
        if isinstance(senha_valor, int):
            if sessao["menor"] is None or senha_valor < sessao["menor"]:
                sessao["menor"] = senha_valor
            if sessao["maior"] is None or senha_valor > sessao["maior"]:
                sessao["maior"] = senha_valor
        status = (row["status"] or "").lower()
        if status == "aguardando":
            sessao["aguardando"] += 1
        elif status == "aberto":
            sessao["aberto"] += 1
        elif status == "encerrado":
            sessao["encerradas"] += 1

    return sorted(sessoes.values(), key=lambda data_item: data_item["data"], reverse=True)


def _extrair_data_iso(valor_iso: str | None) -> str | None:
    """Extrai YYYY-MM-DD sem alterar o dia original do timestamp."""
    if not valor_iso:
        return None

    if "T" in valor_iso:
        data_parte = valor_iso.split("T", 1)[0]
    elif " " in valor_iso:
        data_parte = valor_iso.split(" ", 1)[0]
    else:
        data_parte = valor_iso

    data_parte = data_parte.strip()
    if len(data_parte) >= 10:
        data_parte = data_parte[:10]

    try:
        datetime.strptime(data_parte, "%Y-%m-%d")
    except ValueError:
        return None

    return data_parte

def excluir_senhas_por_data(data_iso: str) -> int:
    """Remove todas as senhas associadas à data informada."""
    with conectar() as conn:
        cursor = conn.execute("DELETE FROM senha WHERE DATE(hora) = ?", (data_iso,))
        conn.commit()
    return cursor.rowcount

def listar_todas_senhas():
    """Retorna todas as senhas com campos principais para relatórios."""
    with conectar() as conn:
        rows = conn.execute(
            """
            SELECT id, senha, hora, usuario, resposta, status, terminal, unidade, atualizado_em
            FROM senha
            ORDER BY atualizado_em DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]

def excluir_todas_senhas():
    """Remove todas as senhas do banco."""
    with conectar() as conn:
        conn.execute("DELETE FROM senha")
        conn.commit()

def obter_chamada_aberta():
    """Retorna a primeira senha em status aberto."""
    with conectar() as conn:
        linha = conn.execute(
            "SELECT * FROM senha WHERE status = 'aberto' ORDER BY atualizado_em DESC LIMIT 1"
        ).fetchone()
    return dict(linha) if linha else None

def proxima_senha_aguardando():
    """Retorna a proxima senha aguardando."""
    with conectar() as conn:
        linha = conn.execute(
            "SELECT * FROM senha WHERE status = 'aguardando' ORDER BY senha ASC LIMIT 1"
        ).fetchone()
    return dict(linha) if linha else None

def obter_senha_por_id(identificador: int):
    """Busca uma senha especifica por ID."""
    with conectar() as conn:
        linha = conn.execute("SELECT * FROM senha WHERE id = ?", (identificador,)).fetchone()
    return dict(linha) if linha else None

def atualizar_senha(identificador: int, campos: dict):
    """Atualiza campos arbitrarios de uma senha."""
    if not campos:
        return
    colunas = ", ".join(f"{k} = ?" for k in campos.keys())
    valores = list(campos.values())
    valores.append(identificador)
    with conectar() as conn:
        conn.execute(f"UPDATE senha SET {colunas} WHERE id = ?", valores)
        conn.commit()

def encerrar_senha(identificador: int, resposta_padrao: str = "nao compareceu"):
    """Marca uma senha como encerrada."""
    atualizar_senha(
        identificador,
        {
            "status": "encerrado",
            "resposta": resposta_padrao,
            "hora": datetime.now(FUSO_HORARIO).isoformat(),
        },
    )
