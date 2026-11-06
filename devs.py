"""Conta de dev (agência, integrador, o amigo que "faz o sistema" da clínica): uma conta, várias clínicas, e é ele quem dá o suporte.

Chave de dev (`ad_...`) vale como chave de escrita em CADA clínica criada por aquela conta (passe `clinica=<slug>`) e nunca em clínica de outro dev.
O dev vê nome e telefone dos pacientes dos próprios clientes: é decisão de produto (o dev dá o suporte), e a clínica é avisada na página de privacidade."""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import sqlite3

import migracao as mig
import nichos as nx
import nucleo as n

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _expira(horas: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def criar(bd: n.Banco, email: str, senha: str = "", nome: str = "", google_sub: str | None = None, github_id: str | None = None) -> sqlite3.Row:
    """Conta nova. Com senha (cadastro por e-mail) ela precisa de 10+ caracteres; sem senha só entra por Google/GitHub."""
    email = str(email or "").strip().lower()[:120]
    if not EMAIL.fullmatch(email):
        raise n.Erro(422, "email_invalido", "e-mail inválido")
    if senha and len(senha) < 10:
        raise n.Erro(422, "senha_curta", "a senha precisa ter pelo menos 10 caracteres")
    with bd.escrita() as con:
        if con.execute("select 1 from devs where email=?", (email,)).fetchone():
            raise n.Erro(409, "email_em_uso", "já existe uma conta de dev com este e-mail")
        did = con.execute("insert into devs(email,nome,senha,google_sub,github_id,criado) values(?,?,?,?,?,?)",
                          (email, str(nome or "").strip()[:80], n.hash_senha(senha) if senha else "", google_sub, github_id, n._agora_iso())).lastrowid
    return bd.um("select * from devs where id=?", (did,))


def _sessao(bd: n.Banco, dev_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with bd.escrita() as con:
        con.execute("delete from dev_sessoes where expira<?", (n._agora_iso(),))
        con.execute("insert into dev_sessoes(hash,dev_id,expira) values(?,?,?)", (n._sha(token), dev_id, _expira(14 * 24)))
    return token


def sessao_de(bd: n.Banco, dev_id: int) -> str:
    return _sessao(bd, dev_id)


def entrar(bd: n.Banco, email: str, senha: str) -> str:
    d = bd.um("select * from devs where email=?", (str(email or "").strip().lower(),))
    ok = n.confere_senha(str(senha or ""), d["senha"] if d and d["senha"] else "scrypt$00$00")  # mesmo custo com conta inexistente ou só-OAuth
    if not (d and d["senha"] and ok):
        raise n.Erro(401, "credenciais", "e-mail ou senha incorretos")
    return _sessao(bd, d["id"])


def dev_da_sessao(bd: n.Banco, token: str) -> sqlite3.Row | None:
    if not token:
        return None
    return bd.um("select d.* from dev_sessoes s join devs d on d.id=s.dev_id where s.hash=? and s.expira>?", (n._sha(token), n._agora_iso()))


def sair(bd: n.Banco, token: str) -> None:
    with bd.escrita() as con:
        con.execute("delete from dev_sessoes where hash=?", (n._sha(token),))


# ---- chaves de dev

def criar_chave(bd: n.Banco, dev_id: int, nome: str) -> dict:
    with bd.escrita() as con:
        if con.execute("select count(*) from chaves_dev where dev_id=? and revogada=0", (dev_id,)).fetchone()[0] >= n.LIMITES["chaves"]:
            raise n.Erro(409, "limite", f"no máximo {n.LIMITES['chaves']} chaves ativas")
        prefixo = secrets.token_hex(4)
        texto = f"ad_{prefixo}_{secrets.token_urlsafe(28)}"
        con.execute("insert into chaves_dev(dev_id,nome,prefixo,hash,criado) values(?,?,?,?,?)", (dev_id, str(nome or "").strip()[:60] or "agente", prefixo, n._sha(texto), n._agora_iso()))
    return {"chave": texto, "prefixo": prefixo, "escopo": "dev", "aviso": "guarde agora: a chave não é mostrada de novo"}


def autenticar(bd: n.Banco, texto: str) -> tuple[sqlite3.Row, str] | None:
    r = bd.um("select d.*, k.id as chave_id from chaves_dev k join devs d on d.id=k.dev_id where k.hash=? and k.revogada=0", (n._sha(texto),)) if texto.startswith("ad_") else None
    if not r:
        return None
    with bd.escrita() as con:
        con.execute("update chaves_dev set ultimo_uso=? where id=?", (n._agora_iso(), r["chave_id"]))
    return r, "dev"


def listar_chaves(bd: n.Banco, dev_id: int) -> list[dict]:
    return [dict(r) for r in bd.ler("select id,nome,prefixo,criado,ultimo_uso from chaves_dev where dev_id=? and revogada=0 order by id", (dev_id,))]


def revogar_chave(bd: n.Banco, dev_id: int, chave_id: int) -> None:
    with bd.escrita() as con:
        con.execute("update chaves_dev set revogada=1 where id=? and dev_id=?", (chave_id, dev_id))


# ---- os clientes do dev (as clínicas dele)

def clinica_do_dev(bd: n.Banco, dev: sqlite3.Row, slug: str) -> sqlite3.Row:
    c = n.clinica_por_slug(bd, slug)
    if c["dev_id"] != dev["id"]:
        raise n.Erro(403, "outra_clinica", "esta clínica não é de um cliente desta conta de dev")
    return c


def clinicas(bd: n.Banco, dev: sqlite3.Row) -> list[dict]:
    return [{"slug": r["slug"], "nome": r["nome"], "nicho": r["nicho"], "cidade": r["cidade"], "criado": r["criado"], "agendamentos_futuros": r["fut"],
             "personalizar": r["personalizar"]}
            for r in bd.ler("select c.*, (select count(*) from agendamentos a where a.clinica_id=c.id and a.status='confirmado' and a.data>=date('now')) fut "
                            "from clinicas c where c.dev_id=? order by c.id", (dev["id"],))]


def criar_clinica(bd: n.Banco, dev: sqlite3.Row, nome: str, nicho: str = "clinica", slug: str = "", cidade: str = "", telefone: str = "") -> dict:
    if bd.um("select count(*) q from clinicas where dev_id=?", (dev["id"],))["q"] >= n.LIMITES["clinicas_por_dev"]:
        raise n.Erro(409, "limite", f"no máximo {n.LIMITES['clinicas_por_dev']} clientes por conta de dev")
    # O login da clínica nasce com e-mail de reserva e senha aleatória (ninguém a vê): o dev entra pelo suporte ou define o acesso do cliente depois.
    c = n.criar_clinica(bd, nome, f"suporte+{secrets.token_hex(5)}@clientes.invalid", secrets.token_hex(16), slug, nicho)
    with bd.escrita() as con:
        con.execute("update clinicas set dev_id=? where id=?", (dev["id"], c["id"]))
    n.salvar_clinica(bd, bd.um("select * from clinicas where id=?", (c["id"],)), {"cidade": cidade, "telefone": telefone})
    return {"slug": c["slug"], "nicho": c["nicho"], "pagina": f"/c/{c['slug']}"}


def apagar_clinica(bd: n.Banco, dev: sqlite3.Row, slug: str, confirmar: str) -> None:
    c = clinica_do_dev(bd, dev, slug)
    if confirmar != c["slug"]:
        raise n.Erro(422, "confirmacao", "para apagar, envie confirmar com o endereço (slug) da clínica; não tem volta, exporte antes")
    mig.apagar_clinica(bd, c["slug"])


def definir_acesso(bd: n.Banco, dev: sqlite3.Row, slug: str, email: str, senha: str) -> None:
    """O dev entrega ao cliente o login da clínica (e-mail e senha escolhidos agora)."""
    c = clinica_do_dev(bd, dev, slug)
    email = str(email or "").strip().lower()[:120]
    if not EMAIL.fullmatch(email) or len(str(senha or "")) < 10:
        raise n.Erro(422, "acesso_invalido", "e-mail inválido ou senha com menos de 10 caracteres")
    with bd.escrita() as con:
        if con.execute("select 1 from usuarios where email=? and clinica_id!=?", (email, c["id"])).fetchone():
            raise n.Erro(409, "email_em_uso", "já existe uma conta de clínica com este e-mail")
        con.execute("update usuarios set email=?, senha=? where clinica_id=?", (email, n.hash_senha(senha), c["id"]))
        con.execute("delete from sessoes where usuario_id in (select id from usuarios where clinica_id=?)", (c["id"],))


def sessao_suporte(bd: n.Banco, dev: sqlite3.Row, slug: str) -> str:
    """Sessão de painel da clínica para o dev dar suporte (8 h). Devolve o token do cookie `sessao`."""
    c = clinica_do_dev(bd, dev, slug)
    u = bd.um("select id from usuarios where clinica_id=? order by id limit 1", (c["id"],))
    token = secrets.token_urlsafe(32)
    with bd.escrita() as con:
        con.execute("insert into sessoes(hash,usuario_id,expira) values(?,?,?)", (n._sha(token), u["id"], _expira(8)))
    return token


def por_provedor(bd: n.Banco, prov: str, ident: dict, pode_criar=lambda: True) -> tuple[sqlite3.Row, bool]:
    """Dev dono desta identidade do Google/GitHub: acha pelo id do provedor, senão liga a uma conta de MESMO e-mail verificado, senão cria. (conta, criada)"""
    col = {"google": "google_sub", "github": "github_id"}[prov]
    if not ident.get("sub") or not ident.get("verificado") or not EMAIL.fullmatch(ident.get("email", "")):
        raise n.Erro(422, "email_nao_verificado", f"o {prov.capitalize()} não informou um e-mail verificado; verifique-o lá ou use e-mail e senha")
    d = bd.um(f"select * from devs where {col}=?", (ident["sub"],))  # noqa: S608 - nome de coluna é constante nossa
    if d:
        return d, False
    d = bd.um("select * from devs where email=?", (ident["email"],))
    if d:
        with bd.escrita() as con:
            con.execute(f"update devs set {col}=? where id=?", (ident["sub"], d["id"]))  # noqa: S608
        return bd.um("select * from devs where id=?", (d["id"],)), False
    if not pode_criar():
        raise n.Erro(429, "cadastros_pausados", "o limite diário de contas novas foi atingido; tente amanhã")
    return criar(bd, ident["email"], "", ident.get("nome", ""), **{col: ident["sub"]}), True


def personalizar(bd: n.Banco, dev: sqlite3.Row, slug: str, cor=None, rotulos=None) -> dict:
    """O dev muda a cor e os rótulos do cliente (os textos do site, do agendamento e da página do cliente final). `cor=""` e `rotulos={}` limpam."""
    c = clinica_do_dev(bd, dev, slug)
    try:
        nova = nx.validar_personalizacao(cor, rotulos)
    except ValueError as e:
        raise n.Erro(422, "personalizacao_invalida", str(e)) from None
    with bd.escrita() as con:
        con.execute("update clinicas set personalizar=? where id=?", (json.dumps(nova, ensure_ascii=False) if nova else "", c["id"]))
    return nova
