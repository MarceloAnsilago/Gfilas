import sqlite3
from pathlib import Path
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
    "origem",
    "atualizado_em",
)

def conectar():
    """Abre conexão SQLite"""
    db_path = Path(app.config["DB_PATH"])
    db_path_str = str(db_path)
    if db_path_str and db_path_str != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
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
                data_execucao TEXT,
                usuario TEXT,
                resposta TEXT,
                status TEXT,
                terminal INTEGER,
                unidade TEXT,
                prioridade TEXT,
                origem TEXT,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS configuracao (
                chave TEXT PRIMARY KEY,
                valor TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS print_job (
                id INTEGER PRIMARY KEY,
                numero TEXT NOT NULL,
                tipo TEXT NOT NULL,
                unidade TEXT NOT NULL,
                prioridade TEXT NOT NULL,
                data_hora TEXT NOT NULL,
                teste INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                claimed_at TEXT,
                completed_at TEXT,
                last_error TEXT,
                printer_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        colunas = [row["name"] for row in conn.execute("PRAGMA table_info(senha)").fetchall()]
        if "data_execucao" not in colunas:
            conn.execute("ALTER TABLE senha ADD COLUMN data_execucao TEXT")
            conn.execute(
                """
                UPDATE senha
                SET data_execucao = substr(hora, 1, 10)
                WHERE data_execucao IS NULL OR data_execucao = ''
                """
            )
        if "origem" not in colunas:
            conn.execute("ALTER TABLE senha ADD COLUMN origem TEXT")
            conn.execute(
                """
                UPDATE senha
                SET origem = 'lote'
                WHERE origem IS NULL OR origem = ''
                """
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_senha_status ON senha(status, senha)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_senha_status_updated ON senha(status, atualizado_em DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_print_job_status_id ON print_job(status, id)")
        conn.commit()

def senha_existe(senha_valor: int, data_iso: str | None = None) -> bool:
    """Verifica se uma senha j� existe na data selecionada (se fornecida)."""
    sql = "SELECT 1 FROM senha WHERE senha = ?"
    params: list = [senha_valor]
    if data_iso:
        sql += " AND COALESCE(data_execucao, substr(hora, 1, 10)) = ?"
        params.append(data_iso)
    sql += " LIMIT 1"
    with conectar() as conn:
        linha = conn.execute(sql, tuple(params)).fetchone()
    return linha is not None

def inserir_senha(
    numero: int,
    unidade: str,
    usuario: str = "admin",
    data_execucao=None,
    prioridade: str = "normal",
    origem: str = "lote",
) -> int:
    """Insere nova senha no banco na data informada (ou dia atual)."""
    if data_execucao is None:
        data_execucao = datetime.now().date()
    hora_base = datetime.combine(data_execucao, time.min)
    hora_local = FUSO_HORARIO.localize(hora_base + timedelta(seconds=numero))
    dados = (
        numero,
        hora_local.isoformat(),
        data_execucao.isoformat(),
        usuario,
        "",
        "aguardando",
        0,
        unidade,
        prioridade,
        origem,
    )
    with conectar() as conn:
        cursor = conn.execute("""
            INSERT INTO senha (senha, hora, data_execucao, usuario, resposta, status, terminal, unidade, prioridade, origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, dados)
        conn.commit()
    return cursor.lastrowid


def proximo_numero_senha(data_iso: str | None = None) -> int:
    """Retorna o proximo numero disponivel para a data informada."""
    if not data_iso:
        data_iso = obter_data_producao_ativa()
    if not data_iso:
        data_iso = datetime.now().date().isoformat()

    with conectar() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(senha), 0) AS maior
            FROM senha
            WHERE COALESCE(data_execucao, substr(hora, 1, 10)) = ?
            """,
            (data_iso,),
        ).fetchone()

    maior = int(row["maior"]) if row and row["maior"] is not None else 0
    return maior + 1


def emitir_senha(
    unidade: str,
    prioridade: str = "normal",
    usuario: str = "totem",
    data_execucao=None,
):
    """Cria uma nova senha e retorna o registro persistido."""
    if data_execucao is None:
        data_execucao = obter_data_producao_ativa() or datetime.now().date().isoformat()
    if hasattr(data_execucao, "isoformat"):
        data_iso = data_execucao.isoformat()
    else:
        data_iso = str(data_execucao)

    numero = proximo_numero_senha(data_iso)
    identificador = inserir_senha(
        numero,
        unidade,
        usuario=usuario,
        data_execucao=datetime.strptime(data_iso, "%Y-%m-%d").date(),
        prioridade=prioridade,
        origem="totem",
    )
    return obter_senha_por_id(identificador)

def contar_senhas():
    with conectar() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM senha").fetchone()
        return total["c"] if total else 0

def listar_senhas(status: str | None = None, data_iso: str | None = None, origem: str | None = None):
    """Retorna senhas (opcionalmente filtradas por status) ordenadas pelo numero."""
    sql = """
        SELECT senha, unidade, hora, status, data_execucao, prioridade,
               COALESCE(origem, 'lote') AS origem
        FROM senha
    """
    filtros = []
    params: list = []
    if status:
        filtros.append("status = ?")
        params.append(status)
    if data_iso:
        filtros.append("COALESCE(data_execucao, substr(hora, 1, 10)) = ?")
        params.append(data_iso)
    if origem:
        filtros.append("COALESCE(origem, 'lote') = ?")
        params.append(origem)
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY senha ASC"

    with conectar() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    return [
        {
            "senha": row["senha"],
            "unidade": row["unidade"] or "UNIDADE",
            "hora": row["hora"],
            "status": row["status"],
            "data_execucao": row["data_execucao"],
            "prioridade": row["prioridade"] or "normal",
            "origem": row["origem"],
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


def obter_painel_status_snapshot(limite: int = 8):
    """Retorna senha atual e últimas encerradas usando uma única conexão."""
    with conectar() as conn:
        atual = conn.execute(
            """
            SELECT *
            FROM senha
            WHERE status = 'aberto'
            ORDER BY atualizado_em DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        ultimas = conn.execute(
            """
            SELECT *
            FROM senha
            WHERE status = 'encerrado'
            ORDER BY atualizado_em DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()

    atual_dict = dict(atual) if atual else None
    ultimas_dict = [dict(row) for row in ultimas]
    if not atual_dict and ultimas_dict:
        atual_dict = ultimas_dict[0]
    return {"senha_atual": atual_dict, "ultimas_senhas": ultimas_dict}

def listar_sessoes_por_data(origem: str | None = None):
    """Agrupa as senhas existentes por data."""
    sql = "SELECT senha, hora, status, data_execucao, origem FROM senha"
    params: tuple = ()
    if origem:
        sql += " WHERE COALESCE(origem, 'lote') = ?"
        params = (origem,)

    with conectar() as conn:
        rows = conn.execute(sql, params).fetchall()

    sessoes: dict[str, dict] = {}
    for row in rows:
        data_iso = row["data_execucao"] or _extrair_data_iso(row["hora"])
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


def obter_data_producao() -> str | None:
    """Retorna a data marcada como sessao em producao."""
    with conectar() as conn:
        row = conn.execute(
            "SELECT valor FROM configuracao WHERE chave = 'data_producao'"
        ).fetchone()
    return row["valor"] if row and row["valor"] else None


def obter_origem_padrao() -> str:
    """Retorna a origem padrao da fila ativa."""
    with conectar() as conn:
        row = conn.execute(
            "SELECT valor FROM configuracao WHERE chave = 'origem_padrao'"
        ).fetchone()
    valor = (row["valor"] if row and row["valor"] else "lote").strip().lower()
    return valor if valor in {"lote", "totem"} else "lote"


def obter_ultimo_numero_totem(prioridade: str) -> int:
    """Retorna o ultimo numero emitido pelo totem para a prioridade."""
    chave = _chave_contador_totem(prioridade)
    with conectar() as conn:
        row = conn.execute(
            "SELECT valor FROM configuracao WHERE chave = ?",
            (chave,),
        ).fetchone()
    if not row or not row["valor"]:
        return 0 if prioridade == "preferencial" else 100
    try:
        return int(str(row["valor"]).strip())
    except ValueError:
        return 0 if prioridade == "preferencial" else 100


def proximo_numero_totem(prioridade: str) -> int:
    """Calcula o proximo numero do totem conforme a faixa da prioridade."""
    prioridade = _normalizar_prioridade(prioridade)
    ultimo = obter_ultimo_numero_totem(prioridade)
    proximo = ultimo + 1
    if prioridade == "preferencial" and proximo > 100:
        raise ValueError("limite_preferencial")
    if prioridade == "normal" and proximo < 101:
        proximo = 101
    return proximo


def registrar_numero_totem(prioridade: str, numero: int) -> None:
    """Persiste o ultimo numero emitido pelo totem."""
    prioridade = _normalizar_prioridade(prioridade)
    chave = _chave_contador_totem(prioridade)
    with conectar() as conn:
        conn.execute(
            """
            INSERT INTO configuracao (chave, valor)
            VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (chave, str(int(numero))),
        )
        conn.commit()


def reiniciar_numero_totem(prioridade: str) -> None:
    """Reinicia o contador do totem para a prioridade."""
    prioridade = _normalizar_prioridade(prioridade)
    valor_base = 0 if prioridade == "preferencial" else 100
    registrar_numero_totem(prioridade, valor_base)


def contar_remanescentes_totem(prioridade: str) -> int:
    """Conta senhas do totem da mesma prioridade ainda nao encerradas na data ativa."""
    prioridade = _normalizar_prioridade(prioridade)
    with conectar() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM senha
            WHERE COALESCE(origem, 'lote') = 'totem'
              AND prioridade = ?
              AND status IN ('aguardando', 'aberto')
              AND COALESCE(data_execucao, substr(hora, 1, 10)) = (
                  SELECT COALESCE(data_execucao, substr(hora, 1, 10))
                  FROM senha
                  WHERE COALESCE(origem, 'lote') = 'totem'
                    AND prioridade = ?
                    AND status IN ('aguardando', 'aberto')
                  ORDER BY COALESCE(data_execucao, substr(hora, 1, 10)) DESC, senha ASC
                  LIMIT 1
              )
            """,
            (prioridade, prioridade),
        ).fetchone()
    return int(row["total"]) if row and row["total"] is not None else 0


def excluir_remanescentes_totem(prioridade: str) -> int:
    """Remove senhas remanescentes do totem da mesma prioridade na data ativa."""
    prioridade = _normalizar_prioridade(prioridade)
    with conectar() as conn:
        data_ref = conn.execute(
            """
            SELECT COALESCE(data_execucao, substr(hora, 1, 10)) AS data_ref
            FROM senha
            WHERE COALESCE(origem, 'lote') = 'totem'
              AND prioridade = ?
              AND status IN ('aguardando', 'aberto')
            ORDER BY data_ref DESC, senha ASC
            LIMIT 1
            """,
            (prioridade,),
        ).fetchone()
        if not data_ref or not data_ref["data_ref"]:
            return 0

        cursor = conn.execute(
            """
            DELETE FROM senha
            WHERE COALESCE(origem, 'lote') = 'totem'
              AND prioridade = ?
              AND status IN ('aguardando', 'aberto')
              AND COALESCE(data_execucao, substr(hora, 1, 10)) = ?
            """,
            (prioridade, data_ref["data_ref"]),
        )
        conn.commit()
    return cursor.rowcount


def criar_print_job(
    numero: str,
    tipo: str,
    unidade: str,
    prioridade: str,
    data_hora: str,
    teste: bool = False,
) -> int:
    """Enfileira uma nova impressao para o agente local."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO print_job (numero, tipo, unidade, prioridade, data_hora, teste, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (numero, tipo, unidade, _normalizar_prioridade(prioridade), data_hora, 1 if teste else 0),
        )
        conn.commit()
    return cursor.lastrowid


def claim_next_print_job(stale_after_seconds: int = 120):
    """Reserva o proximo job pendente para um agente."""
    agora = datetime.now(FUSO_HORARIO)
    stale_before = (agora - timedelta(seconds=stale_after_seconds)).isoformat()
    claimed_at = agora.isoformat()

    with conectar() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE print_job
            SET status = 'pending',
                claimed_at = NULL
            WHERE status = 'processing'
              AND claimed_at IS NOT NULL
              AND claimed_at < ?
            """,
            (stale_before,),
        )
        row = conn.execute(
            """
            SELECT *
            FROM print_job
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None

        conn.execute(
            """
            UPDATE print_job
            SET status = 'processing',
                claimed_at = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (claimed_at, row["id"]),
        )
        conn.commit()

    return obter_print_job(row["id"])


def obter_print_job(identificador: int):
    """Retorna um print job especifico."""
    with conectar() as conn:
        row = conn.execute("SELECT * FROM print_job WHERE id = ?", (identificador,)).fetchone()
    return dict(row) if row else None


def concluir_print_job(identificador: int, printer_info: str | None = None) -> None:
    """Marca job como concluido."""
    with conectar() as conn:
        conn.execute(
            """
            UPDATE print_job
            SET status = 'completed',
                completed_at = ?,
                printer_info = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (datetime.now(FUSO_HORARIO).isoformat(), printer_info, identificador),
        )
        conn.commit()


def falhar_print_job(identificador: int, erro: str) -> None:
    """Marca job como erro para diagnostico."""
    with conectar() as conn:
        conn.execute(
            """
            UPDATE print_job
            SET status = 'error',
                completed_at = ?,
                last_error = ?
            WHERE id = ?
            """,
            (datetime.now(FUSO_HORARIO).isoformat(), erro[:500], identificador),
        )
        conn.commit()


def definir_origem_padrao(origem: str) -> None:
    """Atualiza a origem padrao da fila ativa."""
    origem = (origem or "lote").strip().lower()
    if origem not in {"lote", "totem"}:
        origem = "lote"
    with conectar() as conn:
        conn.execute(
            """
            INSERT INTO configuracao (chave, valor)
            VALUES ('origem_padrao', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (origem,),
        )
        conn.commit()


def definir_data_producao(data_iso: str | None) -> None:
    """Atualiza a data em producao; aceita None para limpar."""
    with conectar() as conn:
        if data_iso:
            conn.execute(
                """
                INSERT INTO configuracao (chave, valor)
                VALUES ('data_producao', ?)
                ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
                """,
                (data_iso,),
            )
        else:
            conn.execute("DELETE FROM configuracao WHERE chave = 'data_producao'")
        conn.commit()


def obter_data_producao_ativa() -> str | None:
    """Retorna a data em producao explicitamente marcada nas sessoes em lote."""
    data_producao = obter_data_producao()
    sessoes = listar_sessoes_por_data(origem="lote")
    datas_validas = {sessao["data"] for sessao in sessoes if sessao.get("data")}

    if data_producao in datas_validas:
        return data_producao
    return None


def obter_fila_ativa():
    """Resolve qual origem/data deve alimentar as chamadas do atendimento."""
    origem_padrao = obter_origem_padrao()
    data_lote = obter_data_producao_ativa()
    if origem_padrao == "lote" and data_lote:
        return {"origem": "lote", "data": data_lote, "manual": True}

    data_totem = _obter_data_ativa_por_origem("totem")
    if origem_padrao == "totem" and data_totem:
        return {"origem": "totem", "data": data_totem, "manual": False}
    if origem_padrao == "totem":
        return None

    if data_lote:
        return {"origem": "lote", "data": data_lote, "manual": True}

    sessoes_lote = listar_sessoes_por_data(origem="lote")
    if sessoes_lote:
        return {"origem": "lote", "data": sessoes_lote[0]["data"], "manual": False}

    if data_totem:
        return {"origem": "totem", "data": data_totem, "manual": False}

    return None


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


def _ids_por_data(data_iso: str, filter_sql: str = "", params: tuple | list = ()) -> list[int]:
    query = "SELECT id, hora, data_execucao FROM senha"
    if filter_sql:
        query += f" WHERE {filter_sql}"

    with conectar() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        row["id"]
        for row in rows
        if (row["data_execucao"] or _extrair_data_iso(row["hora"])) == data_iso
    ]


def excluir_senhas_por_data(data_iso: str) -> int:
    """Remove todas as senhas associadas à data informada."""
    ids = _ids_por_data(data_iso)
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    sql = f"DELETE FROM senha WHERE id IN ({placeholders})"
    with conectar() as conn:
        cursor = conn.execute(sql, tuple(ids))
        conn.commit()
    if obter_data_producao() == data_iso:
        definir_data_producao(None)
    return cursor.rowcount


def encerrar_sequencia_senhas(inicio: int, final: int, data_iso: str | None = None, resposta: str = "nao compareceu") -> int:
    """Encerra um intervalo de senhas que ainda estao aguardando."""
    if not data_iso:
        return 0
    ids = _ids_por_data(
        data_iso,
        filter_sql="status = 'aguardando' AND senha BETWEEN ? AND ?",
        params=(inicio, final),
    )
    if not ids:
        return 0

    horario = datetime.now(FUSO_HORARIO).isoformat()
    placeholders = ",".join("?" for _ in ids)
    sql = f"""
        UPDATE senha
        SET status = 'encerrado',
            resposta = ?,
            hora = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders})
    """
    params = [resposta, horario] + ids

    with conectar() as conn:
        cursor = conn.execute(sql, tuple(params))
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
    fila = obter_fila_ativa()
    if not fila:
        return None

    with conectar() as conn:
        linha = conn.execute(
            """
            SELECT *
            FROM senha
            WHERE status = 'aguardando'
              AND COALESCE(data_execucao, substr(hora, 1, 10)) = ?
              AND COALESCE(origem, 'lote') = ?
            ORDER BY senha ASC
            LIMIT 1
            """,
            (fila["data"], fila["origem"]),
        ).fetchone()
    return dict(linha) if linha else None


def _obter_data_ativa_por_origem(origem: str) -> str | None:
    """Retorna a data mais recente com senha pendente na origem informada."""
    with conectar() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(data_execucao, substr(hora, 1, 10)) AS data_ref
            FROM senha
            WHERE status = 'aguardando'
              AND COALESCE(origem, 'lote') = ?
            ORDER BY data_ref DESC, senha ASC
            LIMIT 1
            """,
            (origem,),
        ).fetchone()
    return row["data_ref"] if row and row["data_ref"] else None


def _normalizar_prioridade(prioridade: str) -> str:
    return "preferencial" if (prioridade or "").strip().lower() == "preferencial" else "normal"


def _chave_contador_totem(prioridade: str) -> str:
    prioridade = _normalizar_prioridade(prioridade)
    return f"contador_totem_{prioridade}"

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
