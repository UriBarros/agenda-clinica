"""Lembretes por WhatsApp pelo Evolution API (https://github.com/EvolutionAPI/evolution-api).

Desenho: o lembrete só nasce como CONSEQUÊNCIA de um agendamento real (ver `nucleo._programar`) e sai do WhatsApp do próprio dono da
clínica, pela instância dele. Não existe operação, nem na API nem no MCP, que receba um número ou um texto livre: por isso isto não serve
de disparador de spam. A chave do Evolution mora só no ambiente do servidor (EVOLUTION_URL, EVOLUTION_KEY) e nunca é gravada nem devolvida.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

import nucleo as n

AVISO = ("RISCO: o Evolution usa o WhatsApp Web (não oficial). O WhatsApp pode BANIR o número que manda mensagem em massa, para quem não o tem "
         "salvo ou para quem denuncia. Use um número só da clínica, nunca para divulgação. Aqui só saem lembretes para quem agendou (1 confirmação "
         "e 1 lembrete por consulta, no máximo %d por dia), com link para não receber mais. Para volume ou garantia, use a API oficial da Meta.")
MAX_TENTATIVAS = 3


def configurado() -> bool:
    return bool(os.environ.get("EVOLUTION_URL") and os.environ.get("EVOLUTION_KEY"))


def teto_dia() -> int:
    return int(os.environ.get("WHATSAPP_TETO_DIA", "100"))


def aviso() -> str:
    return AVISO % teto_dia()


def _pedir(metodo: str, caminho: str, corpo: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(os.environ["EVOLUTION_URL"].rstrip("/") + caminho, method=metodo,
                                 data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"apikey": os.environ["EVOLUTION_KEY"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return 0, {}


def estado_instancia(instancia: str) -> str:
    """"conectado", "desconectado" ou "indisponivel" (Evolution fora do ar ou sem a instância)."""
    if not configurado():
        return "indisponivel"
    st, j = _pedir("GET", f"/instance/connectionState/{instancia}")
    if st != 200:
        return "indisponivel"
    return "conectado" if (j.get("instance") or j).get("state") == "open" else "desconectado"


def numero(tel: str) -> str:
    d = "".join(ch for ch in str(tel) if ch.isdigit())
    return "55" + d if len(d) in (10, 11) else d


def enviar(instancia: str, tel: str, texto: str) -> tuple[bool, str]:
    """"Aceito pelo Evolution" não é "chegou no aparelho": o Evolution não expõe a entrega. Quem confirma é o paciente."""
    st, _ = _pedir("POST", f"/message/sendText/{instancia}", {"number": numero(tel), "text": texto})
    return (True, "aceito pelo Evolution") if st in (200, 201) else (False, f"evolution respondeu {st or 'sem resposta'}")


ENVIAR: Callable[[str, str, str], tuple[bool, str]] = enviar  # os testes trocam por um falso: nunca mande WhatsApp real em teste


def texto(tipo: str, r: sqlite3.Row, base: str) -> str:
    d = dt.date.fromisoformat(r["data"])
    quando = f"{d.day:02d}/{d.month:02d} às {n.hhmm(r['inicio'])}"
    corpo = (f"Agendamento confirmado: {r['servico']} com {r['profissional']}, {quando} ({r['local']})." if tipo == "confirmacao"
             else f"Lembrete: {r['servico']} com {r['profissional']}, {quando} ({r['local']}).")
    return (f"[{r['clinica']}] Olá, {r['paciente_nome']}! {corpo}\nVer, remarcar ou cancelar: {base}/m/{r['codigo']}\n"
            f"Não pediu este agendamento ou não quer lembretes? {base}/m/{r['codigo']}/sem-lembrete")


CONSULTA = ("select l.id lid, l.tipo, l.tentativas, a.paciente_nome, a.paciente_tel, a.codigo, a.data, a.inicio, a.status ast, a.clinica_id, "
            "c.nome clinica, c.whatsapp_ativo, c.whatsapp_instancia, s.nome servico, p.nome profissional, lo.nome local "
            "from lembretes l join agendamentos a on a.id=l.agendamento_id join clinicas c on c.id=a.clinica_id "
            "join servicos s on s.id=a.servico_id join profissionais p on p.id=a.profissional_id join locais lo on lo.id=a.local_id "
            "where l.status='pendente' and l.enviar_em<=? order by l.enviar_em limit 50")


def _marcar(bd: n.Banco, lid: int, status: str, detalhe: str, tentativas: int | None = None, depois_min: int = 0) -> None:
    with bd.escrita() as con:
        con.execute("update lembretes set status=?, detalhe=?, tentativas=coalesce(?, tentativas), atualizado=?, "
                    "enviar_em=case when ?>0 then strftime('%Y-%m-%dT%H:%M:%SZ','now',?) else enviar_em end where id=?",
                    (status, detalhe[:200], tentativas, n._agora_iso(), depois_min, f"+{depois_min} minutes", lid))


def rodar_uma_vez(bd: n.Banco, base_url: str, pausa_s: float = 3.0) -> dict:
    """Envia o que venceu. Freios: teto diário por clínica, pausa entre mensagens (3 s), opt-out do paciente, 3 tentativas e instância
    desconectada não vira laço de erro. Devolve contadores (para teste e para log)."""
    cont = {"enviados": 0, "cancelados": 0, "adiados": 0, "falhas": 0}
    conectada: dict[str, str] = {}
    for r in bd.ler(CONSULTA, (n._agora_iso(),)):
        if r["ast"] != "confirmado" or not r["whatsapp_ativo"] or bd.um("select 1 from sem_lembrete where clinica_id=? and tel=?", (r["clinica_id"], r["paciente_tel"])):
            _marcar(bd, r["lid"], "cancelado", "consulta cancelada, whatsapp desligado ou paciente pediu para não receber")
            cont["cancelados"] += 1
            continue
        feitos = bd.um("select count(*) q from lembretes l join agendamentos a on a.id=l.agendamento_id where a.clinica_id=? and l.status='enviado' "
                       "and date(l.atualizado)=date('now')", (r["clinica_id"],))["q"]
        if feitos >= teto_dia():
            cont["adiados"] += 1  # fica pendente: amanhã sai (ou vence a consulta e ninguém lembra, que é melhor que banir o número)
            continue
        inst = r["whatsapp_instancia"]
        if inst not in conectada:
            conectada[inst] = estado_instancia(inst)
        ok, det = (False, f"whatsapp {conectada[inst]}") if conectada[inst] != "conectado" else ENVIAR(inst, r["paciente_tel"], texto(r["tipo"], r, base_url))
        if ok:
            _marcar(bd, r["lid"], "enviado", det, r["tentativas"] + 1)
            cont["enviados"] += 1
            time.sleep(pausa_s)
        else:
            t = r["tentativas"] + 1
            _marcar(bd, r["lid"], "falhou" if t >= MAX_TENTATIVAS else "pendente", det, t, 0 if t >= MAX_TENTATIVAS else 10)
            cont["falhas"] += 1
    return cont


def laco(bd: n.Banco, base_url: str) -> None:
    while True:
        try:
            rodar_uma_vez(bd, base_url)
        except Exception as ex:  # noqa: BLE001 - a rotina nunca morre: o pior caso é o lembrete atrasar
            print(f"lembretes: {type(ex).__name__}: {ex}", flush=True)
        time.sleep(60)


def iniciar(bd: n.Banco, base_url: str) -> bool:
    """Liga a rotina só se o servidor tem Evolution E sabe o próprio endereço (os links da mensagem precisam dele)."""
    if not (configurado() and base_url):
        return False
    threading.Thread(target=laco, args=(bd, base_url), daemon=True).start()
    return True


def estado(bd: n.Banco, c: sqlite3.Row) -> dict:
    cont = {r["status"]: r["q"] for r in bd.ler("select l.status, count(*) q from lembretes l join agendamentos a on a.id=l.agendamento_id "
                                                "where a.clinica_id=? group by 1", (c["id"],))}
    return {"servidor_com_evolution": configurado(), "ativo": bool(c["whatsapp_ativo"]), "instancia": c["whatsapp_instancia"],
            "whatsapp": estado_instancia(c["whatsapp_instancia"]) if c["whatsapp_instancia"] else "sem_instancia",
            "lembrete_horas": c["lembrete_horas"], "confirmacao": bool(c["whatsapp_confirmacao"]), "teto_dia": teto_dia(),
            "lembretes": cont, "aviso": aviso()}


def configurar(bd: n.Banco, c: sqlite3.Row, ativo, instancia, horas, confirmacao, aceito_risco) -> dict:
    ligando = ativo is not None and bool(ativo) and not c["whatsapp_ativo"]
    if ligando and not configurado():
        raise n.Erro(409, "whatsapp_indisponivel", "este servidor não tem Evolution configurado (EVOLUTION_URL e EVOLUTION_KEY)")
    if ligando and not aceito_risco:
        raise n.Erro(422, "risco_nao_aceito", "para ligar, envie aceito_risco=true depois de ler o aviso: " + aviso())
    n.salvar_whatsapp(bd, c, ativo, instancia, horas, confirmacao)
    return estado(bd, n.clinica_por_slug(bd, c["slug"]))


def lista(bd: n.Banco, c: sqlite3.Row, limite: int = 50) -> list[dict]:
    return [{"id": r["id"], "agendamento_id": r["agendamento_id"], "tipo": r["tipo"], "status": r["status"], "enviar_em": r["enviar_em"],
             "tentativas": r["tentativas"], "detalhe": r["detalhe"], "telefone": "***" + r["tel"][-4:]}
            for r in bd.ler("select l.*, a.paciente_tel tel from lembretes l join agendamentos a on a.id=l.agendamento_id where a.clinica_id=? "
                            "order by l.id desc limit ?", (c["id"], max(1, min(int(limite), 200))))]


def nao_quero(bd: n.Banco, codigo: str) -> None:
    """Opt-out do paciente pelo link da mensagem: vale para o telefone inteiro naquela clínica e cancela o que está na fila."""
    r, c = n.agendamento_por_codigo(bd, codigo)
    with bd.escrita() as con:
        con.execute("insert or ignore into sem_lembrete(clinica_id, tel, criado) values(?,?,?)", (c["id"], r["paciente_tel"], n._agora_iso()))
        con.execute("update lembretes set status='cancelado', detalhe='paciente pediu para não receber', atualizado=? where status='pendente' and "
                    "agendamento_id in (select id from agendamentos where clinica_id=? and paciente_tel=?)", (n._agora_iso(), c["id"], r["paciente_tel"]))
