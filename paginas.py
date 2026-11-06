"""HTML do agenda-clinica: site público da clínica, agendamento, página do paciente e painel.

Sem JavaScript de propósito: o agendamento é uma sequência de links e formulários. Funciona em qualquer
celular, no leitor de tela e para o agente que só lê HTML, e a CSP do servidor proíbe script.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import urllib.parse
from pathlib import Path

import nucleo as n
import ops

e = html.escape

# Fotos de fundo (Unsplash e Pexels, licenças de uso livre), servidas do NOSSO domínio com crédito (ADR-001): nada de hotlink,
# nada de terceiro vendo o IP do paciente. Cada clínica ganha uma foto estável pelo endereço dela (mesma entrada, mesma foto).
FUNDOS_DIR = Path(__file__).resolve().parent / "static" / "fundos"
POOL = ["acolhimento", "clinica-clara", "consulta", "conversa", "minimalista", "moderna", "nutricao", "psicologia", "recepcao", "spa"]
try:
    CREDITOS = json.loads((FUNDOS_DIR.parent / "creditos.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    CREDITOS = {}


# Cada foto tem 3 arquivos: cheia (desktop), "-m" (celular, 800 px) e "-b" (já desfocada, para as páginas de tarefa). O desfoque é feito UMA vez,
# na geração do arquivo: `filter: blur` ao vivo num elemento de tela cheia travava celular simples.
FOTOS_VALIDAS = {f"{p}{suf}" for p in POOL for suf in ("", "-m", "-b")}


def fundo_de(chave: str) -> str:
    return POOL[int(hashlib.sha256(str(chave).encode()).hexdigest(), 16) % len(POOL)]
DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
CSS = """
:root{--bg:#f1f6f5;--cartao:#fff;--tinta:#10292a;--mudo:#587170;--linha:#d6e3e1;--c:#0f766e;--c2:#0b5a54;--aviso:#fff4d6;--erro:#b42318;--ok:#067647;
--vidro:rgba(247,251,250,.94);--vidro-borda:rgba(255,255,255,.7);--sombra:0 24px 60px rgba(6,32,32,.22)}
@media(prefers-color-scheme:dark){:root{--bg:#0a1514;--cartao:#112221;--tinta:#e6f1f0;--mudo:#93aeac;--linha:#27403e;--c:#2dd4bf;--c2:#5eead4;--aviso:#3b3115;--erro:#f97066;--ok:#47cd89;
--vidro:rgba(10,22,21,.92);--vidro-borda:rgba(255,255,255,.10);--sombra:0 24px 60px rgba(0,0,0,.5)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tinta);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--c)}main{max-width:920px;margin:0 auto;padding:22px 16px 56px}h1{font-size:clamp(1.9rem,5vw,2.4rem);line-height:1.15;letter-spacing:-.02em;margin:.2em 0}h2{font-size:1.3rem;letter-spacing:-.01em;margin:1.7em 0 .5em}
header.topo{background:var(--cartao);border-bottom:1px solid var(--linha)}header.topo div{max-width:1040px;margin:0 auto;padding:14px 18px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header.topo b{font-size:1.08rem;letter-spacing:-.01em;margin-right:auto}header.topo a{text-decoration:none;font-weight:600}
.cartao{background:var(--cartao);border:1px solid var(--linha);border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 1px 2px rgba(6,32,32,.04)}.grade{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.mudo{color:var(--mudo);font-size:.93rem}
.btn,button{display:inline-block;background:linear-gradient(135deg,var(--c),var(--c2));color:#fff;border:0;border-radius:14px;padding:12px 20px;font:inherit;font-weight:700;text-decoration:none;cursor:pointer;box-shadow:0 8px 20px rgba(15,118,110,.28);transition:transform .15s,box-shadow .15s}
.btn:hover,button:hover{transform:translateY(-1px);box-shadow:0 12px 26px rgba(15,118,110,.34)}.btn.grande{padding:15px 28px;font-size:1.08rem;border-radius:16px}
@media(prefers-color-scheme:dark){.btn,button{color:#04211e}}.sec{background:transparent!important;color:var(--c)!important;border:1.5px solid var(--c);box-shadow:none!important}.perigo{background:transparent!important;color:var(--erro)!important;border:1.5px solid var(--erro);box-shadow:none!important}
label{display:block;margin:12px 0 5px;font-weight:600;font-size:.95rem}input,select,textarea{width:100%;padding:12px;border:1.5px solid var(--linha);border-radius:12px;background:var(--bg);color:var(--tinta);font:inherit}
input:focus,select:focus,textarea:focus{outline:3px solid color-mix(in srgb,var(--c) 35%,transparent);border-color:var(--c)}
input[type=checkbox]{width:auto}.linha{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.linha>*{flex:1 1 140px}.linha .fixo{flex:0 0 auto}
.horas{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 16px}.horas a,.horas button{padding:9px 15px;border-radius:12px;background:var(--cartao);color:var(--c);border:1.5px solid var(--c);text-decoration:none;font-weight:700;box-shadow:none;transition:background .15s,color .15s}
.horas a:hover{background:var(--c);color:#fff}
.aviso{background:var(--aviso);border-radius:14px;padding:14px 16px;margin:14px 0}.erro{color:var(--erro);font-weight:600}.ok{color:var(--ok);font-weight:600}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 6px;border-bottom:1px solid var(--linha);vertical-align:top}th{font-size:.85rem;color:var(--mudo)}
code,pre{background:var(--cartao);border:1px solid var(--linha);border-radius:8px;padding:2px 6px;font-size:.88rem}pre{padding:14px;overflow:auto}
.pill{display:inline-block;border-radius:99px;padding:3px 12px;font-size:.82rem;border:1.5px solid var(--linha);text-decoration:none;margin:2px 0}a.pill:hover{border-color:var(--c)}footer{margin-top:40px;color:var(--mudo);font-size:.88rem}
form.in{display:inline}.sr{position:absolute;left:-9999px}
/* ---- imersivo: foto de fundo fixa, herói e folha de vidro */
.fundo{position:fixed;inset:0;z-index:-2;background-color:#0b2b2a;background-position:center;background-size:cover;background-repeat:no-repeat}
.fundo::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(3,20,22,.42) 0%,rgba(3,20,22,.66) 50%,rgba(3,20,22,.9) 100%)}
body.vidro .fundo::after{background:linear-gradient(180deg,rgba(3,20,22,.5),rgba(3,20,22,.78))}
body.imersivo header.topo{background:transparent;border:0;position:absolute;left:0;right:0;top:0;z-index:3}body.imersivo header.topo a,body.imersivo header.topo b a{color:#fff!important;text-shadow:0 1px 12px rgba(0,0,0,.5)}
body.vidro header.topo{background:rgba(3,20,22,.6);border:0;position:sticky;top:0;z-index:3}body.vidro header.topo a,body.vidro header.topo b a{color:#fff!important}
.heroi{min-height:78vh;display:flex;flex-direction:column;justify-content:flex-end;max-width:1040px;margin:0 auto;padding:110px 22px 56px;color:#fff}
.heroi h1{font-size:clamp(2.3rem,7vw,4rem);line-height:1.05;margin:.15em 0 .3em;text-shadow:0 4px 34px rgba(0,0,0,.5)}.heroi p{font-size:clamp(1.05rem,2.4vw,1.3rem);max-width:640px;margin:.2em 0 1em;text-shadow:0 2px 22px rgba(0,0,0,.5)}
.heroi .kicker{align-self:flex-start;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.35);border-radius:99px;padding:5px 14px;font-size:.9rem;font-weight:600}
.heroi .acoes{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px}.heroi .btn.sec{color:#fff!important;border-color:rgba(255,255,255,.75)!important;background:rgba(255,255,255,.12)!important;}
.folha{background:var(--vidro);border:1px solid var(--vidro-borda);border-bottom:0;border-radius:34px 34px 0 0;box-shadow:var(--sombra);max-width:1040px;margin:0 auto;padding:30px 22px 64px}
.folha.cheia{max-width:760px;margin:26px auto 70px;border-radius:30px;border-bottom:1px solid var(--vidro-borda);padding:26px 22px 34px}
.folha .cartao{background:color-mix(in srgb,var(--cartao) 88%,transparent)}
.credito{font-size:11px;color:#fff;opacity:.88;background:rgba(0,0,0,.38);padding:3px 10px;border-radius:99px;white-space:nowrap}.credito a{color:#fff}
.heroi{position:relative}.heroi .credito{position:absolute;right:16px;bottom:14px}.credito.fim{display:block;width:max-content;margin:-40px auto 24px;position:relative}
@media(max-width:560px){.heroi{padding-top:90px;min-height:70vh}.folha{border-radius:26px 26px 0 0;padding:22px 14px 56px}}
"""


def pagina(titulo: str, corpo: str, *, desc: str = "", canonical: str = "", indexar: bool = True, nav: str = "", marca: str = "agenda-clinica",
           home: str = "/", extra_head: str = "", fundo: str = "", modo: str = "limpo", heroi: str = "") -> str:
    """`modo`: "limpo" (painel, trabalho), "vidro" (página de tarefa sobre a foto desfocada) ou "heroi" (foto cheia + herói)."""
    meta = f'<meta name="description" content="{e(desc)}">' if desc else ""
    meta += f'<link rel="canonical" href="{e(canonical)}">' if canonical else ""
    meta += "" if indexar else '<meta name="robots" content="noindex">'
    foto = fundo if (fundo in POOL and modo != "limpo") else ""
    cor = CREDITOS.get(foto, {}).get("cor", "#0b2b2a")
    camada = ""
    if foto and modo == "vidro":  # tarefa: a foto já desfocada (10 a 17 KB), sem filtro no navegador
        meta += f'<link rel="preload" as="image" href="/static/fundos/{foto}-b.jpg">'
        camada = f'<div class="fundo" style="background-image:url(/static/fundos/{foto}-b.jpg);background-color:{e(cor)}"></div>'
    elif foto:  # herói: 800 px no celular (23 a 67 KB), cheia só de 701 px para cima
        meta += (f'<link rel="preload" as="image" href="/static/fundos/{foto}-m.jpg" media="(max-width:700px)">'
                 f'<link rel="preload" as="image" href="/static/fundos/{foto}.jpg" media="(min-width:701px)">'
                 f'<style>.fundo{{background-image:url(/static/fundos/{foto}-m.jpg)}}@media(min-width:701px){{.fundo{{background-image:url(/static/fundos/{foto}.jpg)}}}}</style>')
        camada = f'<div class="fundo" style="background-color:{e(cor)}"></div>'
    cr = CREDITOS.get(foto)
    credito = (f'Foto: <a href="/creditos">{e(cr["fotografo"])}</a> · {e(cr["fonte"])}') if foto and cr else ""
    cab = (f'<header class="topo"><div><b><a href="{e(home)}" style="color:inherit">{e(marca)}</a></b>{nav}</div></header>')
    if foto and modo == "heroi":
        miolo, classe = f'{cab}<section class="heroi">{heroi}<div class="credito">{credito}</div></section><main class="folha">{corpo}</main>', "imersivo"
    elif foto and modo == "vidro":
        miolo, classe = f'{cab}<main class="folha cheia">{corpo}</main><div class="credito fim">{credito}</div>', "vidro"
    else:
        miolo, classe = f'{cab}<main>{corpo}</main>', ""
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(titulo)}</title>{meta}{extra_head}<style>{CSS}</style></head><body class="{classe}">{camada}{miolo}</body></html>')


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
        nav='<a href="/docs">Para agentes</a><a href="/entrar">Entrar</a>', fundo="psicologia", modo="heroi",
        heroi=('<span class="kicker">Grátis · código aberto (MIT)</span><h1>Site de clínica com agendamento online.</h1>'
               '<p>Páginas para a clínica e cada profissional, vários locais, agenda por horário livre e painel com login para bloquear, cancelar e remarcar. '
               'Sem mensalidade, sem anúncio. E <b>API e MCP</b> para agentes de IA agendarem.</p>'
               '<div class="acoes"><a class="btn grande" href="#criar">Criar minha clínica</a>'
               + ('<a class="btn grande sec" href="/c/demo">Ver a demonstração</a>' if demo else "") + '</div>'))


def privacidade() -> str:
    return pagina("Privacidade — agenda-clinica", """<h1>Privacidade</h1>
<p>Este serviço guarda apenas o necessário para marcar uma consulta: <b>nome</b>, <b>telefone</b> e, se você informar, <b>e-mail</b>,
junto da data, do horário, do serviço e do profissional. <b>Não guardamos dado clínico</b> (sintomas, exames, prontuário): não escreva isso nos campos.</p>
<p>Esses dados são visíveis para a clínica em que você agendou e para quem tiver o código da sua consulta. Não são vendidos nem usados para
publicidade. Para corrigir ou apagar seus dados, peça à clínica; quem opera o serviço atende a clínica pelo e-mail dela.</p>
<p>A clínica é a controladora dos dados dos próprios pacientes (LGPD, art. 5º, VI); este software é a ferramenta. O código é aberto e pode ser auditado.</p>
<p>Este sistema <b>não envia mensagens</b> (e-mail ou WhatsApp): quem avisa o paciente de cancelamentos e remarcações é a clínica.</p>""", nav='<a href="/">Início</a>', fundo="clinica-clara", modo="vidro")


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
    return pagina(f"{c['nome']} — agende online", f"""<h2 style="margin-top:.2em">Profissionais</h2><div class="grade">{profs or "<p class='mudo'>Em breve.</p>"}</div>
<h2>Serviços</h2><div class="cartao"><table><tr><th>Serviço</th><th>Duração</th><th>Valor</th><th></th></tr>{servs}</table></div>
<h2>Onde atendemos</h2><div class="grade">{locs}</div>
<footer>Agendamento por <a href="/">agenda-clinica</a>, software livre.</footer>""",
        desc=f"{c['nome']}{' em ' + c['cidade'] if c['cidade'] else ''}: conheça os profissionais e agende online.",
        canonical=f"{base}/c/{c['slug']}" if c.get("indexavel") else "", indexar=bool(c.get("indexavel")),
        marca=c["nome"], home=f"/c/{c['slug']}",
        extra_head=f'<script type="application/ld+json">{ld}</script>',
        nav=f'<a href="/c/{e(c["slug"])}/agendar">Agendar</a>', fundo=fundo_de(c["slug"]), modo="heroi",
        heroi=(f'<span class="kicker">{e(c["cidade"]) if c["cidade"] else "Agende online"}</span><h1>{e(c["nome"])}</h1><p>{e(c["descricao"])}</p>'
               f'<div class="acoes"><a class="btn grande" href="/c/{e(c["slug"])}/agendar">Agendar consulta</a>' + (f'<a class="btn grande sec" href="https://wa.me/{e(_so_digitos(c["telefone"]))}">WhatsApp</a>' if _so_digitos(c["telefone"]) else "") + '</div>'))


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
                      indexar=not q and not erro, marca=c["nome"], home=f"/c/{slug}", nav=nav, fundo=fundo_de(slug), modo="vidro")
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
<button>Confirmar</button></form>""", indexar=False, marca=c["nome"], home=f"/c/{slug}", nav=nav, fundo=fundo_de(slug), modo="vidro")
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
                  indexar=False, marca=c["nome"], home=f"/c/{slug}", nav=nav, fundo=fundo_de(slug), modo="vidro")


def agendado(info: dict, ag: dict, base: str) -> str:
    c = info["clinica"]
    wa = (f"<p><a class='btn sec' href='https://wa.me/{e(_so_digitos(c['telefone']))}'>Falar com a clínica</a></p>" if _so_digitos(c["telefone"]) else "")
    return pagina(f"Agendado — {c['nome']}", f"""<h1 class="ok">Agendado!</h1>
<div class="cartao"><b>{e(ag['servico'])}</b> com <b>{e(ag['profissional'])}</b><br>{e(data_br(ag['data']))} às {e(ag['hora'])}<br>{e(ag['local'])} · {e(ag['endereco'])}</div>
<div class="aviso"><b>Guarde este link</b> para consultar, cancelar ou remarcar:<br><a href="/m/{e(ag['codigo'])}">{e(base)}/m/{e(ag['codigo'])}</a><br>
<span class="mudo">Código: <code>{e(ag['codigo'])}</code>. A clínica não envia mensagem automática: guarde o código.</span></div>{wa}""",
                  indexar=False, marca=c["nome"], home=f"/c/{c['slug']}", fundo=fundo_de(c["slug"]), modo="vidro")


def consulta(ag: dict, clinica: dict, erro: str = "") -> str:
    ativo = ag["status"] == "confirmado"
    return pagina(f"Sua consulta — {clinica['nome']}", f"""<h1>Sua consulta</h1>{_erro(erro)}
<div class="cartao"><b>{e(ag['servico'])}</b> com <b>{e(ag['profissional'])}</b><br>{e(data_br(ag['data']))} às {e(ag['hora'])}<br>{e(ag['local'])} · {e(ag['endereco'])}<br>
<span class="pill">{'confirmada' if ativo else 'cancelada'}</span></div>
{f'''<div class="linha"><a class="btn sec fixo" href="/m/{e(ag['codigo'])}/remarcar">Remarcar</a>
<form method="post" action="/m/{e(ag['codigo'])}/cancelar" class="in"><button class="perigo">Cancelar consulta</button></form></div>''' if ativo else ''}""",
                  indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}", fundo=fundo_de(clinica["slug"]), modo="vidro")


def remarcar_paciente(ag: dict, clinica: dict, horarios: list[dict], profs: dict, erro: str = "") -> str:
    corpo = ""
    for h in horarios:
        corpo += (f"<form method='post' action='/m/{e(ag['codigo'])}/remarcar' class='in'><input type='hidden' name='data' value='{e(h['data'])}'>"
                  f"<input type='hidden' name='hora' value='{e(h['hora'])}'><input type='hidden' name='profissional' value='{h['profissional_id']}'>"
                  f"<button class='sec' style='margin:3px'>{e(data_br(h['data']))} {e(h['hora'])} · {e(profs.get(h['profissional_id'], ''))}</button></form>")
    return pagina(f"Remarcar — {clinica['nome']}", f"<h1>Remarcar</h1>{_erro(erro)}<p class='mudo'>Escolha o novo horário:</p>{corpo or '<p class=aviso>Sem horários livres nos próximos 14 dias.</p>'}",
                  indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}", fundo=fundo_de(clinica["slug"]), modo="vidro")


# ------------------------------------------------------------------ painel

def _csrf(tok: str) -> str:
    return f'<input type="hidden" name="csrf" value="{e(n.csrf_de(tok))}">'


def entrar(erro: str = "") -> str:
    return pagina("Entrar — agenda-clinica", f"""<h1>Entrar</h1>{_erro(erro)}<form method="post" action="/entrar" class="cartao">
<label>E-mail<input name="email" type="email" required autocomplete="username"></label>
<label>Senha<input name="senha" type="password" required autocomplete="current-password"></label><button>Entrar</button></form>
<p class="mudo">Ainda não tem clínica? <a href="/#criar">Crie grátis</a>.</p>""", indexar=False, fundo="minimalista", modo="vidro")


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
<p><a href="/openapi.json">openapi.json</a> · <a href="/llms.txt">llms.txt</a></p>""", desc="API REST e servidor MCP do agenda-clinica para agentes de IA.", canonical=f"{base}/docs", nav='<a href="/">Início</a>', fundo="clinica-clara", modo="vidro")


def creditos() -> str:
    itens = "".join(
        f"<div class='cartao'><b>{e(c['alt'])}</b><div class='mudo'>Foto de <a href='{e(c['pagina'])}' rel='noopener'>{e(c['fotografo'])}</a> · {e(c['fonte'])} · {e(c['licenca'])}</div></div>"
        for k, c in sorted(CREDITOS.items()))
    return pagina("Créditos das fotos — agenda-clinica", f"""<h1>Créditos das fotos</h1>
<p>As fotos de fundo vêm do <b>Unsplash</b> e do <b>Pexels</b>, ambos de uso livre, e são servidas deste domínio (nenhum terceiro vê o seu acesso). Obrigado aos fotógrafos.</p>
<div class="grade">{itens}</div>""", desc="Créditos das fotos de fundo do agenda-clinica.", nav='<a href="/">Início</a>', fundo="spa", modo="vidro")
