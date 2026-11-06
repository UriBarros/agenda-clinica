"""Registro único de operações: de UMA tabela saem a API REST, as ferramentas MCP, o OpenAPI e o llms.txt.

Por quê: REST e MCP descritos à mão divergem na primeira semana. Aqui a operação é declarada uma vez
(nome, parâmetros, nível de acesso) e os consumidores leem a mesma fonte; tests/test_ops.py falha se uma
operação some de algum deles.

Níveis: "publico" (qualquer pessoa ou agente: ver clínica, horários, agendar, gerir a própria consulta pelo
código), "leitura" e "escrita" (chave de API da clínica, enviada em `Authorization: Bearer ac_...`).
"""
from __future__ import annotations

import re
from typing import Any, Callable

import lembretes as lem
import nucleo as n

NIVEL = {"publico": 0, "leitura": 1, "escrita": 2}
OPS: dict[str, dict] = {}
# Agendamentos SEM chave por clínica: um atacante com vários IPs não esvazia a agenda de uma clínica em minutos.
LIM_CLINICA = n.Limitador()


def P(nome: str, tipo: str, desc: str, obrig: bool = False) -> dict:
    return {"nome": nome, "tipo": tipo, "desc": desc, "obrig": obrig}


def op(nome: str, desc: str, metodo: str, caminho: str, params: list[dict], nivel: str = "publico",
       ok: int = 200, por: str = "slug") -> Callable:
    """por: como a clínica é achada — "slug" (parâmetro `clinica`, ou a da chave), "chave" (só a da chave), "codigo" (pelo código da consulta)."""
    def reg(fn: Callable) -> Callable:
        OPS[nome] = {"nome": nome, "desc": desc, "metodo": metodo, "caminho": caminho, "params": params,
                     "nivel": nivel, "ok": ok, "por": por, "fn": fn}
        return fn
    return reg


def _clinica_p() -> dict:
    return P("clinica", "string", "endereço (slug) da clínica, ex.: 'clinica-aurora'; dispensável com chave de API")


def _tipar(spec: dict, valor: Any) -> Any:
    t = spec["tipo"]
    try:
        if t == "integer":
            return int(valor)
        if t == "boolean":
            return valor if isinstance(valor, bool) else str(valor).lower() in ("1", "true", "sim", "yes")
        if t == "string":
            return str(valor)
    except (TypeError, ValueError, OverflowError):
        raise n.Erro(422, "parametro_invalido", f"parâmetro {spec['nome']!r} deve ser {t}") from None
    return valor


def executar(bd: n.Banco, nome: str, args: dict, auth: tuple | None, origem: str = "api") -> tuple[dict, int]:
    """(resposta, status). `auth` = (linha da clínica, escopo) vindo da chave, ou None."""
    o = OPS.get(nome)
    if not o:
        raise n.Erro(404, "operacao_desconhecida", f"operação {nome!r} não existe")
    nivel = auth[1] if auth else "publico"
    if NIVEL[nivel] < NIVEL[o["nivel"]]:
        if not auth:
            raise n.Erro(401, "chave_obrigatoria", "esta operação exige uma chave de API (Authorization: Bearer ac_...)")
        raise n.Erro(403, "escopo_insuficiente", f"esta operação exige chave com escopo '{o['nivel']}'")
    a: dict = {}
    for p in o["params"]:
        if args.get(p["nome"]) not in (None, ""):
            a[p["nome"]] = _tipar(p, args[p["nome"]])
        elif p["obrig"]:
            raise n.Erro(422, "parametro_obrigatorio", f"falta o parâmetro {p['nome']!r}")
    a["_origem"] = origem
    c = None
    if o["por"] == "chave" or (o["por"] == "slug" and auth and not a.get("clinica")):
        c = auth[0]
    elif o["por"] == "slug":
        c = n.clinica_por_slug(bd, a.get("clinica", ""))
        if auth and auth[0]["id"] != c["id"]:
            raise n.Erro(403, "outra_clinica", "a chave de API é de outra clínica")
    if o["nome"] == "agendar" and not auth and c is not None and not LIM_CLINICA.passa(
            "agendar_anonimo", str(c["id"]), n.LIMITES["anonimos_por_clinica_hora"], 3600):
        raise n.Erro(429, "clinica_sobrecarregada", "muitos agendamentos nesta clínica na última hora; tente mais tarde ou ligue para a clínica")
    return o["fn"](bd, c, a), o["ok"]


# ---------------------------------------------------------------- públicas

def _sem_paciente(bd, ag_id: int) -> dict:
    return n._ag_dict(bd, bd.um("select * from agendamentos where id=?", (ag_id,)), com_paciente=False)


@op("clinica_info", "Dados da clínica: locais, profissionais com a agenda semanal, serviços (duração, preço em centavos). Comece por aqui.",
    "GET", "/clinicas/{clinica}", [_clinica_p()])
def _clinica_info(bd, c, a):
    return n.info_publica(bd, c)


@op("horarios_livres", "Horários livres para um serviço, num dia ou intervalo (até 14 dias, no máximo 300 horários; `truncado=true` = há mais, refine), com profissional e local. É a fonte de verdade: "
    "confirme aqui antes de agendar.", "GET", "/clinicas/{clinica}/horarios",
    [_clinica_p(), P("servico_id", "integer", "id do serviço", True), P("de", "string", "data inicial AAAA-MM-DD", True),
     P("ate", "string", "data final AAAA-MM-DD (padrão: só o dia 'de')"), P("profissional_id", "integer", "restringe a um profissional"),
     P("local_id", "integer", "restringe a um local")])
def _horarios(bd, c, a):
    teto = n.LIMITES["linhas_horarios"]
    linhas = n.horarios_livres(bd, c, a["servico_id"], a.get("profissional_id"), a["de"], a.get("ate"), a.get("local_id"), limite=teto + 1)
    # `truncado`: havia mais horários que o teto; o agente refina por profissional, local ou janela menor.
    return {"horarios": linhas[:teto], "truncado": len(linhas) > teto}


@op("agendar", "Agenda uma consulta num horário livre. Devolve o `codigo` com que o paciente consulta, cancela ou remarca. "
    "Só envie consentimento=true se o paciente concordou com o uso do nome e telefone para o agendamento.",
    "POST", "/clinicas/{clinica}/agendamentos",
    [_clinica_p(), P("servico_id", "integer", "id do serviço", True), P("profissional_id", "integer", "id do profissional", True),
     P("data", "string", "AAAA-MM-DD", True), P("hora", "string", "HH:MM, um dos horários de horarios_livres", True),
     P("nome", "string", "nome do paciente", True), P("telefone", "string", "telefone com DDD", True),
     P("email", "string", "e-mail do paciente (opcional)"), P("consentimento", "boolean", "o paciente consentiu (LGPD)", True)], ok=201)
def _agendar(bd, c, a):
    return n.agendar(bd, c, a["servico_id"], a["profissional_id"], a["data"], a["hora"], a["nome"], a["telefone"],
                     a.get("email", ""), a["_origem"], bool(a.get("consentimento")))


@op("ver_consulta", "Consulta um agendamento pelo código recebido ao agendar (sem chave de API).", "GET", "/consultas/{codigo}",
    [P("codigo", "string", "código do agendamento", True)], por="codigo")
def _ver_consulta(bd, c, a):
    r, _ = n.agendamento_por_codigo(bd, a["codigo"])
    return n._ag_dict(bd, r, com_paciente=False)


@op("cancelar_consulta", "Cancela o agendamento pelo código (o paciente cancelando a própria consulta).", "POST", "/consultas/{codigo}/cancelar",
    [P("codigo", "string", "código do agendamento", True)], por="codigo")
def _cancelar_consulta(bd, c, a):
    r, _ = n.agendamento_por_codigo(bd, a["codigo"])
    n.cancelar(bd, r, "paciente")
    return _sem_paciente(bd, r["id"])  # o código dá acesso à consulta, não ao cadastro do paciente


@op("remarcar_consulta", "Remarca o agendamento pelo código para outro horário livre (mesmo serviço; pode trocar de profissional).",
    "POST", "/consultas/{codigo}/remarcar",
    [P("codigo", "string", "código do agendamento", True), P("data", "string", "nova data AAAA-MM-DD", True),
     P("hora", "string", "novo horário HH:MM", True), P("profissional_id", "integer", "outro profissional (opcional)")], por="codigo")
def _remarcar_consulta(bd, c, a):
    r, cl = n.agendamento_por_codigo(bd, a["codigo"])
    n.remarcar(bd, cl, r, a["data"], a["hora"], a.get("profissional_id"), "paciente")
    return _sem_paciente(bd, r["id"])


# ---------------------------------------------------------------- com chave: leitura

@op("listar_agendamentos", "Lista os agendamentos da clínica num intervalo (até 93 dias), com dados do paciente.", "GET", "/agendamentos",
    [P("de", "string", "data inicial AAAA-MM-DD", True), P("ate", "string", "data final (padrão: só o dia 'de')"),
     P("profissional_id", "integer", "filtra por profissional"), P("status", "string", "confirmado ou cancelado")], nivel="leitura", por="chave")
def _listar_ag(bd, c, a):
    return {"agendamentos": n.listar_agendamentos(bd, c, a["de"], a.get("ate"), a.get("profissional_id"), a.get("status"))}


@op("ver_agendamento", "Um agendamento da clínica pelo id.", "GET", "/agendamentos/{id}",
    [P("id", "integer", "id do agendamento", True)], nivel="leitura", por="chave")
def _ver_ag(bd, c, a):
    return n._ag_dict(bd, n.agendamento_da_clinica(bd, c, a["id"]))


@op("listar_bloqueios", "Bloqueios de agenda (folgas, férias, reuniões) de hoje em diante.", "GET", "/bloqueios",
    [P("a_partir_de", "string", "AAAA-MM-DD (padrão: hoje)")], nivel="leitura", por="chave")
def _listar_bl(bd, c, a):
    return {"bloqueios": n.listar_bloqueios(bd, c, a.get("a_partir_de"))}


# ---------------------------------------------------------------- com chave: escrita

@op("cancelar_agendamento", "Cancela um agendamento (a clínica cancelando). Avise o paciente (os lembretes por WhatsApp, se ligados, são só de consultas confirmadas).",
    "POST", "/agendamentos/{id}/cancelar", [P("id", "integer", "id do agendamento", True)], nivel="escrita", por="chave")
def _cancelar_ag(bd, c, a):
    return n.cancelar(bd, n.agendamento_da_clinica(bd, c, a["id"]), "clinica")


@op("remarcar_agendamento", "Remarca um agendamento para outro horário livre; pode trocar o profissional. Avise o paciente.",
    "POST", "/agendamentos/{id}/remarcar",
    [P("id", "integer", "id do agendamento", True), P("data", "string", "nova data AAAA-MM-DD", True),
     P("hora", "string", "novo horário HH:MM", True), P("profissional_id", "integer", "outro profissional (opcional)")], nivel="escrita", por="chave")
def _remarcar_ag(bd, c, a):
    return n.remarcar(bd, c, n.agendamento_da_clinica(bd, c, a["id"]), a["data"], a["hora"], a.get("profissional_id"), "clinica")


@op("bloquear_agenda", "Bloqueia a agenda de um profissional (ou da clínica toda, sem profissional_id) num intervalo. "
    "Se houver consultas confirmadas no intervalo, recusa (409) a menos que cancelar_conflitos=true, que as cancela e devolve a lista.",
    "POST", "/bloqueios",
    [P("inicio", "string", "AAAA-MM-DDTHH:MM", True), P("fim", "string", "AAAA-MM-DDTHH:MM", True),
     P("profissional_id", "integer", "vazio = clínica toda"), P("motivo", "string", "texto livre"),
     P("cancelar_conflitos", "boolean", "cancela as consultas atingidas")], nivel="escrita", ok=201, por="chave")
def _bloquear(bd, c, a):
    return n.bloquear(bd, c, a["inicio"], a["fim"], a.get("profissional_id"), a.get("motivo", ""), bool(a.get("cancelar_conflitos")))


@op("remover_bloqueio", "Remove um bloqueio de agenda.", "DELETE", "/bloqueios/{id}",
    [P("id", "integer", "id do bloqueio", True)], nivel="escrita", por="chave")
def _remover_bl(bd, c, a):
    n.remover_bloqueio(bd, c, a["id"])
    return {"removido": a["id"]}


@op("salvar_local", "Cria um local de atendimento (sem id) ou atualiza (com id). ativo=false desativa.", "POST", "/locais",
    [P("id", "integer", "id (atualizar)"), P("nome", "string", "nome do local"), P("endereco", "string", "endereço"),
     P("cidade", "string", "cidade"), P("ativo", "boolean", "false desativa")], nivel="escrita", ok=201, por="chave")
def _salvar_local(bd, c, a):
    return {"id": n.salvar_local(bd, c["id"], a)}


@op("salvar_profissional", "Cria um profissional (sem id) ou atualiza (com id). ativo=false desativa.", "POST", "/profissionais",
    [P("id", "integer", "id (atualizar)"), P("nome", "string", "nome"), P("especialidade", "string", "especialidade"),
     P("registro", "string", "registro no conselho (CRM, CRP...)"), P("bio", "string", "apresentação curta"),
     P("ativo", "boolean", "false desativa")], nivel="escrita", ok=201, por="chave")
def _salvar_prof(bd, c, a):
    return {"id": n.salvar_profissional(bd, c["id"], a)}


@op("salvar_servico", "Cria um serviço (sem id) ou atualiza (com id): nome, duração em minutos, preço em centavos (opcional).", "POST", "/servicos",
    [P("id", "integer", "id (atualizar)"), P("nome", "string", "nome do serviço"), P("duracao_min", "integer", "duração em minutos (5 a 480)"),
     P("preco_centavos", "integer", "preço em centavos; vazio = não exibir"), P("ativo", "boolean", "false desativa")],
    nivel="escrita", ok=201, por="chave")
def _salvar_serv(bd, c, a):
    if not a.get("id") and not a.get("duracao_min"):
        raise n.Erro(422, "duracao_min_obrigatorio", "informe duracao_min")
    return {"id": n.salvar_servico(bd, c["id"], a)}


@op("definir_disponibilidade", "Define TODA a agenda semanal de um profissional (substitui a anterior): lista de janelas "
    "{dia 0=dom..6=sáb, inicio 'HH:MM', fim 'HH:MM', local_id}. Uma janela por local e dia; não podem se sobrepor.",
    "PUT", "/profissionais/{profissional_id}/disponibilidade",
    [P("profissional_id", "integer", "id do profissional", True), P("janelas", "array", "lista de janelas", True)], nivel="escrita", por="chave")
def _def_disp(bd, c, a):
    return {"disponibilidade": n.definir_disponibilidade(bd, c["id"], a["profissional_id"], a["janelas"])}


@op("configurar_clinica", "Atualiza os dados da clínica: nome, descrição, telefone, e-mail, cidade, fuso, passo entre horários (min) "
    "e antecedência mínima para agendar (min).", "PATCH", "/clinica",
    [P("nome", "string", "nome"), P("descricao", "string", "descrição"), P("telefone", "string", "telefone"), P("email", "string", "e-mail"),
     P("cidade", "string", "cidade"), P("tz", "string", "fuso IANA, ex.: America/Sao_Paulo"),
     P("passo_min", "integer", "10, 15, 20, 30, 45 ou 60"), P("antecedencia_min", "integer", "minutos de antecedência mínima")],
    nivel="escrita", por="chave")
def _config(bd, c, a):
    n.salvar_clinica(bd, c, a)
    return n.info_publica(bd, n.clinica_por_slug(bd, c["slug"]))["clinica"]


@op("whatsapp_status", "Estado do lembrete por WhatsApp (Evolution) da clínica: se o servidor tem Evolution, se está ligado, se a instância está conectada, "
    "quantos lembretes por status e o AVISO DE RISCO (número não oficial pode ser banido; só sai lembrete para quem agendou).",
    "GET", "/whatsapp", [], nivel="leitura", por="chave")
def _wa_status(bd, c, a):
    return lem.estado(bd, c)


@op("whatsapp_configurar", "Liga/desliga e configura o lembrete por WhatsApp da clínica pela instância do Evolution que a clínica conectou. "
    "NÃO existe operação para mandar mensagem a um número: os lembretes saem sozinhos, só para quem agendou (1 confirmação e 1 lembrete por consulta, com link "
    "para não receber mais). Para LIGAR é obrigatório aceito_risco=true: o Evolution é não oficial e o WhatsApp pode banir o número; use um número só da clínica "
    "e nunca para divulgação ou spam.", "PATCH", "/whatsapp",
    [P("ativo", "boolean", "ligar ou desligar os lembretes"), P("instancia", "string", "nome da instância do Evolution (3 a 40 letras, números, - ou _)"),
     P("lembrete_horas", "integer", "quantas horas antes da consulta (1 a 72; padrão 24)"),
     P("confirmacao", "boolean", "também mandar uma confirmação logo ao agendar"),
     P("aceito_risco", "boolean", "obrigatório para ligar: confirma que leu o aviso de risco")], nivel="escrita", por="chave")
def _wa_config(bd, c, a):
    return lem.configurar(bd, c, a.get("ativo"), a.get("instancia"), a.get("lembrete_horas"), a.get("confirmacao"), a.get("aceito_risco"))


@op("lembretes_listar", "Últimos lembretes de WhatsApp da clínica (status: pendente, enviado, falhou, cancelado), com o telefone mascarado. "
    "'enviado' significa aceito pelo Evolution, não que chegou no aparelho.", "GET", "/lembretes",
    [P("limite", "integer", "quantos (1 a 200; padrão 50)")], nivel="leitura", por="chave")
def _wa_lista(bd, c, a):
    return {"lembretes": lem.lista(bd, c, a.get("limite") or 50)}


# ---------------------------------------------------------------- consumidores da tabela

def _json_schema(params: list[dict]) -> dict:
    tipos = {"integer": {"type": "integer"}, "string": {"type": "string"}, "boolean": {"type": "boolean"},
             "array": {"type": "array", "items": {"type": "object"}}}
    return {"type": "object", "properties": {p["nome"]: {**tipos[p["tipo"]], "description": p["desc"]} for p in params},
            "required": [p["nome"] for p in params if p["obrig"]]}


def ferramentas_mcp(auth: tuple | None) -> list[dict]:
    nivel = NIVEL[auth[1] if auth else "publico"]
    return [{"name": o["nome"], "description": o["desc"], "inputSchema": _json_schema(o["params"]),
             "annotations": {"readOnlyHint": o["metodo"] == "GET", "destructiveHint": o["metodo"] == "DELETE"}}
            for o in OPS.values() if NIVEL[o["nivel"]] <= nivel]


def rota(metodo: str, caminho: str) -> tuple[dict, dict] | None:
    """(operação, parâmetros do caminho) para METODO /caminho (sem o prefixo /api/v1)."""
    for o in OPS.values():
        if o["metodo"] != metodo:
            continue
        m = re.fullmatch(re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", o["caminho"]), caminho)
        if m:
            return o, m.groupdict()
    return None


def openapi(servidor: str) -> dict:
    paths: dict = {}
    for o in OPS.values():
        em_caminho = set(re.findall(r"\{(\w+)\}", o["caminho"]))
        corpo = o["metodo"] in ("POST", "PUT", "PATCH")
        parametros = [{"name": p["nome"], "in": "path", "required": True, "description": p["desc"], "schema": {"type": "string"}}
                      for p in o["params"] if p["nome"] in em_caminho]
        resto = [p for p in o["params"] if p["nome"] not in em_caminho]
        if not corpo:
            parametros += [{"name": p["nome"], "in": "query", "required": p["obrig"], "description": p["desc"],
                            "schema": _json_schema([p])["properties"][p["nome"]]} for p in resto]
        item: dict = {"operationId": o["nome"], "summary": o["desc"], "parameters": parametros,
                      "responses": {str(o["ok"]): {"description": "ok"}, "4XX": {"description": "erro: {erro:{codigo,mensagem}}"}}}
        if corpo and resto:
            item["requestBody"] = {"required": True, "content": {"application/json": {"schema": _json_schema(resto)}}}
        if o["nivel"] != "publico":
            item["security"] = [{"chave": []}]
            item["description"] = f"Exige chave de API com escopo '{o['nivel']}'."
        paths.setdefault("/api/v1" + o["caminho"], {})[o["metodo"].lower()] = item
    return {"openapi": "3.1.0", "info": {"title": "agenda-clinica", "version": "1.0.0",
            "description": "Agendamento online para clínicas. Também disponível como servidor MCP em /mcp."},
            "servers": [{"url": servidor}], "paths": paths,
            "components": {"securitySchemes": {"chave": {"type": "http", "scheme": "bearer", "description": "chave ac_... criada no painel"}}}}


def llms_txt(servidor: str) -> str:
    linhas = [f"# agenda-clinica ({servidor})", "",
              "> Site de clínica com agendamento online. Código aberto, grátis. Agentes: API REST e servidor MCP.", "",
              f"- MCP (Streamable HTTP, JSON-RPC): POST {servidor}/mcp",
              f"- OpenAPI: {servidor}/openapi.json", f"- Guia: {servidor}/docs", "",
              "Operações públicas (sem chave): " + ", ".join(o["nome"] for o in OPS.values() if o["nivel"] == "publico") + ".",
              "Operações com chave de API (Authorization: Bearer ac_...): " + ", ".join(o["nome"] for o in OPS.values() if o["nivel"] != "publico") + ".", "",
              "Fluxo: clinica_info -> horarios_livres -> agendar (guarde o `codigo`) -> ver_consulta / cancelar_consulta / remarcar_consulta.",
              "Nunca invente horário: só agende um que horarios_livres devolveu. Só sai mensagem se a clínica ligou o WhatsApp (whatsapp_status), e só lembrete de consulta real."]
    return "\n".join(linhas) + "\n"
