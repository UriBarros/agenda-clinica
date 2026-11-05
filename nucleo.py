"""Núcleo do agenda-clinica: banco SQLite e as regras da agenda.

Só biblioteca padrão. Nenhuma regra de horário mora fora deste arquivo: o site,
a API REST e o MCP chamam as mesmas funções (ver ops.py), então não há três
versões da mesma regra para divergir.

Convenções: datas "AAAA-MM-DD", horas em minutos desde a meia-noite (inteiro),
dias da semana 0=domingo..6=sábado, tudo no fuso da clínica. Dinheiro em centavos.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

LIMITES = {"profissionais": 30, "locais": 20, "servicos": 60, "chaves": 10,
           "futuros_por_telefone": 5, "horizonte_dias": 120, "janela_consulta_dias": 14,
           # Teto de linhas por resposta de horários: sem ele, uma clínica de 30 profissionais 24 h devolvia ~7 MB por chamada.
           "linhas_horarios": 300, "anonimos_por_clinica_hora": 60, "clinicas_novas_por_dia": 100}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
RESERVADOS = {"api", "admin", "painel", "mcp", "docs", "entrar", "sair", "criar", "health", "demo-admin"}


class Erro(Exception):
    """Erro de regra, com status HTTP e código estável para o agente decidir o que fazer."""

    def __init__(self, status: int, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.status, self.codigo, self.mensagem = status, codigo, mensagem


SCHEMA = """
create table if not exists clinicas(id integer primary key, slug text unique not null, nome text not null,
  descricao text default '', telefone text default '', email text default '', cidade text default '',
  tz text default 'America/Sao_Paulo', passo_min integer default 30, antecedencia_min integer default 120, criado text,
  listada integer default 1);
create table if not exists locais(id integer primary key, clinica_id integer not null references clinicas(id),
  nome text not null, endereco text default '', cidade text default '', ativo integer default 1);
create table if not exists profissionais(id integer primary key, clinica_id integer not null references clinicas(id),
  nome text not null, especialidade text default '', registro text default '', bio text default '', ativo integer default 1);
create table if not exists servicos(id integer primary key, clinica_id integer not null references clinicas(id),
  nome text not null, duracao_min integer not null, preco_centavos integer, ativo integer default 1);
create table if not exists disponibilidade(id integer primary key, profissional_id integer not null references profissionais(id),
  local_id integer not null references locais(id), dia integer not null, inicio integer not null, fim integer not null);
create table if not exists bloqueios(id integer primary key, clinica_id integer not null references clinicas(id),
  profissional_id integer references profissionais(id), inicio text not null, fim text not null, motivo text default '', criado text);
create table if not exists agendamentos(id integer primary key, clinica_id integer not null references clinicas(id),
  profissional_id integer not null references profissionais(id), local_id integer not null references locais(id),
  servico_id integer not null references servicos(id), paciente_nome text not null, paciente_tel text not null,
  paciente_email text default '', data text not null, inicio integer not null, fim integer not null,
  status text not null default 'confirmado', cancelado_por text, codigo text unique not null, origem text default 'web',
  criado text, atualizado text);
create index if not exists ag_prof_data on agendamentos(profissional_id, data);
create index if not exists ag_clin_data on agendamentos(clinica_id, data);
create table if not exists eventos(id integer primary key, agendamento_id integer not null, quando text, tipo text, detalhe text);
create table if not exists usuarios(id integer primary key, clinica_id integer not null references clinicas(id),
  email text unique not null, senha text not null, criado text);
create table if not exists sessoes(hash text primary key, usuario_id integer not null references usuarios(id), expira text not null);
create table if not exists chaves(id integer primary key, clinica_id integer not null references clinicas(id),
  nome text not null, prefixo text not null, hash text unique not null, escopo text not null, criado text,
  ultimo_uso text, revogada integer default 0);
"""


class Banco:
    """SQLite em WAL. Conexão por operação (barata neste porte); escrita serializada por trava + BEGIN IMMEDIATE."""

    def __init__(self, pasta: str | Path):
        self.caminho = Path(pasta) / "agenda.db"
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._trava = threading.Lock()
        con = self._con()
        con.executescript(SCHEMA)
        # Banco criado antes da coluna `listada` (produção de 05/11): acrescenta sem perder dado. Padrão 1 = indexável
        # (decisão do dono em 05/11: "indexa tudo"); o operador tira uma clínica específica com `app.py delistar`.
        if "listada" not in {r["name"] for r in con.execute("pragma table_info(clinicas)")}:
            con.execute("alter table clinicas add column listada integer default 1")
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.caminho, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("pragma journal_mode=wal")
        con.execute("pragma foreign_keys=on")
        return con

    @contextmanager
    def escrita(self):
        with self._trava:
            con = self._con()
            con.execute("begin immediate")
            try:
                yield con
                con.execute("commit")
            except BaseException:
                con.execute("rollback")
                raise
            finally:
                con.close()

    def ler(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        con = self._con()
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def um(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        r = self.ler(sql, args)
        return r[0] if r else None

    def copia_segura(self, destino: str | Path) -> None:
        """Cópia consistente (VACUUM INTO) para backup, sem parar o serviço."""
        con = self._con()
        try:
            con.execute("vacuum into ?", (str(destino),))
        finally:
            con.close()


class Limitador:
    """Janela deslizante em memória, por (balde, chave). Um processo só: o limite é por réplica."""

    TETO = 20000

    def __init__(self):
        import collections
        self._t: dict = collections.defaultdict(collections.deque)
        self._trava = threading.Lock()

    def passa(self, balde: str, quem: str, maximo: int, janela_s: int, agora: float | None = None) -> bool:
        import time
        agora = time.monotonic() if agora is None else agora
        with self._trava:
            q = self._t[(balde, quem)]
            while q and q[0] <= agora - janela_s:
                q.popleft()
            if len(q) >= maximo:
                return False
            q.append(agora)
            if len(self._t) > self.TETO:
                # Poda dura: primeiro o que já expirou; se ainda estourar, descarta os mais antigos até a metade.
                # Sem isto, um atacante com muitas chaves distintas fazia cada requisição varrer a tabela inteira.
                for k in [k for k, v in self._t.items() if not v or v[-1] <= agora - 3600]:
                    self._t.pop(k, None)
                if len(self._t) > self.TETO:
                    for k, _ in sorted(self._t.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)[: len(self._t) - self.TETO // 2]:
                        self._t.pop(k, None)
            return True


# ------------------------------------------------------------------ tempo

def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def minutos(h: str) -> int:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(h or "").strip())
    if not m:
        raise Erro(422, "hora_invalida", f"hora {h!r} fora do formato HH:MM")
    return int(m[1]) * 60 + int(m[2])


def data_valida(s: Any) -> dt.date:
    try:
        return dt.date.fromisoformat(str(s))
    except ValueError:
        raise Erro(422, "data_invalida", f"data {s!r} fora do formato AAAA-MM-DD") from None


def dia_semana(d: dt.date) -> int:
    return (d.weekday() + 1) % 7


def agora_local(tz: str, utc: dt.datetime | None = None) -> tuple[dt.date, int]:
    """(data, minutos) de agora no fuso da clínica. Sem tzdata no sistema, cai em UTC-3 (Brasil, sem horário de verão desde 2019)."""
    utc = utc or dt.datetime.now(dt.timezone.utc)
    try:
        loc = utc.astimezone(ZoneInfo(tz))  # type: ignore[misc]
    except Exception:
        loc = utc.astimezone(dt.timezone(dt.timedelta(hours=-3)))
    return loc.date(), loc.hour * 60 + loc.minute


def _agora_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ senha, sessão, chave

def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${sal.hex()}${h.hex()}"


def confere_senha(senha: str, guardado: str) -> bool:
    try:
        _, sal, h = guardado.split("$")
        novo = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(novo.hex(), h)
    except ValueError:
        return False


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def criar_clinica(bd: Banco, nome: str, email: str, senha: str, slug: str = "") -> dict:
    nome, email = str(nome or "").strip()[:100], str(email or "").strip().lower()[:120]
    if not nome:
        raise Erro(422, "nome_obrigatorio", "informe o nome da clínica")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise Erro(422, "email_invalido", "e-mail inválido")
    if len(str(senha or "")) < 10:
        raise Erro(422, "senha_curta", "a senha precisa ter pelo menos 10 caracteres")
    base = slug or re.sub(r"[^a-z0-9]+", "-", _sem_acento(nome).lower()).strip("-")[:38]
    if not SLUG.match(base or "") or base in RESERVADOS:
        raise Erro(422, "slug_invalido", "endereço da clínica inválido (use letras, números e hífen, 3 a 40 caracteres)")
    with bd.escrita() as con:
        if con.execute("select 1 from usuarios where email=?", (email,)).fetchone():
            raise Erro(409, "email_em_uso", "já existe uma conta com este e-mail")
        final = base
        while con.execute("select 1 from clinicas where slug=?", (final,)).fetchone():
            final = f"{base[:33]}-{secrets.token_hex(2)}"
        # O e-mail de login NÃO é copiado para o contato público (a clínica preenche o dela no painel).
        cid = con.execute("insert into clinicas(slug,nome,email,criado) values(?,?,?,?)", (final, nome, "", _agora_iso())).lastrowid
        con.execute("insert into usuarios(clinica_id,email,senha,criado) values(?,?,?,?)", (cid, email, hash_senha(senha), _agora_iso()))
    return dict(bd.um("select * from clinicas where id=?", (cid,)))


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def entrar(bd: Banco, email: str, senha: str) -> str:
    u = bd.um("select * from usuarios where email=?", (str(email or "").strip().lower(),))
    # Mesmo custo de scrypt com usuário inexistente: não revela quais e-mails têm conta.
    ok = confere_senha(str(senha or ""), u["senha"] if u else "scrypt$00$00")
    if not (u and ok):
        raise Erro(401, "credenciais", "e-mail ou senha incorretos")
    token = secrets.token_urlsafe(32)
    expira = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with bd.escrita() as con:
        con.execute("delete from sessoes where expira<?", (_agora_iso(),))
        con.execute("insert into sessoes(hash,usuario_id,expira) values(?,?,?)", (_sha(token), u["id"], expira))
    return token


def purgar_sessoes(bd: Banco) -> None:
    with bd.escrita() as con:
        con.execute("delete from sessoes where expira<?", (_agora_iso(),))


def sair(bd: Banco, token: str) -> None:
    with bd.escrita() as con:
        con.execute("delete from sessoes where hash=?", (_sha(token),))


def clinica_da_sessao(bd: Banco, token: str) -> sqlite3.Row | None:
    if not token:
        return None
    return bd.um("select c.* from sessoes s join usuarios u on u.id=s.usuario_id join clinicas c on c.id=u.clinica_id "
                 "where s.hash=? and s.expira>?", (_sha(token), _agora_iso()))


def csrf_de(token: str) -> str:
    return hmac.new(token.encode(), b"csrf", hashlib.sha256).hexdigest()[:32]


def criar_chave(bd: Banco, clinica_id: int, nome: str, escopo: str) -> dict:
    if escopo not in ("leitura", "escrita"):
        raise Erro(422, "escopo_invalido", "escopo deve ser 'leitura' ou 'escrita'")
    nome = str(nome or "").strip()[:60] or "agente"
    with bd.escrita() as con:
        if con.execute("select count(*) from chaves where clinica_id=? and revogada=0", (clinica_id,)).fetchone()[0] >= LIMITES["chaves"]:
            raise Erro(409, "limite", f"no máximo {LIMITES['chaves']} chaves ativas")
        prefixo = secrets.token_hex(4)
        texto = f"ac_{prefixo}_{secrets.token_urlsafe(28)}"
        con.execute("insert into chaves(clinica_id,nome,prefixo,hash,escopo,criado) values(?,?,?,?,?,?)",
                    (clinica_id, nome, prefixo, _sha(texto), escopo, _agora_iso()))
    return {"chave": texto, "prefixo": prefixo, "escopo": escopo, "nome": nome,
            "aviso": "guarde agora: a chave não é mostrada de novo"}


def autenticar_chave(bd: Banco, texto: str) -> tuple[sqlite3.Row, str] | None:
    if not texto.startswith("ac_"):
        return None
    r = bd.um("select c.*, k.escopo as escopo_chave, k.id as chave_id from chaves k join clinicas c on c.id=k.clinica_id "
              "where k.hash=? and k.revogada=0", (_sha(texto),))
    if not r:
        return None
    with bd.escrita() as con:
        con.execute("update chaves set ultimo_uso=? where id=?", (_agora_iso(), r["chave_id"]))
    return r, r["escopo_chave"]


def revogar_chave(bd: Banco, clinica_id: int, chave_id: int) -> None:
    with bd.escrita() as con:
        con.execute("update chaves set revogada=1 where id=? and clinica_id=?", (chave_id, clinica_id))


def listar_chaves(bd: Banco, clinica_id: int) -> list[dict]:
    return [dict(r) for r in bd.ler("select id,nome,prefixo,escopo,criado,ultimo_uso from chaves where clinica_id=? and revogada=0 order by id", (clinica_id,))]


# ------------------------------------------------------------------ cadastro (clínica, locais, equipe, serviços)

def clinica_por_slug(bd: Banco, slug: str) -> sqlite3.Row:
    c = bd.um("select * from clinicas where slug=?", (str(slug or "").lower(),))
    if not c:
        raise Erro(404, "clinica_nao_encontrada", f"não existe clínica com o endereço {slug!r}")
    return c


def salvar_clinica(bd: Banco, c: sqlite3.Row, campos: dict) -> None:
    passo = int(campos.get("passo_min") or c["passo_min"])
    ant = int(campos.get("antecedencia_min") if campos.get("antecedencia_min") not in (None, "") else c["antecedencia_min"])
    if passo not in (10, 15, 20, 30, 45, 60) or not 0 <= ant <= 10080:
        raise Erro(422, "config_invalida", "passo deve ser 10/15/20/30/45/60 min e antecedência de 0 a 10080 min")
    tz = str(campos.get("tz") or c["tz"])
    try:
        ZoneInfo(tz)  # type: ignore[misc]
    except Exception:
        if tz != "America/Sao_Paulo":
            raise Erro(422, "fuso_invalido", f"fuso {tz!r} desconhecido") from None
    pegar = lambda k: str(campos.get(k) if campos.get(k) is not None else c[k])[:500]
    with bd.escrita() as con:
        con.execute("update clinicas set nome=?,descricao=?,telefone=?,email=?,cidade=?,tz=?,passo_min=?,antecedencia_min=? where id=?",
                    (pegar("nome")[:100] or c["nome"], pegar("descricao"), pegar("telefone")[:30], pegar("email")[:120],
                     pegar("cidade")[:80], tz, passo, ant, c["id"]))


def _salvar(bd: Banco, tabela: str, cid: int, campos: dict, colunas: dict[str, Any], limite: str, obrigatorio: str) -> int:
    """Insere ou atualiza (id presente) uma linha da clínica `cid`. `colunas`: nome -> função de limpeza."""
    try:
        valores = {k: f(campos[k]) for k, f in colunas.items() if k in campos}
        item_id = int(campos["id"]) if campos.get("id") else 0
    except (ValueError, TypeError, OverflowError):
        raise Erro(422, "valor_invalido", "algum campo tem valor inválido (número esperado?)") from None
    if not item_id and not valores.get(obrigatorio):
        raise Erro(422, f"{obrigatorio}_obrigatorio", f"informe {obrigatorio}")
    with bd.escrita() as con:
        if item_id:
            if not con.execute(f"select 1 from {tabela} where id=? and clinica_id=?", (item_id, cid)).fetchone():
                raise Erro(404, "nao_encontrado", f"{tabela[:-1]} {item_id} não existe nesta clínica")
            if valores:
                con.execute(f"update {tabela} set " + ",".join(f"{k}=?" for k in valores) + " where id=?", (*valores.values(), item_id))
            return item_id
        if con.execute(f"select count(*) from {tabela} where clinica_id=? and ativo=1", (cid,)).fetchone()[0] >= LIMITES[limite]:
            raise Erro(409, "limite", f"no máximo {LIMITES[limite]} {limite} por clínica")
        valores["clinica_id"] = cid
        return con.execute(f"insert into {tabela}({','.join(valores)}) values({','.join('?' * len(valores))})", tuple(valores.values())).lastrowid


_txt = lambda n: (lambda v: str(v or "").strip()[:n])
_ativo = lambda v: 0 if str(v).lower() in ("0", "false", "nao", "não") else 1


def salvar_local(bd, cid, c):
    return _salvar(bd, "locais", cid, c, {"nome": _txt(80), "endereco": _txt(200), "cidade": _txt(80), "ativo": _ativo}, "locais", "nome")


def salvar_profissional(bd, cid, c):
    return _salvar(bd, "profissionais", cid, c, {"nome": _txt(100), "especialidade": _txt(100), "registro": _txt(40),
                                                 "bio": _txt(600), "ativo": _ativo}, "profissionais", "nome")


def _duracao(v):
    d = int(v)
    if not 5 <= d <= 480:
        raise Erro(422, "duracao_invalida", "duração entre 5 e 480 minutos")
    return d


def _preco(v):
    if v in (None, ""):
        return None
    p = int(v)
    if p < 0:
        raise Erro(422, "preco_invalido", "preço não pode ser negativo (centavos)")
    return p


def salvar_servico(bd, cid, c):
    return _salvar(bd, "servicos", cid, c, {"nome": _txt(100), "duracao_min": _duracao, "preco_centavos": _preco, "ativo": _ativo}, "servicos", "nome")


def definir_disponibilidade(bd: Banco, cid: int, profissional_id: int, janelas: list[dict]) -> list[dict]:
    """Substitui TODA a disponibilidade semanal do profissional. janela: {dia 0-6, inicio 'HH:MM', fim 'HH:MM', local_id}."""
    if not isinstance(janelas, list) or len(janelas) > 70:
        raise Erro(422, "janelas_invalidas", "janelas deve ser uma lista com até 70 itens")
    limpas = []
    for j in janelas:
        try:
            dia = int(j.get("dia", -1))
            ini, fim = minutos(j.get("inicio")), minutos(j.get("fim"))
            loc = int(j.get("local_id", 0))
        except (ValueError, TypeError, OverflowError, AttributeError):
            raise Erro(422, "janela_invalida", "cada janela deve ser {dia, inicio, fim, local_id} com valores válidos") from None
        if not 0 <= dia <= 6 or fim <= ini:
            raise Erro(422, "janela_invalida", f"janela inválida: {j}")
        limpas.append((dia, ini, fim, loc))
    por_dia: dict[int, list] = {}
    for dia, ini, fim, loc in sorted(limpas):
        for (i2, f2) in por_dia.get(dia, []):
            if ini < f2 and fim > i2:
                raise Erro(422, "janelas_sobrepostas", f"duas faixas se sobrepõem no dia {dia}")
        por_dia.setdefault(dia, []).append((ini, fim))
    with bd.escrita() as con:
        if not con.execute("select 1 from profissionais where id=? and clinica_id=?", (profissional_id, cid)).fetchone():
            raise Erro(404, "profissional_nao_encontrado", f"profissional {profissional_id} não existe nesta clínica")
        for _, _, _, loc in limpas:
            if not con.execute("select 1 from locais where id=? and clinica_id=? and ativo=1", (loc, cid)).fetchone():
                raise Erro(404, "local_nao_encontrado", f"local {loc} não existe nesta clínica")
        con.execute("delete from disponibilidade where profissional_id=?", (profissional_id,))
        con.executemany("insert into disponibilidade(profissional_id,local_id,dia,inicio,fim) values(?,?,?,?,?)",
                        [(profissional_id, loc, dia, ini, fim) for dia, ini, fim, loc in limpas])
    return disponibilidade_de(bd, profissional_id)


def disponibilidade_de(bd: Banco, profissional_id: int) -> list[dict]:
    return [{"dia": r["dia"], "inicio": hhmm(r["inicio"]), "fim": hhmm(r["fim"]), "local_id": r["local_id"]}
            for r in bd.ler("select * from disponibilidade where profissional_id=? order by dia, inicio", (profissional_id,))]


def info_publica(bd: Banco, c: sqlite3.Row) -> dict:
    """O que o site e o agente precisam para montar a escolha. Sem dado de paciente."""
    profs = []
    for p in bd.ler("select * from profissionais where clinica_id=? and ativo=1 order by nome", (c["id"],)):
        profs.append({"id": p["id"], "nome": p["nome"], "especialidade": p["especialidade"], "registro": p["registro"],
                      "bio": p["bio"], "disponibilidade": disponibilidade_de(bd, p["id"])})
    return {"clinica": {**{k: c[k] for k in ("slug", "nome", "descricao", "telefone", "email", "cidade", "tz", "passo_min", "antecedencia_min")},
                        "indexavel": bool(c["listada"])},
            "locais": [{k: r[k] for k in ("id", "nome", "endereco", "cidade")} for r in bd.ler("select * from locais where clinica_id=? and ativo=1 order by nome", (c["id"],))],
            "profissionais": profs,
            "servicos": [{"id": r["id"], "nome": r["nome"], "duracao_min": r["duracao_min"], "preco_centavos": r["preco_centavos"]}
                         for r in bd.ler("select * from servicos where clinica_id=? and ativo=1 order by nome", (c["id"],))]}


# ------------------------------------------------------------------ horários

def _ocupacao(con: sqlite3.Connection, prof: int, d: dt.date, ignorar: int | None) -> list[tuple[int, int]]:
    """Intervalos (min) em que o profissional está ocupado no dia: consultas confirmadas e bloqueios (dele ou da clínica toda)."""
    iso = d.isoformat()
    ocupados = [(r[0], r[1]) for r in con.execute(
        "select inicio,fim from agendamentos where profissional_id=? and data=? and status='confirmado' and id is not ?", (prof, iso, ignorar))]
    clin = con.execute("select clinica_id from profissionais where id=?", (prof,)).fetchone()[0]
    for b in con.execute("select inicio,fim from bloqueios where clinica_id=? and (profissional_id is null or profissional_id=?)", (clin, prof)):
        bi, bf = b[0], b[1]
        if bi[:10] <= iso <= bf[:10]:
            ocupados.append((minutos(bi[11:16]) if bi[:10] == iso else 0, minutos(bf[11:16]) if bf[:10] == iso else 1440))
    return ocupados


def _livres_dia(con: sqlite3.Connection, c: sqlite3.Row, prof: int, dur: int, d: dt.date, local: int | None = None,
                ignorar: int | None = None, agora: tuple[dt.date, int] | None = None) -> list[dict]:
    hoje, min_hoje = agora or agora_local(c["tz"])
    if d < hoje or d > hoje + dt.timedelta(days=LIMITES["horizonte_dias"]):
        return []
    ocupados = _ocupacao(con, prof, d, ignorar)
    saida = []
    for w in con.execute("select local_id,inicio,fim from disponibilidade where profissional_id=? and dia=? order by inicio", (prof, dia_semana(d))):
        if local is not None and w["local_id"] != local:
            continue
        if not con.execute("select 1 from locais where id=? and ativo=1", (w["local_id"],)).fetchone():
            continue
        t = w["inicio"]
        while t + dur <= w["fim"]:
            # Minutos desde agora até o início da consulta (vale para qualquer dia, não só hoje).
            passou = (d - hoje).days * 1440 + t < min_hoje + c["antecedencia_min"]
            if not passou and not any(t < b and t + dur > a for a, b in ocupados):
                saida.append({"hora": hhmm(t), "local_id": w["local_id"]})
            t += c["passo_min"]
    return saida


def horarios_livres(bd: Banco, c: sqlite3.Row, servico_id: int, profissional_id: int | None, de: str, ate: str | None = None,
                    local_id: int | None = None, limite: int = 600) -> list[dict]:
    """Horários livres ordenados. Para ao juntar `limite` linhas: quem chama pede limite+1 para saber se cortou."""
    ini = data_valida(de)
    fim = data_valida(ate) if ate else ini
    if fim < ini or (fim - ini).days >= LIMITES["janela_consulta_dias"]:
        raise Erro(422, "janela_invalida", f"consulte no máximo {LIMITES['janela_consulta_dias']} dias por vez (de <= ate)")
    s = bd.um("select * from servicos where id=? and clinica_id=? and ativo=1", (servico_id, c["id"]))
    if not s:
        raise Erro(404, "servico_nao_encontrado", f"serviço {servico_id} não existe nesta clínica")
    profs = bd.ler("select * from profissionais where clinica_id=? and ativo=1 and (? is null or id=?) order by nome", (c["id"], profissional_id, profissional_id))
    if profissional_id and not profs:
        raise Erro(404, "profissional_nao_encontrado", f"profissional {profissional_id} não existe nesta clínica")
    agora = agora_local(c["tz"])
    con = bd._con()
    try:
        saida, d = [], ini
        while d <= fim and len(saida) < limite:
            for p in profs:
                for h in _livres_dia(con, c, p["id"], s["duracao_min"], d, local_id, agora=agora):
                    saida.append({"data": d.isoformat(), "hora": h["hora"], "profissional_id": p["id"], "local_id": h["local_id"]})
                if len(saida) >= limite:
                    break
            d += dt.timedelta(days=1)
    finally:
        con.close()
    return sorted(saida, key=lambda x: (x["data"], x["hora"], x["profissional_id"]))


# ------------------------------------------------------------------ agendamentos

def _ag_dict(bd: Banco, r: sqlite3.Row, com_paciente: bool = True) -> dict:
    d = {"id": r["id"], "codigo": r["codigo"], "status": r["status"], "data": r["data"], "hora": hhmm(r["inicio"]), "fim": hhmm(r["fim"]),
         "profissional_id": r["profissional_id"], "local_id": r["local_id"], "servico_id": r["servico_id"], "origem": r["origem"]}
    for chave, tabela, col in (("profissional", "profissionais", "nome"), ("local", "locais", "nome"), ("servico", "servicos", "nome")):
        x = bd.um(f"select {col} from {tabela} where id=?", (r[chave + "_id"],))
        d[chave] = x[0] if x else ""
    loc = bd.um("select endereco from locais where id=?", (r["local_id"],))
    d["endereco"] = loc[0] if loc else ""
    if com_paciente:
        d.update({"paciente_nome": r["paciente_nome"], "paciente_telefone": r["paciente_tel"], "paciente_email": r["paciente_email"]})
    if r["status"] == "cancelado":
        d["cancelado_por"] = r["cancelado_por"]
    return d


def agendar(bd: Banco, c: sqlite3.Row, servico_id: int, profissional_id: int, data: str, hora: str, nome: str, telefone: str,
            email: str = "", origem: str = "web", consentimento: bool = False) -> dict:
    nome, tel, email = str(nome or "").strip()[:100], re.sub(r"\D", "", str(telefone or ""))[:13], str(email or "").strip()[:120]
    if not consentimento:
        raise Erro(422, "consentimento", "é preciso consentir com o uso do nome e telefone para o agendamento (LGPD)")
    if not nome or len(tel) < 10:
        raise Erro(422, "dados_paciente", "informe nome e telefone com DDD")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise Erro(422, "email_invalido", "e-mail inválido")
    d, ini = data_valida(data), minutos(hora)
    s = bd.um("select * from servicos where id=? and clinica_id=? and ativo=1", (servico_id, c["id"]))
    p = bd.um("select * from profissionais where id=? and clinica_id=? and ativo=1", (profissional_id, c["id"]))
    if not s or not p:
        raise Erro(404, "nao_encontrado", "serviço ou profissional não existe nesta clínica")
    with bd.escrita() as con:
        # A checagem de choque e o insert estão na MESMA transação imediata: dois pedidos
        # simultâneos para o mesmo horário não passam os dois.
        livres = _livres_dia(con, c, p["id"], s["duracao_min"], d)
        alvo = next((h for h in livres if h["hora"] == hhmm(ini)), None)
        if not alvo:
            raise Erro(409, "horario_indisponivel", "esse horário não está mais livre; consulte os horários de novo")
        futuros = con.execute("select count(*) from agendamentos where clinica_id=? and paciente_tel=? and status='confirmado' and data>=?",
                              (c["id"], tel, agora_local(c["tz"])[0].isoformat())).fetchone()[0]
        if futuros >= LIMITES["futuros_por_telefone"]:
            raise Erro(429, "limite_paciente", f"este telefone já tem {futuros} consultas futuras; cancele uma antes")
        codigo = secrets.token_urlsafe(12)
        aid = con.execute("insert into agendamentos(clinica_id,profissional_id,local_id,servico_id,paciente_nome,paciente_tel,paciente_email,"
                          "data,inicio,fim,codigo,origem,criado,atualizado) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (c["id"], p["id"], alvo["local_id"], s["id"], nome, tel, email, d.isoformat(), ini, ini + s["duracao_min"],
                           codigo, origem, _agora_iso(), _agora_iso())).lastrowid
        con.execute("insert into eventos(agendamento_id,quando,tipo,detalhe) values(?,?,?,?)", (aid, _agora_iso(), "criado", origem))
    return _ag_dict(bd, bd.um("select * from agendamentos where id=?", (aid,)))


def agendamento_por_codigo(bd: Banco, codigo: str) -> tuple[sqlite3.Row, sqlite3.Row]:
    r = bd.um("select * from agendamentos where codigo=?", (str(codigo or ""),))
    if not r:
        raise Erro(404, "agendamento_nao_encontrado", "código de agendamento desconhecido")
    return r, bd.um("select * from clinicas where id=?", (r["clinica_id"],))


def agendamento_da_clinica(bd: Banco, c: sqlite3.Row, ag_id: int) -> sqlite3.Row:
    r = bd.um("select * from agendamentos where id=? and clinica_id=?", (int(ag_id), c["id"]))
    if not r:
        raise Erro(404, "agendamento_nao_encontrado", f"agendamento {ag_id} não existe nesta clínica")
    return r


def cancelar(bd: Banco, r: sqlite3.Row, por: str) -> dict:
    if r["status"] != "confirmado":
        raise Erro(409, "ja_cancelado", "este agendamento não está confirmado")
    with bd.escrita() as con:
        con.execute("update agendamentos set status='cancelado', cancelado_por=?, atualizado=? where id=?", (por, _agora_iso(), r["id"]))
        con.execute("insert into eventos(agendamento_id,quando,tipo,detalhe) values(?,?,?,?)", (r["id"], _agora_iso(), "cancelado", por))
    return _ag_dict(bd, bd.um("select * from agendamentos where id=?", (r["id"],)))


def remarcar(bd: Banco, c: sqlite3.Row, r: sqlite3.Row, data: str, hora: str, profissional_id: int | None, por: str) -> dict:
    if r["status"] != "confirmado":
        raise Erro(409, "nao_confirmado", "só dá para remarcar um agendamento confirmado")
    d, ini = data_valida(data), minutos(hora)
    prof = int(profissional_id or r["profissional_id"])
    with bd.escrita() as con:
        if not con.execute("select 1 from profissionais where id=? and clinica_id=? and ativo=1", (prof, c["id"])).fetchone():
            raise Erro(404, "profissional_nao_encontrado", f"profissional {prof} não existe nesta clínica")
        dur = r["fim"] - r["inicio"]
        # `ignorar`: o próprio horário atual não conta como ocupado (remarcar para o mesmo dia, 30 min depois).
        alvo = next((h for h in _livres_dia(con, c, prof, dur, d, ignorar=r["id"]) if h["hora"] == hhmm(ini)), None)
        if not alvo:
            raise Erro(409, "horario_indisponivel", "o novo horário não está livre")
        con.execute("update agendamentos set profissional_id=?, local_id=?, data=?, inicio=?, fim=?, atualizado=? where id=?",
                    (prof, alvo["local_id"], d.isoformat(), ini, ini + dur, _agora_iso(), r["id"]))
        con.execute("insert into eventos(agendamento_id,quando,tipo,detalhe) values(?,?,?,?)",
                    (r["id"], _agora_iso(), "remarcado", f"{por}: de {r['data']} {hhmm(r['inicio'])} para {d.isoformat()} {hhmm(ini)}"))
    return _ag_dict(bd, bd.um("select * from agendamentos where id=?", (r["id"],)))


def listar_agendamentos(bd: Banco, c: sqlite3.Row, de: str, ate: str | None = None, profissional_id: int | None = None,
                        status: str | None = None) -> list[dict]:
    ini = data_valida(de)
    fim = data_valida(ate) if ate else ini
    if fim < ini or (fim - ini).days >= 93:
        raise Erro(422, "janela_invalida", "consulte no máximo 93 dias por vez (de <= ate)")
    if status not in (None, "", "confirmado", "cancelado"):
        raise Erro(422, "status_invalido", "status deve ser 'confirmado' ou 'cancelado'")
    rows = bd.ler("select * from agendamentos where clinica_id=? and data between ? and ? and (? is null or profissional_id=?) "
                  "and (? is null or status=?) order by data, inicio, id",
                  (c["id"], ini.isoformat(), fim.isoformat(), profissional_id, profissional_id, status or None, status or None))
    return [_ag_dict(bd, r) for r in rows]


# ------------------------------------------------------------------ bloqueios

def _ts(s: str) -> str:
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d)(?::\d\d)?", str(s or "").strip())
    if not m:
        raise Erro(422, "data_hora_invalida", f"use AAAA-MM-DDTHH:MM (recebido {s!r})")
    data_valida(m[1])
    minutos(m[2])
    return f"{m[1]}T{m[2]}"


def bloquear(bd: Banco, c: sqlite3.Row, inicio: str, fim: str, profissional_id: int | None = None, motivo: str = "",
             cancelar_conflitos: bool = False) -> dict:
    ini, fi = _ts(inicio), _ts(fim)
    if fi <= ini:
        raise Erro(422, "intervalo_invalido", "o fim do bloqueio precisa ser depois do início")
    if profissional_id and not bd.um("select 1 from profissionais where id=? and clinica_id=?", (int(profissional_id), c["id"])):
        raise Erro(404, "profissional_nao_encontrado", f"profissional {profissional_id} não existe nesta clínica")
    with bd.escrita() as con:
        # Os conflitos são lidos na MESMA transação do insert: um `agendar` que confirmasse entre a leitura e a
        # gravação deixaria uma consulta viva dentro do bloqueio.
        conflitos = []
        for r in con.execute("select * from agendamentos where clinica_id=? and status='confirmado' and data between ? and ? and (? is null or profissional_id=?)",
                             (c["id"], ini[:10], fi[:10], profissional_id, profissional_id)).fetchall():
            a, b = f"{r['data']}T{hhmm(r['inicio'])}", f"{r['data']}T{hhmm(r['fim'])}"
            if a < fi and b > ini:
                conflitos.append(r)
        if conflitos and not cancelar_conflitos:
            raise Erro(409, "conflito_com_consultas", f"o bloqueio atinge {len(conflitos)} consulta(s) confirmada(s); "
                       "cancele-as/remarque antes ou envie cancelar_conflitos=true")
        bid = con.execute("insert into bloqueios(clinica_id,profissional_id,inicio,fim,motivo,criado) values(?,?,?,?,?,?)",
                          (c["id"], profissional_id or None, ini, fi, str(motivo or "")[:200], _agora_iso())).lastrowid
        for r in conflitos:
            con.execute("update agendamentos set status='cancelado', cancelado_por='clinica', atualizado=? where id=?", (_agora_iso(), r["id"]))
            con.execute("insert into eventos(agendamento_id,quando,tipo,detalhe) values(?,?,?,?)", (r["id"], _agora_iso(), "cancelado", f"bloqueio {bid}"))
    return {"id": bid, "inicio": ini, "fim": fi, "profissional_id": profissional_id, "motivo": motivo,
            "consultas_canceladas": [_ag_dict(bd, bd.um("select * from agendamentos where id=?", (r["id"],))) for r in conflitos]}


def listar_bloqueios(bd: Banco, c: sqlite3.Row, a_partir_de: str | None = None) -> list[dict]:
    corte = f"{data_valida(a_partir_de).isoformat() if a_partir_de else agora_local(c['tz'])[0].isoformat()}T00:00"
    return [{"id": r["id"], "inicio": r["inicio"], "fim": r["fim"], "profissional_id": r["profissional_id"], "motivo": r["motivo"]}
            for r in bd.ler("select * from bloqueios where clinica_id=? and fim>=? order by inicio", (c["id"], corte))]


def remover_bloqueio(bd: Banco, c: sqlite3.Row, bloqueio_id: int) -> None:
    with bd.escrita() as con:
        if not con.execute("delete from bloqueios where id=? and clinica_id=?", (int(bloqueio_id), c["id"])).rowcount:
            raise Erro(404, "bloqueio_nao_encontrado", f"bloqueio {bloqueio_id} não existe nesta clínica")
