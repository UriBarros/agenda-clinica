"""HTML do agenda-clinica: site público da clínica, agendamento, página do paciente e painel.

Sem JavaScript de propósito: o agendamento é uma sequência de links e formulários. Funciona em qualquer
celular, no leitor de tela e para o agente que só lê HTML, e a CSP do servidor proíbe script.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import urllib.parse

import nucleo as n
import ops

e = html.escape
DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
CSS = """
:root{--bg:#f6f8f8;--cartao:#fff;--tinta:#16302f;--mudo:#587170;--linha:#d8e3e2;--c:#0f766e;--c2:#0b5a54;--aviso:#fff4d6;--erro:#b42318;--ok:#067647}
@media(prefers-color-scheme:dark){:root{--bg:#0e1a19;--cartao:#142423;--tinta:#e6f1f0;--mudo:#93aeac;--linha:#27403e;--c:#2dd4bf;--c2:#5eead4;--aviso:#3b3115;--erro:#f97066;--ok:#47cd89}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tinta);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--c)}main{max-width:900px;margin:0 auto;padding:20px 16px 56px}h1{font-size:1.9rem;line-height:1.2;margin:.2em 0}h2{font-size:1.25rem;margin:1.6em 0 .5em}
header.topo{background:var(--cartao);border-bottom:1px solid var(--linha)}header.topo div{max-width:900px;margin:0 auto;padding:12px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header.topo b{font-size:1.05rem;margin-right:auto}header.topo a{text-decoration:none;font-weight:600}
.cartao{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:16px;margin:12px 0}.grade{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.mudo{color:var(--mudo);font-size:.92rem}.hero{padding:28px 0 8px}.hero p{font-size:1.12rem;max-width:640px}
.btn,button{display:inline-block;background:var(--c);color:#fff;border:0;border-radius:10px;padding:11px 18px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}
@media(prefers-color-scheme:dark){.btn,button{color:#04211e}}.sec{background:transparent!important;color:var(--c)!important;border:1px solid var(--c)}.perigo{background:transparent!important;color:var(--erro)!important;border:1px solid var(--erro)}
label{display:block;margin:10px 0 4px;font-weight:600;font-size:.95rem}input,select,textarea{width:100%;padding:10px;border:1px solid var(--linha);border-radius:10px;background:var(--bg);color:var(--tinta);font:inherit}
input[type=checkbox]{width:auto}.linha{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.linha>*{flex:1 1 140px}.linha .fixo{flex:0 0 auto}
.horas{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 14px}.horas a,.horas button{padding:8px 13px;border-radius:9px;background:var(--cartao);color:var(--c);border:1px solid var(--c);text-decoration:none;font-weight:600}
.aviso{background:var(--aviso);border-radius:12px;padding:12px 14px;margin:12px 0}.erro{color:var(--erro);font-weight:600}.ok{color:var(--ok);font-weight:600}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--linha);vertical-align:top}th{font-size:.85rem;color:var(--mudo)}
code,pre{background:var(--cartao);border:1px solid var(--linha);border-radius:8px;padding:2px 6px;font-size:.88rem}pre{padding:12px;overflow:auto}
.pill{display:inline-block;border-radius:99px;padding:1px 9px;font-size:.8rem;border:1px solid var(--linha)}footer{margin-top:40px;color:var(--mudo);font-size:.88rem}
form.in{display:inline}.sr{position:absolute;left:-9999px}
"""


def pagina(titulo: str, corpo: str, *, desc: str = "", canonical: str = "", indexar: bool = True, nav: str = "", marca: str = "agenda-clinica",
           home: str = "/", extra_head: str = "") -> str:
    meta = f'<meta name="description" content="{e(desc)}">' if desc else ""
    meta += f'<link rel="canonical" href="{e(canonical)}">' if canonical else ""
    meta += "" if indexar else '<meta name="robots" content="noindex">'
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(titulo)}</title>{meta}{extra_head}<style>{CSS}</style></head><body>'
            f'<header class="topo"><div><b><a href="{e(home)}" style="color:inherit">{e(marca)}</a></b>{nav}</div></header>'
            f'<main>{corpo}</main></body></html>')


def brl(centavos) -> str:
    return "" if centavos is None else f"R$ {centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{DIAS[n.dia_semana(d)][:3]} {d.day:02d}/{d.month:02d}"


def _erro(msg: str) -> str:
    return f'<p class="erro" role="alert">{e(msg)}</p>' if msg else ""


# ------------------------------------------------------------------ raiz

def home(repo_url: str, demo: bool, erro: str = "") -> str:
    return pagina("agenda-clinica — site de clínica com agendamento online, grátis e aberto", f"""
<section class="hero"><h1>Site de clínica com agendamento online. Grátis, de código aberto.</h1>
<p>Páginas para a clínica e cada profissional, vários locais, agenda por horário livre, painel com login para bloquear a agenda,
cancelar e remarcar. Sem mensalidade, sem anúncio. E <b>API e servidor MCP</b> para agentes de IA agendarem e gerirem a agenda.</p></section>
<div class="grade">
<div class="cartao"><b>Para o paciente</b><p class="mudo">Escolhe serviço, profissional e horário livre no celular, sem criar conta. Recebe um código para consultar, cancelar ou remarcar.</p></div>
<div class="cartao"><b>Para a clínica</b><p class="mudo">Painel com login: agenda do dia, bloqueio de férias e folgas, cancelar e remarcar, equipe, locais e horários semanais.</p></div>
<div class="cartao"><b>Para agentes</b><p class="mudo">API REST (<a href="/openapi.json">OpenAPI</a>) e MCP em <code>/mcp</code>. Veja o <a href="/docs">guia</a> e o <a href="/llms.txt">llms.txt</a>.</p></div></div>
<h2 id="criar">Criar minha clínica</h2>{_erro(erro)}
<form method="post" action="/criar" class="cartao"><label>Nome da clínica<input name="nome" required maxlength="100"></label>
<label>E-mail (será o login)<input name="email" type="email" required></label>
<label>Senha (mínimo 10 caracteres)<input name="senha" type="password" minlength="10" required autocomplete="new-password"></label>
<p class="mudo">Ao criar, você aceita a <a href="/privacidade">política de privacidade</a>. Não guardamos dado clínico: só nome, telefone e e-mail de quem agenda.</p>
<button>Criar grátis</button></form>
{'<p><a href="/c/demo">Ver uma clínica de demonstração</a> (dados fictícios; agentes podem testar a API nela).</p>' if demo else ''}
<footer>Código-fonte: <a href="{e(repo_url)}">{e(repo_url)}</a> · <a href="/privacidade">Privacidade</a></footer>""",
        desc="Site de clínica com agendamento online grátis e de código aberto: profissionais, locais, painel com login, API REST e MCP para agentes.",
        nav='<a href="/docs">Para agentes</a><a href="/entrar">Entrar</a>')


def privacidade() -> str:
    return pagina("Privacidade — agenda-clinica", """<h1>Privacidade</h1>
<p>Este serviço guarda apenas o necessário para marcar uma consulta: <b>nome</b>, <b>telefone</b> e, se você informar, <b>e-mail</b>,
junto da data, do horário, do serviço e do profissional. <b>Não guardamos dado clínico</b> (sintomas, exames, prontuário): não escreva isso nos campos.</p>
<p>Esses dados são visíveis para a clínica em que você agendou e para quem tiver o código da sua consulta. Não são vendidos nem usados para
publicidade. Para corrigir ou apagar seus dados, peça à clínica; quem opera o serviço atende a clínica pelo e-mail dela.</p>
<p>A clínica é a controladora dos dados dos próprios pacientes (LGPD, art. 5º, VI); este software é a ferramenta. O código é aberto e pode ser auditado.</p>
<p>Este sistema <b>não envia mensagens</b> (e-mail ou WhatsApp): quem avisa o paciente de cancelamentos e remarcações é a clínica.</p>""", nav='<a href="/">Início</a>')


# ------------------------------------------------------------------ site da clínica

def site_clinica(info: dict, base: str) -> str:
    c = info["clinica"]
    ld = {"@context": "https://schema.org", "@type": "MedicalClinic", "name": c["nome"], "url": f"{base}/c/{c['slug']}",
          "description": c["descricao"] or None, "telephone": c["telefone"] or None, "email": c["email"] or None,
          "location": [{"@type": "Place", "name": l["nome"], "address": ", ".join(x for x in (l["endereco"], l["cidade"]) if x)} for l in info["locais"]],
          "employee": [{"@type": "Person", "name": p["nome"], "jobTitle": p["especialidade"] or None} for p in info["profissionais"]]}
    # `<` vira \u003c: com só `</` escapado, um nome "<!--<script>" fazia o parser engolir o `</script>` real e o resto da página.
    ld = json.dumps({k: v for k, v in ld.items() if v}, ensure_ascii=False).replace("<", "\\u003c")
    locais = {l["id"]: l for l in info["locais"]}
    profs = ""
    for p in info["profissionais"]:
        semana = {}
        for j in p["disponibilidade"]:
            semana.setdefault(j["local_id"], []).append(f"{DIAS[j['dia']][:3]} {j['inicio']}–{j['fim']}")
        onde = "".join(f"<div class='mudo'><b>{e(locais[i]['nome'])}</b>: {e(', '.join(t))}</div>" for i, t in semana.items() if i in locais)
        profs += (f"<div class='cartao'><b>{e(p['nome'])}</b><div class='mudo'>{e(p['especialidade'])} {('· ' + e(p['registro'])) if p['registro'] else ''}</div>"
                  f"<p>{e(p['bio'])}</p>{onde}</div>")
    servs = "".join(f"<tr><td>{e(s['nome'])}</td><td>{s['duracao_min']} min</td><td>{e(brl(s['preco_centavos']))}</td>"
                    f"<td><a href='/c/{e(c['slug'])}/agendar?servico={s['id']}'>Agendar</a></td></tr>" for s in info["servicos"])
    locs = "".join(f"<div class='cartao'><b>{e(l['nome'])}</b><div class='mudo'>{e(l['endereco'])} {e(l['cidade'])}</div></div>" for l in info["locais"])
    wa = f"<p><a class='btn sec' href='https://wa.me/{e(_so_digitos(c['telefone']))}'>Falar pelo WhatsApp</a></p>" if _so_digitos(c["telefone"]) else ""
    return pagina(f"{c['nome']} — agende online", f"""<section class="hero"><h1>{e(c['nome'])}</h1><p>{e(c['descricao'])}</p>
<p><a class="btn" href="/c/{e(c['slug'])}/agendar">Agendar consulta</a></p></section>
<h2>Profissionais</h2><div class="grade">{profs or "<p class='mudo'>Em breve.</p>"}</div>
<h2>Serviços</h2><div class="cartao"><table><tr><th>Serviço</th><th>Duração</th><th>Valor</th><th></th></tr>{servs}</table></div>
<h2>Onde atendemos</h2><div class="grade">{locs}</div>{wa}
<footer>Agendamento por <a href="/">agenda-clinica</a>, software livre.</footer>""",
        desc=f"{c['nome']}{' em ' + c['cidade'] if c['cidade'] else ''}: conheça os profissionais e agende online.",
        canonical=f"{base}/c/{c['slug']}" if c.get("indexavel") else "", indexar=bool(c.get("indexavel")),
        marca=c["nome"], home=f"/c/{c['slug']}",
        extra_head=f'<script type="application/ld+json">{ld}</script>',
        nav=f'<a href="/c/{e(c["slug"])}/agendar">Agendar</a>')


def _so_digitos(t: str) -> str:
    d = "".join(ch for ch in str(t or "") if ch.isdigit())
    return ("55" + d) if len(d) in (10, 11) else d


def agendar(info: dict, horarios: list[dict], q: dict, erro: str = "") -> str:
    c, slug = info["clinica"], info["clinica"]["slug"]
    profs = {p["id"]: p for p in info["profissionais"]}
    locais = {l["id"]: l for l in info["locais"]}
    serv = next((s for s in info["servicos"] if str(s["id"]) == q.get("servico")), None)
    base = f"/c/{e(slug)}/agendar"
    nav = f'<a href="/c/{e(slug)}">Voltar ao site</a>'
    if not serv:
        itens = "".join(f"<a class='cartao' style='display:block;text-decoration:none' href='{base}?servico={s['id']}'><b>{e(s['nome'])}</b>"
                        f"<div class='mudo'>{s['duracao_min']} min {e(brl(s['preco_centavos']))}</div></a>" for s in info["servicos"])
        return pagina(f"Agendar — {c['nome']}", f"<h1>Qual serviço?</h1>{_erro(erro)}<div class='grade'>{itens or '<p>Esta clínica ainda não cadastrou serviços.</p>'}</div>",
                      # A /agendar BASE é indexável (decisão do dono: "indexa tudo"); com parâmetro (serviço, horário) ou erro
                      # é combinação infinita de URLs sem conteúdo próprio, e a página do paciente (/m/) é dado pessoal: noindex.
                      indexar=not q and not erro, marca=c["nome"], home=f"/c/{slug}", nav=nav)
    if q.get("hora") and q.get("data") and q.get("profissional"):
        p = profs.get(int(q["profissional"])) if q["profissional"].isascii() and q["profissional"].isdigit() else None
        loc = next((h for h in horarios if h["data"] == q["data"] and h["hora"] == q["hora"] and str(h["profissional_id"]) == q["profissional"]), None)
        if not p or not loc:
            return agendar(info, horarios, {"servico": q["servico"]}, "Esse horário não está mais livre. Escolha outro.")
        return pagina(f"Confirmar — {c['nome']}", f"""<h1>Confirmar agendamento</h1>{_erro(erro)}
<div class="cartao"><b>{e(serv['nome'])}</b> com <b>{e(p['nome'])}</b><br>{e(data_br(q['data']))} às {e(q['hora'])} · {e(locais[loc['local_id']]['nome'])}
<div class="mudo">{e(locais[loc['local_id']]['endereco'])}</div></div>
<form method="post" action="/c/{e(slug)}/agendar" class="cartao">
<input type="hidden" name="servico" value="{serv['id']}"><input type="hidden" name="profissional" value="{p['id']}"><input type="hidden" name="data" value="{e(q['data'])}"><input type="hidden" name="hora" value="{e(q['hora'])}">
<label>Seu nome<input name="nome" required maxlength="100" autocomplete="name"></label>
<label>Telefone com DDD<input name="telefone" required inputmode="tel" autocomplete="tel" placeholder="(48) 99999-0000"></label>
<label>E-mail (opcional)<input name="email" type="email" autocomplete="email"></label>
<p><label style="font-weight:400"><input type="checkbox" name="consentimento" value="1" required> Autorizo a clínica a usar meu nome e telefone para este agendamento
(<a href="/privacidade">privacidade</a>). Não escreva informações de saúde aqui.</label></p>
<button>Confirmar</button></form>""", indexar=False, marca=c["nome"], home=f"/c/{slug}", nav=nav)
    filtro = q.get("profissional", "")
    links = f"<a class='pill' href='{base}?servico={serv['id']}'>Qualquer profissional</a> " + " ".join(
        f"<a class='pill' href='{base}?servico={serv['id']}&amp;profissional={p['id']}'>{e(p['nome'])}</a>" for p in info["profissionais"])
    dias: dict = {}
    for h in horarios:
        if not filtro or str(h["profissional_id"]) == filtro:
            dias.setdefault((h["data"], h["profissional_id"], h["local_id"]), []).append(h["hora"])
    corpo = ""
    for (d, pid, lid), horas in dias.items():
        qs = lambda hr: urllib.parse.urlencode({"servico": serv["id"], "profissional": pid, "data": d, "hora": hr})
        corpo += (f"<div><b>{e(data_br(d))}</b> · {e(profs[pid]['nome'])} · <span class='mudo'>{e(locais[lid]['nome'])}</span><div class='horas'>"
                  + "".join(f"<a href='{base}?{e(qs(hr))}'>{e(hr)}</a>" for hr in horas) + "</div></div>")
    return pagina(f"Horários — {c['nome']}", f"""<h1>{e(serv['nome'])}</h1><p class="mudo">Próximos 14 dias · {serv['duracao_min']} min</p>
<p>{links}</p>{_erro(erro)}{corpo or "<p class='aviso'>Sem horários livres nos próximos 14 dias para essa escolha. Tente outro profissional ou fale com a clínica.</p>"}""",
                  indexar=False, marca=c["nome"], home=f"/c/{slug}", nav=nav)


def agendado(info: dict, ag: dict, base: str) -> str:
    c = info["clinica"]
    wa = (f"<p><a class='btn sec' href='https://wa.me/{e(_so_digitos(c['telefone']))}'>Falar com a clínica</a></p>" if _so_digitos(c["telefone"]) else "")
    return pagina(f"Agendado — {c['nome']}", f"""<h1 class="ok">Agendado!</h1>
<div class="cartao"><b>{e(ag['servico'])}</b> com <b>{e(ag['profissional'])}</b><br>{e(data_br(ag['data']))} às {e(ag['hora'])}<br>{e(ag['local'])} · {e(ag['endereco'])}</div>
<div class="aviso"><b>Guarde este link</b> para consultar, cancelar ou remarcar:<br><a href="/m/{e(ag['codigo'])}">{e(base)}/m/{e(ag['codigo'])}</a><br>
<span class="mudo">Código: <code>{e(ag['codigo'])}</code>. A clínica não envia mensagem automática: guarde o código.</span></div>{wa}""",
                  indexar=False, marca=c["nome"], home=f"/c/{c['slug']}")


def consulta(ag: dict, clinica: dict, erro: str = "") -> str:
    ativo = ag["status"] == "confirmado"
    return pagina(f"Sua consulta — {clinica['nome']}", f"""<h1>Sua consulta</h1>{_erro(erro)}
<div class="cartao"><b>{e(ag['servico'])}</b> com <b>{e(ag['profissional'])}</b><br>{e(data_br(ag['data']))} às {e(ag['hora'])}<br>{e(ag['local'])} · {e(ag['endereco'])}<br>
<span class="pill">{'confirmada' if ativo else 'cancelada'}</span></div>
{f'''<div class="linha"><a class="btn sec fixo" href="/m/{e(ag['codigo'])}/remarcar">Remarcar</a>
<form method="post" action="/m/{e(ag['codigo'])}/cancelar" class="in"><button class="perigo">Cancelar consulta</button></form></div>''' if ativo else ''}""",
                  indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}")


def remarcar_paciente(ag: dict, clinica: dict, horarios: list[dict], profs: dict, erro: str = "") -> str:
    corpo = ""
    for h in horarios:
        corpo += (f"<form method='post' action='/m/{e(ag['codigo'])}/remarcar' class='in'><input type='hidden' name='data' value='{e(h['data'])}'>"
                  f"<input type='hidden' name='hora' value='{e(h['hora'])}'><input type='hidden' name='profissional' value='{h['profissional_id']}'>"
                  f"<button class='sec' style='margin:3px'>{e(data_br(h['data']))} {e(h['hora'])} · {e(profs.get(h['profissional_id'], ''))}</button></form>")
    return pagina(f"Remarcar — {clinica['nome']}", f"<h1>Remarcar</h1>{_erro(erro)}<p class='mudo'>Escolha o novo horário:</p>{corpo or '<p class=aviso>Sem horários livres nos próximos 14 dias.</p>'}",
                  indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}")


# ------------------------------------------------------------------ painel

def _csrf(tok: str) -> str:
    return f'<input type="hidden" name="csrf" value="{e(n.csrf_de(tok))}">'


def entrar(erro: str = "") -> str:
    return pagina("Entrar — agenda-clinica", f"""<h1>Entrar</h1>{_erro(erro)}<form method="post" action="/entrar" class="cartao">
<label>E-mail<input name="email" type="email" required autocomplete="username"></label>
<label>Senha<input name="senha" type="password" required autocomplete="current-password"></label><button>Entrar</button></form>
<p class="mudo">Ainda não tem clínica? <a href="/#criar">Crie grátis</a>.</p>""", indexar=False)


def _nav_painel(c) -> str:
    return (f'<a href="/painel">Agenda</a><a href="/painel/equipe">Equipe e horários</a><a href="/painel/api">Agentes e API</a>'
            f'<a href="/c/{e(c["slug"])}">Ver site</a><a href="/sair">Sair</a>')


def painel(c, tok: str, dia: dt.date, ags: list[dict], bloqueios: list[dict], profs: list[dict], msg: str = "", erro: str = "") -> str:
    ant, prox = dia - dt.timedelta(days=1), dia + dt.timedelta(days=1)
    linhas = ""
    for a in ags:
        ativo = a["status"] == "confirmado"
        tel = _so_digitos(a["paciente_telefone"])
        acoes = (f"<a href='https://wa.me/{e(tel)}' target='_blank' rel='noopener'>WhatsApp</a> · <a href='/painel/remarcar?id={a['id']}'>Remarcar</a> "
                 f"<form method='post' action='/painel/acao' class='in'>{_csrf(tok)}<input type='hidden' name='acao' value='cancelar'><input type='hidden' name='id' value='{a['id']}'>"
                 f"<input type='hidden' name='volta' value='/painel?data={dia.isoformat()}'><button class='perigo' style='padding:3px 9px'>Cancelar</button></form>") if ativo else "<span class='pill'>cancelada</span>"
        linhas += (f"<tr><td><b>{e(a['hora'])}</b>–{e(a['fim'])}</td><td>{e(a['paciente_nome'])}<div class='mudo'>{e(a['paciente_telefone'])}</div></td>"
                   f"<td>{e(a['servico'])}<div class='mudo'>{e(a['profissional'])} · {e(a['local'])}</div></td><td>{acoes}</td></tr>")
    opts = "<option value=''>Clínica toda</option>" + "".join(f"<option value='{p['id']}'>{e(p['nome'])}</option>" for p in profs)
    bl = "".join(f"<tr><td>{e(b['inicio'].replace('T', ' '))} → {e(b['fim'].replace('T', ' '))}</td><td>{e(next((p['nome'] for p in profs if p['id'] == b['profissional_id']), 'Clínica toda'))}</td>"
                 f"<td>{e(b['motivo'])}</td><td><form method='post' action='/painel/acao' class='in'>{_csrf(tok)}<input type='hidden' name='acao' value='remover_bloqueio'>"
                 f"<input type='hidden' name='id' value='{b['id']}'><button class='sec' style='padding:3px 9px'>Remover</button></form></td></tr>" for b in bloqueios)
    return pagina(f"Agenda — {c['nome']}", f"""<h1>{e(c['nome'])}</h1>{f'<p class="ok">{e(msg)}</p>' if msg else ''}{_erro(erro)}
<div class="linha"><a class="btn sec fixo" href="/painel?data={ant}">← {ant.day:02d}/{ant.month:02d}</a><form method="get" action="/painel" class="linha"><input type="date" name="data" value="{dia}"><button class="fixo sec">Ir</button></form>
<a class="btn sec fixo" href="/painel?data={prox}">{prox.day:02d}/{prox.month:02d} →</a></div>
<h2>{e(DIAS[n.dia_semana(dia)].capitalize())}, {dia.day:02d}/{dia.month:02d}/{dia.year}</h2>
<div class="cartao">{f'<table><tr><th>Hora</th><th>Paciente</th><th>Serviço</th><th></th></tr>{linhas}</table>' if linhas else "<p class='mudo'>Nenhuma consulta neste dia.</p>"}</div>
<h2>Bloquear agenda</h2><form method="post" action="/painel/acao" class="cartao">{_csrf(tok)}<input type="hidden" name="acao" value="bloquear"><input type="hidden" name="volta" value="/painel?data={dia}">
<div class="linha"><label>Quem<select name="profissional_id">{opts}</select></label><label>De<input type="datetime-local" name="inicio" value="{dia}T08:00" required></label>
<label>Até<input type="datetime-local" name="fim" value="{dia}T18:00" required></label><label>Motivo<input name="motivo" maxlength="200" placeholder="férias, congresso..."></label></div>
<p><label style="font-weight:400"><input type="checkbox" name="cancelar_conflitos" value="1"> Se houver consultas nesse período, cancelá-las (você avisa os pacientes)</label></p><button>Bloquear</button></form>
{f'<h2>Bloqueios de hoje em diante</h2><div class="cartao"><table>{bl}</table></div>' if bl else ''}""", indexar=False, marca=c["nome"], home="/painel", nav=_nav_painel(c))


def remarcar_painel(c, tok: str, ag: dict, horarios: list[dict], profs: dict) -> str:
    corpo = "".join(f"<form method='post' action='/painel/acao' class='in'>{_csrf(tok)}<input type='hidden' name='acao' value='remarcar'><input type='hidden' name='id' value='{ag['id']}'>"
                    f"<input type='hidden' name='data' value='{e(h['data'])}'><input type='hidden' name='hora' value='{e(h['hora'])}'><input type='hidden' name='profissional_id' value='{h['profissional_id']}'>"
                    f"<input type='hidden' name='volta' value='/painel?data={e(h['data'])}'><button class='sec' style='margin:3px'>{e(data_br(h['data']))} {e(h['hora'])} · {e(profs.get(h['profissional_id'], ''))}</button></form>"
                    for h in horarios)
    return pagina(f"Remarcar — {c['nome']}", f"<h1>Remarcar {e(ag['paciente_nome'])}</h1><p class='mudo'>Atual: {e(data_br(ag['data']))} {e(ag['hora'])} · {e(ag['servico'])}. Escolha o novo horário (próximos 14 dias); depois avise o paciente.</p>{corpo or '<p class=aviso>Sem horários livres.</p>'}",
                  indexar=False, marca=c["nome"], home="/painel", nav=_nav_painel(c))


def equipe(c, tok: str, info: dict, msg: str = "", erro: str = "") -> str:
    locais = info["locais"]
    f = lambda acao, extra="": f'<form method="post" action="/painel/acao" class="cartao">{_csrf(tok)}<input type="hidden" name="acao" value="{acao}"><input type="hidden" name="volta" value="/painel/equipe">{extra}'
    lopts = lambda sel=0: "".join(f"<option value='{l['id']}' {'selected' if l['id'] == sel else ''}>{e(l['nome'])}</option>" for l in locais)
    dados = (f("clinica") + f"""<h3>Dados da clínica</h3><label>Nome<input name="nome" value="{e(c['nome'])}"></label><label>Apresentação<textarea name="descricao" rows="3">{e(c['descricao'])}</textarea></label>
<div class="linha"><label>Telefone (WhatsApp)<input name="telefone" value="{e(c['telefone'])}"></label><label>E-mail<input name="email" value="{e(c['email'])}"></label><label>Cidade<input name="cidade" value="{e(c['cidade'])}"></label></div>
<div class="linha"><label>Passo entre horários<select name="passo_min">{''.join(f"<option {'selected' if int(c['passo_min']) == v else ''}>{v}</option>" for v in (10, 15, 20, 30, 45, 60))}</select></label>
<label>Antecedência mínima (min)<input name="antecedencia_min" type="number" min="0" value="{c['antecedencia_min']}"></label></div><button>Salvar</button></form>""")
    locs = "".join(f"<div class='mudo'>• <b>{e(l['nome'])}</b> {e(l['endereco'])}</div>" for l in locais) + f(
        "salvar_local") + "<div class='linha'><label>Novo local<input name='nome' required></label><label>Endereço<input name='endereco'></label><label>Cidade<input name='cidade'></label><button class='fixo'>Adicionar</button></div></form>"
    servs = "".join(f"<div class='mudo'>• <b>{e(s['nome'])}</b> {s['duracao_min']} min {e(brl(s['preco_centavos']))}</div>" for s in info["servicos"]) + f(
        "salvar_servico") + "<div class='linha'><label>Novo serviço<input name='nome' required></label><label>Duração (min)<input name='duracao_min' type='number' value='30' min='5' max='480'></label><label>Preço (R$, opcional)<input name='preco' inputmode='decimal'></label><button class='fixo'>Adicionar</button></div></form>"
    profs = ""
    for p in info["profissionais"]:
        por_dia: dict = {}
        for j in p["disponibilidade"]:
            por_dia.setdefault(j["dia"], []).append(j)
        linhas = ""
        for d in range(7):
            for k in range(2):
                j = (por_dia.get(d) or [])[k:k + 1]
                j = j[0] if j else {"inicio": "", "fim": "", "local_id": 0}
                linhas += (f"<div class='linha'><span class='fixo' style='width:80px'>{DIAS[d][:3] if k == 0 else ''}</span><input type='time' name='i{d}_{k}' value='{e(j['inicio'])}' aria-label='início {DIAS[d]}'>"
                           f"<input type='time' name='f{d}_{k}' value='{e(j['fim'])}' aria-label='fim {DIAS[d]}'><select name='l{d}_{k}' aria-label='local {DIAS[d]}'>{lopts(j['local_id'])}</select></div>")
        profs += (f"<div class='cartao'><b>{e(p['nome'])}</b> <span class='mudo'>{e(p['especialidade'])}</span><details><summary>Horários semanais</summary>"
                  f"<form method='post' action='/painel/acao'>{_csrf(tok)}<input type='hidden' name='acao' value='disponibilidade'><input type='hidden' name='profissional_id' value='{p['id']}'>"
                  f"<input type='hidden' name='volta' value='/painel/equipe'><p class='mudo'>Até duas faixas por dia. Deixe em branco os dias sem atendimento.</p>{linhas}<button>Salvar horários</button></form></details></div>")
    novo_prof = f("salvar_profissional") + "<div class='linha'><label>Novo profissional<input name='nome' required></label><label>Especialidade<input name='especialidade'></label><label>Registro (CRM, CRP...)<input name='registro'></label><button class='fixo'>Adicionar</button></div></form>"
    return pagina(f"Equipe — {c['nome']}", f"<h1>Equipe, locais e serviços</h1>{f'<p class=ok>{e(msg)}</p>' if msg else ''}{_erro(erro)}{dados}<h2>Locais</h2>{locs}<h2>Serviços</h2>{servs}<h2>Profissionais</h2>{profs}{novo_prof}",
                  indexar=False, marca=c["nome"], home="/painel", nav=_nav_painel(c))


def painel_api(c, tok: str, chaves: list[dict], base: str, nova: dict | None = None, erro: str = "") -> str:
    caixa = (f"<div class='aviso'><b>Chave criada (aparece só agora):</b><br><code style='word-break:break-all'>{e(nova['chave'])}</code></div>" if nova else "")
    linhas = "".join(f"<tr><td>{e(k['nome'])}</td><td><code>ac_{e(k['prefixo'])}…</code></td><td>{e(k['escopo'])}</td><td>{e(k['ultimo_uso'] or 'nunca usada')}</td>"
                     f"<td><form method='post' action='/painel/acao' class='in'>{_csrf(tok)}<input type='hidden' name='acao' value='revogar_chave'><input type='hidden' name='id' value='{k['id']}'>"
                     f"<input type='hidden' name='volta' value='/painel/api'><button class='perigo' style='padding:3px 9px'>Revogar</button></form></td></tr>" for k in chaves)
    cfg = json.dumps({"mcpServers": {"agenda-clinica": {"type": "http", "url": f"{base}/mcp", "headers": {"Authorization": "Bearer ac_SUA_CHAVE"}}}}, indent=2)
    return pagina(f"Agentes — {c['nome']}", f"""<h1>Agentes e API</h1>{_erro(erro)}{caixa}
<p>Qualquer agente (Claude, ChatGPT, scripts) pode agendar e gerir esta clínica por <b>MCP</b> ou <b>REST</b>. Sem chave, o agente só vê horários e agenda; com chave, ele lista, cancela, remarca e bloqueia.</p>
<h2>Chaves de API</h2><div class="cartao">{f'<table><tr><th>Nome</th><th>Chave</th><th>Escopo</th><th>Último uso</th><th></th></tr>{linhas}</table>' if linhas else "<p class='mudo'>Nenhuma chave ainda.</p>"}</div>
<form method="post" action="/painel/acao" class="cartao">{_csrf(tok)}<input type="hidden" name="acao" value="criar_chave"><input type="hidden" name="volta" value="/painel/api">
<div class="linha"><label>Nome<input name="nome" placeholder="meu agente" required></label><label>Escopo<select name="escopo"><option value="leitura">leitura (só consulta)</option><option value="escrita">escrita (cancela, remarca, bloqueia, configura)</option></select></label><button class="fixo">Criar chave</button></div></form>
<h2>Conectar um agente (MCP)</h2><pre>{e(cfg)}</pre><p class="mudo">Endereço do MCP: <code>{e(base)}/mcp</code> · OpenAPI: <a href="/openapi.json">{e(base)}/openapi.json</a> · <a href="/docs">guia completo</a>. Sua clínica: <code>{e(c['slug'])}</code>.</p>
<div class="aviso">Trate a chave como senha: quem a tem acessa nomes e telefones dos pacientes. Revogue no primeiro sinal de vazamento.</div>""",
                  indexar=False, marca=c["nome"], home="/painel", nav=_nav_painel(c))


def docs(base: str) -> str:
    linhas = "".join(f"<tr><td><code>{e(o['nome'])}</code></td><td><code>{o['metodo']} /api/v1{e(o['caminho'])}</code></td><td>{'público' if o['nivel'] == 'publico' else 'chave: ' + o['nivel']}</td><td>{e(o['desc'])}</td></tr>" for o in ops.OPS.values())
    cfg = json.dumps({"mcpServers": {"agenda-clinica": {"type": "http", "url": f"{base}/mcp"}}}, indent=2)
    return pagina("Guia para agentes — agenda-clinica", f"""<h1>Guia para agentes</h1>
<p>Cada operação existe como <b>ferramenta MCP</b> e como <b>endpoint REST</b>, a partir da mesma definição. Sem chave: <code>clinica_info</code>, <code>horarios_livres</code>,
<code>agendar</code> e a gestão da consulta pelo código. Com chave (<code>Authorization: Bearer ac_...</code>, criada no painel): listar, cancelar, remarcar, bloquear e configurar.</p>
<h2>MCP</h2><pre>{e(cfg)}</pre><p class="mudo">Transporte HTTP (JSON-RPC 2.0) em <code>POST {e(base)}/mcp</code>; sem sessão e sem streaming.</p>
<h2>REST</h2><pre>curl '{e(base)}/api/v1/clinicas/demo/horarios?servico_id=1&amp;de=2026-11-10'
curl -X POST {e(base)}/api/v1/clinicas/demo/agendamentos -H 'content-type: application/json' \\
  -d '{{"servico_id":1,"profissional_id":1,"data":"2026-11-10","hora":"09:00","nome":"Maria","telefone":"48999990000","consentimento":true}}'</pre>
<p>Erros: <code>{{"erro":{{"codigo":"horario_indisponivel","mensagem":"..."}}}}</code> com o status HTTP correspondente (409 = horário tomado, consulte de novo).</p>
<h2>Regras para o agente</h2><ul><li>Só agende um horário que <code>horarios_livres</code> devolveu.</li><li>Só envie <code>consentimento: true</code> se o paciente concordou.</li>
<li>O sistema não envia mensagens: ao cancelar ou remarcar, avise o paciente por outro canal.</li><li>Não grave dado clínico nos campos.</li></ul>
<h2>Operações</h2><div class="cartao" style="overflow:auto"><table><tr><th>Ferramenta</th><th>REST</th><th>Acesso</th><th>O que faz</th></tr>{linhas}</table></div>
<p><a href="/openapi.json">openapi.json</a> · <a href="/llms.txt">llms.txt</a></p>""", desc="API REST e servidor MCP do agenda-clinica para agentes de IA.", canonical=f"{base}/docs", nav='<a href="/">Início</a>')
