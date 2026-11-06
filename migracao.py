"""Sair do nosso servidor, ou entrar no seu: exportar e importar uma clínica inteira (JSON versionado) e apagar o que se importou.

Nunca vão no arquivo: hash de senha, chaves de API, sessões, a instância do WhatsApp (cada servidor tem o seu Evolution) e a fila de lembretes.
Agendamentos (dado de paciente, LGPD) só vão com `com_pacientes=True`, e o código de cada um vai junto para os links `/m/<código>` continuarem valendo."""
from __future__ import annotations

import sqlite3

import nucleo as n

FORMATO = "agenda-clinica/1"
TETO_AGENDAMENTOS = 50000


def exportar(bd: n.Banco, c: sqlite3.Row, com_pacientes: bool = False) -> dict:
    cid = c["id"]
    refs = lambda tabela: {r["id"]: r for r in bd.ler(f"select * from {tabela} where clinica_id=? order by id", (cid,))}  # noqa: E731 - nome de tabela é constante nossa
    locais, profs, servs = refs("locais"), refs("profissionais"), refs("servicos")
    janelas: dict[int, list] = {}
    for j in bd.ler("select d.* from disponibilidade d join profissionais p on p.id=d.profissional_id where p.clinica_id=? order by d.dia, d.inicio", (cid,)):
        janelas.setdefault(j["profissional_id"], []).append({"dia": j["dia"], "inicio": n.hhmm(j["inicio"]), "fim": n.hhmm(j["fim"]), "local": j["local_id"]})
    out = {"formato": FORMATO,
           "clinica": {k: c[k] for k in ("slug", "nome", "descricao", "telefone", "email", "cidade", "tz", "passo_min", "antecedencia_min", "nicho")},
           "locais": [{"ref": i, **{k: r[k] for k in ("nome", "endereco", "cidade", "ativo")}} for i, r in locais.items()],
           "profissionais": [{"ref": i, **{k: r[k] for k in ("nome", "especialidade", "registro", "bio", "ativo")}, "janelas": janelas.get(i, [])} for i, r in profs.items()],
           "servicos": [{"ref": i, **{k: r[k] for k in ("nome", "duracao_min", "preco_centavos", "ativo")}} for i, r in servs.items()],
           "bloqueios": [{"profissional": b["profissional_id"], "inicio": b["inicio"], "fim": b["fim"], "motivo": b["motivo"]}
                         for b in bd.ler("select * from bloqueios where clinica_id=? order by id", (cid,))],
           "com_pacientes": bool(com_pacientes)}
    if com_pacientes:
        out["agendamentos"] = [{"profissional": a["profissional_id"], "local": a["local_id"], "servico": a["servico_id"], "paciente_nome": a["paciente_nome"],
                                "paciente_tel": a["paciente_tel"], "paciente_email": a["paciente_email"], "data": a["data"], "inicio": n.hhmm(a["inicio"]),
                                "fim": n.hhmm(a["fim"]), "status": a["status"], "cancelado_por": a["cancelado_por"], "codigo": a["codigo"], "origem": a["origem"]}
                               for a in bd.ler("select * from agendamentos where clinica_id=? order by id limit ?", (cid, TETO_AGENDAMENTOS))]
    return out


def apagar_clinica(bd: n.Banco, slug: str) -> None:
    """A inversa de criar/importar (regra da casa: quem cria escreve o que apaga). Não tem volta: exporte antes."""
    c = n.clinica_por_slug(bd, slug)
    cid = c["id"]
    with bd.escrita() as con:
        for sql in ("delete from eventos where agendamento_id in (select id from agendamentos where clinica_id=?)",
                    "delete from lembretes where agendamento_id in (select id from agendamentos where clinica_id=?)",
                    "delete from agendamentos where clinica_id=?", "delete from bloqueios where clinica_id=?",
                    "delete from disponibilidade where profissional_id in (select id from profissionais where clinica_id=?)",
                    "delete from servicos where clinica_id=?", "delete from profissionais where clinica_id=?", "delete from locais where clinica_id=?",
                    "delete from chaves where clinica_id=?", "delete from sessoes where usuario_id in (select id from usuarios where clinica_id=?)",
                    "delete from usuarios where clinica_id=?", "delete from sem_lembrete where clinica_id=?", "delete from clinicas where id=?"):
            con.execute(sql, (cid,))


def _lista(d: dict, chave: str, teto: int) -> list:
    v = d.get(chave, [])
    if not isinstance(v, list) or len(v) > teto or not all(isinstance(x, dict) for x in v):
        raise n.Erro(422, "arquivo_invalido", f"'{chave}' deve ser uma lista de objetos (no máximo {teto})")
    return v


def importar(bd: n.Banco, dados: dict, email: str, senha: str, slug: str = "") -> dict:
    """Recria a clínica do arquivo neste servidor, com login novo (e-mail e senha de quem importa). Se algo falhar no meio, desfaz tudo."""
    if not isinstance(dados, dict) or dados.get("formato") != FORMATO:
        raise n.Erro(422, "formato_desconhecido", f"arquivo não é {FORMATO!r}")
    cl = dados.get("clinica")
    if not isinstance(cl, dict):
        raise n.Erro(422, "arquivo_invalido", "falta o objeto 'clinica'")
    locais, profs, servs = _lista(dados, "locais", n.LIMITES["locais"]), _lista(dados, "profissionais", n.LIMITES["profissionais"]), _lista(dados, "servicos", n.LIMITES["servicos"])
    bloqueios, ags = _lista(dados, "bloqueios", 5000), _lista(dados, "agendamentos", TETO_AGENDAMENTOS)
    nova = n.criar_clinica(bd, str(cl.get("nome", "")), email, senha, slug or str(cl.get("slug", "")), str(cl.get("nicho") or "clinica"))
    cid = nova["id"]
    try:
        n.salvar_clinica(bd, bd.um("select * from clinicas where id=?", (cid,)),
                         {k: cl[k] for k in ("descricao", "telefone", "email", "cidade", "tz", "passo_min", "antecedencia_min") if k in cl})
        L = {x["ref"]: n.salvar_local(bd, cid, {k: x[k] for k in ("nome", "endereco", "cidade", "ativo") if k in x}) for x in locais}
        S = {x["ref"]: n.salvar_servico(bd, cid, {k: x[k] for k in ("nome", "duracao_min", "preco_centavos", "ativo") if k in x}) for x in servs}
        P = {}
        for x in profs:
            P[x["ref"]] = pid = n.salvar_profissional(bd, cid, {k: x[k] for k in ("nome", "especialidade", "registro", "bio", "ativo") if k in x})
            n.definir_disponibilidade(bd, cid, pid, [{"dia": j["dia"], "inicio": j["inicio"], "fim": j["fim"], "local_id": L[j["local"]]} for j in x.get("janelas", [])])
        feitos = 0
        with bd.escrita() as con:
            for b in bloqueios:
                con.execute("insert into bloqueios(clinica_id,profissional_id,inicio,fim,motivo,criado) values(?,?,?,?,?,?)",
                            (cid, P.get(b.get("profissional")), str(b["inicio"])[:25], str(b["fim"])[:25], str(b.get("motivo", ""))[:200], n._agora_iso()))
            for a in ags:
                if con.execute("select 1 from agendamentos where codigo=?", (a["codigo"],)).fetchone():
                    continue  # código já usado neste servidor: pula em vez de sobrescrever o agendamento de outra clínica
                feitos += 1
                con.execute("insert into agendamentos(clinica_id,profissional_id,local_id,servico_id,paciente_nome,paciente_tel,paciente_email,data,inicio,fim,status,"
                            "cancelado_por,codigo,origem,criado,atualizado) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (cid, P[a["profissional"]], L[a["local"]], S[a["servico"]], str(a["paciente_nome"])[:100], str(a["paciente_tel"])[:13], str(a.get("paciente_email", ""))[:120],
                             n.data_valida(a["data"]).isoformat(), n.minutos(a["inicio"]), n.minutos(a["fim"]), a.get("status", "confirmado"),
                             a.get("cancelado_por"), a["codigo"], a.get("origem", "web"), n._agora_iso(), n._agora_iso()))
    except (KeyError, TypeError, ValueError, n.Erro, sqlite3.Error) as e:
        apagar_clinica(bd, nova["slug"])
        if isinstance(e, n.Erro):
            raise
        raise n.Erro(422, "arquivo_invalido", f"arquivo com campo faltando ou inválido ({type(e).__name__}: {e}); nada foi importado") from None
    return {"slug": nova["slug"], "locais": len(L), "profissionais": len(P), "servicos": len(S), "bloqueios": len(bloqueios),
            "agendamentos": feitos}
