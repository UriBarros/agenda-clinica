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

import nichos as nx
import nucleo as n
import ops

e = html.escape

# Fotos de fundo (Unsplash e Pexels, licenças de uso livre), servidas do NOSSO domínio com crédito (ADR-001): nada de hotlink,
# nada de terceiro vendo o IP do paciente. Cada clínica ganha uma foto estável pelo endereço dela (mesma entrada, mesma foto).
FUNDOS_DIR = Path(__file__).resolve().parent / "static" / "fundos"
POOL = nx.POOL_TODOS  # o pool de CADA nicho mora em nichos.json
try:
    CREDITOS = json.loads((FUNDOS_DIR.parent / "creditos.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    CREDITOS = {}


# Cada foto tem 3 arquivos: cheia (desktop), "-m" (celular, 800 px) e "-b" (já desfocada, para as páginas de tarefa). O desfoque é feito UMA vez,
# na geração do arquivo: `filter: blur` ao vivo num elemento de tela cheia travava celular simples.
FOTOS_VALIDAS = {f"{p}{suf}" for p in POOL for suf in ("", "-m", "-b")}


def fundo_de(chave: str, c=None) -> str:
    pool = nx.vocab(c)["pool"]
    return pool[int(hashlib.sha256(str(chave).encode()).hexdigest(), 16) % len(pool)]
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
           home: str = "/", extra_head: str = "", fundo: str = "", modo: str = "limpo", heroi: str = "", tema: str = "") -> str:
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
    # Cor do cliente só no tema claro: no escuro o contraste do tom padrão já foi medido; o dev personaliza o que a clínica vê de dia.
    estilo_tema = f"<style>@media(prefers-color-scheme:light){{:root{{--c:{e(tema)};--c2:{e(tema)}}}}}</style>" if tema else ""
    cab = (f'<header class="topo"><div><b><a href="{e(home)}" style="color:inherit">{e(marca)}</a></b>{nav}</div></header>')
    if foto and modo == "heroi":
        miolo, classe = f'{cab}<section class="heroi">{heroi}<div class="credito">{credito}</div></section><main class="folha">{corpo}</main>', "imersivo"
    elif foto and modo == "vidro":
        miolo, classe = f'{cab}<main class="folha cheia">{corpo}</main><div class="credito fim">{credito}</div>', "vidro"
    else:
        miolo, classe = f'{cab}<main>{corpo}</main>', ""
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(titulo)}</title>{meta}{extra_head}<style>{CSS}</style>{estilo_tema}</head><body class="{classe}">{camada}{miolo}</body></html>')


def brl(centavos) -> str:
    return "" if centavos is None else f"R$ {centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{DIAS[n.dia_semana(d)][:3]} {d.day:02d}/{d.month:02d}"


def _erro(msg: str) -> str:
    return f'<p class="erro" role="alert">{e(msg)}</p>' if msg else ""


# ------------------------------------------------------------------ raiz

def home(repo_url: str, demo: bool, erro: str = "", nicho: str = nx.PADRAO) -> str:
    """Página de entrada de um nicho (`/` = clínica, `/<nicho>` os outros): todo o texto vem de nichos.json."""
    H = nx.NICHOS[nicho]["home"]
    return pagina(H["titulo"], f"""
<div class="grade">
<div class="cartao"><b>{H["cliente"][0]}</b><p class="mudo">{H["cliente"][1]}</p></div>
<div class="cartao"><b>{H["dono"][0]}</b><p class="mudo">{H["dono"][1]}</p></div>
<div class="cartao"><b>Para agentes</b><p class="mudo">API REST (<a href="/openapi.json">OpenAPI</a>) e MCP em <code>/mcp</code>. Veja o <a href="/docs">guia</a> e o <a href="/llms.txt">llms.txt</a>.</p></div></div>
<h2 id="criar">{H["criar"]}</h2>{_erro(erro)}
<form method="post" action="/criar" class="cartao"><input type="hidden" name="nicho" value="{e(nicho)}"><label>{H["nome_label"]}<input name="nome" required maxlength="100"></label>
<label>E-mail (será o login)<input name="email" type="email" required></label>
<label>Senha (mínimo 10 caracteres)<input name="senha" type="password" minlength="10" required autocomplete="new-password"></label>
<p class="mudo">{H["privacidade"]}</p>
<button>Criar grátis</button></form>
{f'<p><a href="/c/{H["demo_slug"]}">{H["demo"]}</a> (dados fictícios; agentes podem testar a API nela).</p>' if demo else ''}
<footer>Código-fonte: <a href="{e(repo_url)}">{e(repo_url)}</a> · <a href="/privacidade">Privacidade</a></footer>""",
        desc=H["desc"], nav='<a href="/docs">Para agentes</a><a href="/devs">Para devs</a><a href="/entrar">Entrar</a>', fundo=H["fundo"], modo="heroi",
        heroi=(f'<span class="kicker">Grátis · código aberto (MIT)</span><h1>{H["h1"]}</h1><p>{H["p"]}</p>'
               f'<div class="acoes"><a class="btn grande" href="#criar">{H["criar"]}</a>'
               + (f'<a class="btn grande sec" href="/c/{H["demo_slug"]}">Ver a demonstração</a>' if demo else "") + '</div>'))


def privacidade() -> str:
    return pagina("Privacidade — agenda-clinica", """<h1>Privacidade</h1>
<p>Este serviço guarda apenas o necessário para marcar uma consulta: <b>nome</b>, <b>telefone</b> e, se você informar, <b>e-mail</b>,
junto da data, do horário, do serviço e do profissional. <b>Não guardamos dado clínico</b> (sintomas, exames, prontuário): não escreva isso nos campos.</p>
<p>Esses dados são visíveis para a clínica em que você agendou e para quem tiver o código da sua consulta. Não são vendidos nem usados para
publicidade. Para corrigir ou apagar seus dados, peça à clínica; quem opera o serviço atende a clínica pelo e-mail dela.</p>
<p>A clínica é a controladora dos dados dos próprios pacientes (LGPD, art. 5º, VI); este software é a ferramenta. Se o cadastro da clínica foi feito por uma <b>conta de dev</b> (agência ou integrador que presta o suporte), esse dev também vê o nome e o telefone de quem agendou naquela clínica, só para dar o suporte. O código é aberto e pode ser auditado.</p>
<p>Por padrão este sistema <b>não envia mensagens</b>. Se a clínica ligar o lembrete por WhatsApp, você recebe no máximo <b>uma confirmação e um lembrete</b> da sua consulta, no número que informou, com um link para não receber mais. Cancelamentos e remarcações feitos pela clínica continuam sendo avisados por ela.</p>""", nav='<a href="/">Início</a>', fundo="clinica-clara", modo="vidro")


# ------------------------------------------------------------------ site da clínica

def site_clinica(info: dict, base: str) -> str:
    c = info["clinica"]
    ld = {"@context": "https://schema.org", "@type": nx.vocab(c)["ld"], "name": c["nome"], "url": f"{base}/c/{c['slug']}",
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
    V = nx.vocab(c)
    return pagina(f"{c['nome']} — agende online", f"""<h2 style="margin-top:.2em">{e(V["profs"])}</h2><div class="grade">{profs or "<p class='mudo'>Em breve.</p>"}</div>
<h2>Serviços</h2><div class="cartao"><table><tr><th>Serviço</th><th>Duração</th><th>Valor</th><th></th></tr>{servs}</table></div>
<h2>Onde atendemos</h2><div class="grade">{locs}</div>
<footer>Agendamento por <a href="/">agenda-clinica</a>, software livre.</footer>""",
        desc=f"{c['nome']}{' em ' + c['cidade'] if c['cidade'] else ''}: conheça a equipe e agende online.",
        canonical=f"{base}/c/{c['slug']}" if c.get("indexavel") else "", indexar=bool(c.get("indexavel")),
        marca=c["nome"], home=f"/c/{c['slug']}",
        extra_head=f'<script type="application/ld+json">{ld}</script>',
        nav=f'<a href="/c/{e(c["slug"])}/agendar">Agendar</a>', tema=nx.tema(c), fundo=fundo_de(c["slug"], c), modo="heroi",
        heroi=(f'<span class="kicker">{e(c["cidade"]) if c["cidade"] else "Agende online"}</span><h1>{e(c["nome"])}</h1><p>{e(c["descricao"])}</p>'
               f'<div class="acoes"><a class="btn grande" href="/c/{e(c["slug"])}/agendar">{e(nx.vocab(c)["agendar"])}</a>' + (f'<a class="btn grande sec" href="https://wa.me/{e(_so_digitos(c["telefone"]))}">WhatsApp</a>' if _so_digitos(c["telefone"]) else "") + '</div>'))


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
    V = nx.vocab(c)
    if not serv:
        itens = "".join(f"<a class='cartao' style='display:block;text-decoration:none' href='{base}?servico={s['id']}'><b>{e(s['nome'])}</b>"
                        f"<div class='mudo'>{s['duracao_min']} min {e(brl(s['preco_centavos']))}</div></a>" for s in info["servicos"])
        return pagina(f"Agendar — {c['nome']}", f"<h1>Qual serviço?</h1>{_erro(erro)}<div class='grade'>{itens or '<p>' + e(V['sem_servicos']) + '</p>'}</div>",
                      # A /agendar BASE é indexável (decisão do dono: "indexa tudo"); com parâmetro (serviço, horário) ou erro
                      # é combinação infinita de URLs sem conteúdo próprio, e a página do paciente (/m/) é dado pessoal: noindex.
                      indexar=not q and not erro, marca=c["nome"], home=f"/c/{slug}", nav=nav, tema=nx.tema(c), fundo=fundo_de(slug, c), modo="vidro")
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
<p><label style="font-weight:400"><input type="checkbox" name="consentimento" value="1" required> {e(V["autorizo"])}
(<a href="/privacidade">privacidade</a>).{e(V["saude"])}</label></p>
<button>Confirmar</button></form>""", indexar=False, marca=c["nome"], home=f"/c/{slug}", nav=nav, tema=nx.tema(c), fundo=fundo_de(slug, c), modo="vidro")
    filtro = q.get("profissional", "")
    links = f"<a class='pill' href='{base}?servico={serv['id']}'>{e(V['qualquer'])}</a> " + " ".join(
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
<p>{links}</p>{_erro(erro)}{corpo or "<p class='aviso'>Sem horários livres nos próximos 14 dias para essa escolha. Tente {e(V['outro'])} ou fale com {e(c['nome'])}.</p>"}""",
                  indexar=False, marca=c["nome"], home=f"/c/{slug}", nav=nav, tema=nx.tema(c), fundo=fundo_de(slug, c), modo="vidro")


def agendado(info: dict, ag: dict, base: str) -> str:
    c = info["clinica"]
    wa = (f"<p><a class='btn sec' href='https://wa.me/{e(_so_digitos(c['telefone']))}'>{e(nx.vocab(c)['falar'])}</a></p>" if _so_digitos(c["telefone"]) else "")
    return pagina(f"Agendado — {c['nome']}", f"""<h1 class="ok">Agendado!</h1>
<div class="cartao"><b>{e(ag['servico'])}</b> com <b>{e(ag['profissional'])}</b><br>{e(data_br(ag['data']))} às {e(ag['hora'])}<br>{e(ag['local'])} · {e(ag['endereco'])}</div>
<div class="aviso"><b>Guarde este link</b> para consultar, cancelar ou remarcar:<br><a href="/m/{e(ag['codigo'])}">{e(base)}/m/{e(ag['codigo'])}</a><br>
<span class="mudo">Código: <code>{e(ag['codigo'])}</code>. {"Você receberá um lembrete por WhatsApp; guarde o código também." if c.get("lembrete_whatsapp") else e(nx.vocab(c)["sem_msg"])}</span></div>{wa}""",
                  indexar=False, marca=c["nome"], home=f"/c/{c['slug']}", tema=nx.tema(c), fundo=fundo_de(c["slug"], c), modo="vidro")


def consulta(ag: dict, clinica: dict, erro: str = "") -> str:
    ativo = ag["status"] == "confirmado"
    return pagina(f"{nx.vocab(clinica)['sua']} — {clinica['nome']}", f"""<h1>{e(nx.vocab(clinica)['sua'])}</h1>{_erro(erro)}
<div class="cartao"><b>{e(ag['servico'])}</b> com <b>{e(ag['profissional'])}</b><br>{e(data_br(ag['data']))} às {e(ag['hora'])}<br>{e(ag['local'])} · {e(ag['endereco'])}<br>
<span class="pill">{'confirmada' if ativo else 'cancelada'}</span></div>
{f'''<div class="linha"><a class="btn sec fixo" href="/m/{e(ag['codigo'])}/remarcar">Remarcar</a>
<form method="post" action="/m/{e(ag['codigo'])}/cancelar" class="in"><button class="perigo">{e(nx.vocab(clinica)["cancelar"])}</button></form></div>''' if ativo else ''}""",
                  indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}", tema=nx.tema(clinica), fundo=fundo_de(clinica["slug"], clinica), modo="vidro")


def remarcar_paciente(ag: dict, clinica: dict, horarios: list[dict], profs: dict, erro: str = "") -> str:
    corpo = ""
    for h in horarios:
        corpo += (f"<form method='post' action='/m/{e(ag['codigo'])}/remarcar' class='in'><input type='hidden' name='data' value='{e(h['data'])}'>"
                  f"<input type='hidden' name='hora' value='{e(h['hora'])}'><input type='hidden' name='profissional' value='{h['profissional_id']}'>"
                  f"<button class='sec' style='margin:3px'>{e(data_br(h['data']))} {e(h['hora'])} · {e(profs.get(h['profissional_id'], ''))}</button></form>")
    return pagina(f"Remarcar — {clinica['nome']}", f"<h1>Remarcar</h1>{_erro(erro)}<p class='mudo'>Escolha o novo horário:</p>{corpo or '<p class=aviso>Sem horários livres nos próximos 14 dias.</p>'}",
                  indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}", tema=nx.tema(clinica), fundo=fundo_de(clinica["slug"], clinica), modo="vidro")


# ------------------------------------------------------------------ painel

def _csrf(tok: str) -> str:
    return f'<input type="hidden" name="csrf" value="{e(n.csrf_de(tok))}">'


def entrar(erro: str = "") -> str:
    return pagina("Entrar — agenda-clinica", f"""<h1>Entrar</h1>{_erro(erro)}<form method="post" action="/entrar" class="cartao">
<label>E-mail<input name="email" type="email" required autocomplete="username"></label>
<label>Senha<input name="senha" type="password" required autocomplete="current-password"></label><button>Entrar</button></form>
<p class="mudo">Ainda não tem clínica? <a href="/#criar">Crie grátis</a>.</p>""", indexar=False, fundo="minimalista", modo="vidro")


def _nav_painel(c) -> str:
    return (f'<a href="/painel">Agenda</a><a href="/painel/equipe">Equipe e horários</a><a href="/painel/whatsapp">WhatsApp</a><a href="/painel/api">Agentes e API</a>'
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
<h2>Levar seus dados</h2><p>Exporte a clínica em JSON para migrar para o seu servidor (<a href="/devs">como</a>): <a href="/painel/exportar">sem pacientes</a> · <a href="/painel/exportar?com_pacientes=1">com pacientes</a> (dado pessoal: guarde com cuidado). Nunca leva senha nem chaves.</p>
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
<li>Só saem mensagens se a clínica ligou o WhatsApp (veja <code>whatsapp_status</code>), e só lembretes de consultas reais: não há operação para mandar texto a um número. Ao cancelar ou remarcar, avise o paciente por outro canal.</li><li>Não grave dado clínico nos campos.</li></ul>
<h2>Operações</h2><div class="cartao" style="overflow:auto"><table><tr><th>Ferramenta</th><th>REST</th><th>Acesso</th><th>O que faz</th></tr>{linhas}</table></div>
<p><a href="/openapi.json">openapi.json</a> · <a href="/llms.txt">llms.txt</a></p>""", desc="API REST e servidor MCP do agenda-clinica para agentes de IA.", canonical=f"{base}/docs", nav='<a href="/">Início</a>', fundo="clinica-clara", modo="vidro")


def creditos() -> str:
    itens = "".join(
        f"<div class='cartao'><b>{e(c['alt'])}</b><div class='mudo'>Foto de <a href='{e(c['pagina'])}' rel='noopener'>{e(c['fotografo'])}</a> · {e(c['fonte'])} · {e(c['licenca'])}</div></div>"
        for k, c in sorted(CREDITOS.items()))
    return pagina("Créditos das fotos — agenda-clinica", f"""<h1>Créditos das fotos</h1>
<p>As fotos de fundo vêm do <b>Unsplash</b> e do <b>Pexels</b>, ambos de uso livre, e são servidas deste domínio (nenhum terceiro vê o seu acesso). Obrigado aos fotógrafos.</p>
<div class="grade">{itens}</div>""", desc="Créditos das fotos de fundo do agenda-clinica.", nav='<a href="/">Início</a>', fundo="spa", modo="vidro")


# ------------------------------------------------------------------ WhatsApp (lembretes pelo Evolution)

def painel_whatsapp(c, tok: str, est: dict, msg: str = "", erro: str = "") -> str:
    cont = " · ".join(f"{k}: {v}" for k, v in sorted(est["lembretes"].items())) or "nenhum ainda"
    sit = ("o servidor <b>não tem Evolution configurado</b> (EVOLUTION_URL e EVOLUTION_KEY): não dá para ligar aqui" if not est["servidor_com_evolution"]
           else f"instância <code>{e(est['instancia'] or '—')}</code>: <b>{e(est['whatsapp'])}</b>")
    return pagina(f"WhatsApp — {c['nome']}", f"""<h1>Lembrete por WhatsApp</h1>{f'<p class="ok">{e(msg)}</p>' if msg else ''}{_erro(erro)}
<div class="aviso" role="alert"><b>Leia antes de ligar.</b> {e(est['aviso'])}</div>
<p>Conecte o WhatsApp da clínica numa instância do <b>Evolution</b> (o QR é lido lá, não aqui) e informe o nome da instância. Depois de ligado, cada agendamento
gera sozinho {'uma confirmação e ' if est['confirmacao'] else ''}um lembrete; <b>não há como mandar mensagem a um número ou texto livre</b>, nem por aqui nem pela API/MCP.</p>
<p class="mudo">Situação: {sit}. Lembretes: {e(cont)}. Estão {'ligados' if est['ativo'] else 'desligados'}.</p>
<form method="post" action="/painel/acao" class="cartao">{_csrf(tok)}<input type="hidden" name="acao" value="whatsapp"><input type="hidden" name="volta" value="/painel/whatsapp">
<label>Nome da instância no Evolution<input name="instancia" value="{e(est['instancia'])}" maxlength="40" placeholder="minha-clinica"></label>
<div class="linha"><label>Lembrar quantas horas antes<input name="lembrete_horas" type="number" min="1" max="72" value="{est['lembrete_horas']}"></label></div>
<p><label style="font-weight:400"><input type="checkbox" name="confirmacao" value="1" {'checked' if est['confirmacao'] else ''}> Também mandar uma confirmação assim que o paciente agendar</label></p>
<p><label style="font-weight:400"><input type="checkbox" name="ativo" value="1" {'checked' if est['ativo'] else ''}> Ligar os lembretes</label></p>
<p><label style="font-weight:400"><input type="checkbox" name="aceito_risco" value="1"> Li o aviso: sei que o número pode ser banido pelo WhatsApp e que uso um número só da clínica, sem divulgação.</label></p>
<button>Salvar</button></form>""", indexar=False, marca=c["nome"], home="/painel", nav=_nav_painel(c))


def sem_lembrete(ag: dict, clinica: dict, feito: bool) -> str:
    V = nx.vocab(clinica)
    corpo = (f"<h1 class='ok'>Pronto</h1><p>Você não receberá mais lembretes de {e(clinica['nome'])} neste telefone. {e(V['sua'])} continua marcada.</p>" if feito else
             f"<h1>Não quer receber lembretes?</h1><p>Vale para este telefone em {e(clinica['nome'])}. {e(V['sua'])} de {e(ag['servico'])}, {e(data_br(ag['data']))} às {e(ag['hora'])}, continua marcada.</p>"
             f"<form method='post' action='/m/{e(ag['codigo'])}/sem-lembrete'><button>Parar de receber</button></form>"
             f"<p class='mudo'>Não foi você que agendou? <a href='/m/{e(ag['codigo'])}'>Cancele {e(V['a_consulta'])} aqui</a>.</p>")
    return pagina(f"Lembretes — {clinica['nome']}", corpo, indexar=False, marca=clinica["nome"], home=f"/c/{clinica['slug']}",
                  tema=nx.tema(clinica), fundo=fundo_de(clinica["slug"], clinica), modo="vidro")


# ------------------------------------------------------------------ para quem desenvolve

def devs(repo_url: str, base: str) -> str:
    return pagina("Para devs — rode no seu servidor ou use o nosso", f"""<h1>Para devs</h1>
<p>O agenda-clinica é <b>software livre (MIT)</b>: Python e SQLite, sem dependência externa. Você pode usar o nosso servidor, rodar o seu, ou começar aqui e migrar depois.</p>
<div class="grade">
<div class="cartao"><b>1 · Código</b><p class="mudo"><a href="{e(repo_url)}">{e(repo_url)}</a><br>Licença MIT. <code>nichos.json</code> é a única coisa que muda de um tipo de negócio para outro: nicho novo é dado, não código.</p></div>
<div class="cartao"><b>2 · Rodar no seu servidor</b><pre>docker build -t agenda-clinica .
docker run -d -p 8080:8080 -v agenda:/data \\
  -e BASE_URL=https://agenda.seudominio.com \\
  agenda-clinica</pre><p class="mudo">Ou sem Docker: <code>python3 app.py</code> (Python 3.12). Os dados ficam em <code>/data</code> (um arquivo SQLite); <code>python3 app.py backup arquivo.db</code> faz cópia consistente com o serviço no ar.</p></div>
<div class="cartao"><b>3 · Migrar do nosso para o seu</b><pre># no painel: Agentes e API → Levar seus dados, ou:
curl -H 'Authorization: Bearer ac_...' \\
  '{e(base)}/api/v1/exportar?com_pacientes=true' &gt; clinica.json

# no seu servidor:
AGENDA_EMAIL=voce@x.com AGENDA_SENHA=... \\
  python3 app.py importar clinica.json</pre><p class="mudo">O arquivo não leva senha, chaves nem sessões: você define o login novo na importação. Com pacientes, os links <code>/m/código</code> continuam valendo. Importar não liga o WhatsApp: cada servidor usa o seu Evolution. Se algo no arquivo falhar, nada é importado.</p></div>
<div class="cartao"><b>4 · Conta de dev: vários clientes, uma chave</b><p class="mudo"><a href="/dev/cadastro">Crie uma conta de dev</a> (e-mail; grátis e aberto), cadastre os seus clientes, monte a agenda de cada um, entregue o login a eles e dê o suporte (você vê nome e telefone dos pacientes dos seus clientes). A chave de dev (<code>ad_...</code>) age em cada cliente seu por API e MCP: passe <code>clinica=&lt;endereço&gt;</code>.</p></div>
<div class="cartao"><b>5 · Gerenciar por API ou MCP</b><p class="mudo">Cada clínica tem chaves de API (escopo leitura ou escrita) no painel. Aponte o seu agente para <code>{e(base)}/mcp</code> (ou para o seu servidor: é o mesmo contrato). <a href="/docs">Guia e operações</a> · <a href="/openapi.json">OpenAPI</a> · <a href="/llms.txt">llms.txt</a>.</p></div>
</div>
<div class="aviso"><b>Dado de paciente é da clínica</b> (LGPD): quem hospeda é operador, não dono. Ao migrar, apague do servidor antigo o que não precisa mais: <code>python3 app.py apagar &lt;slug&gt; --confirmo</code> (não tem volta; exporte antes).</div>""",
                  desc="Código aberto (MIT), como rodar no seu servidor, exportar e importar uma clínica e gerenciar por API ou MCP.", canonical=f"{base}/devs" if base else "",
                  nav='<a href="/">Início</a><a href="/docs">Para agentes</a>', fundo="minimalista", modo="vidro")


# ------------------------------------------------------------------ conta de dev

def dev_conta(modo: str, erro: str = "", oauth: list[tuple[str, str]] | None = None) -> str:
    """`modo`: "cadastro" ou "entrar". `oauth`: [(rótulo, endereço)] dos provedores configurados neste servidor (Google, GitHub)."""
    cad = modo == "cadastro"
    botoes = "".join(f"<a class='btn sec' style='display:block;margin:8px 0;text-align:center' href='{e(h)}'>{e(r)}</a>" for r, h in (oauth or []))
    campos = ('<label>Nome<input name="nome" maxlength="80" autocomplete="name"></label>' if cad else "") + (
        '<label>E-mail<input name="email" type="email" required autocomplete="email"></label>'
        f'<label>Senha{" (mínimo 10 caracteres)" if cad else ""}<input name="senha" type="password" required minlength="{10 if cad else 1}" autocomplete="{"new-password" if cad else "current-password"}"></label>')
    return pagina("Conta de dev — " + ("criar" if cad else "entrar"), f"""<h1>{'Criar conta de dev' if cad else 'Entrar como dev'}</h1>{_erro(erro)}
<p class="mudo">Uma conta, vários clientes (clínicas e outros negócios com hora marcada). Você cria, personaliza e dá o suporte; eles agendam. Grátis e de código aberto.</p>
{botoes}<form method="post" action="/dev/{'cadastro' if cad else 'entrar'}" class="cartao">{campos}<button>{'Criar conta' if cad else 'Entrar'}</button></form>
<p class="mudo">{'Já tem conta? <a href="/dev/entrar">Entrar</a>' if cad else 'Ainda não tem? <a href="/dev/cadastro">Criar conta de dev</a>'} · <a href="/devs">Como funciona</a></p>""",
                  indexar=False, nav='<a href="/devs">Para devs</a>', fundo="minimalista", modo="vidro")


def dev_painel(dev, tok: str, clientes: list[dict], chaves: list[dict], base: str, nova: dict | None = None, msg: str = "", erro: str = "") -> str:
    def form(acao: str, corpo: str, botao: str, classe: str = "sec") -> str:
        return (f"<form method='post' action='/dev/acao' class='in'>{_csrf(tok)}<input type='hidden' name='acao' value='{acao}'>{corpo}"
                f"<button class='{classe}' style='padding:4px 10px'>{botao}</button></form>")
    linhas = ""
    for c in clientes:
        s = e(c["slug"])
        oculto = f"<input type='hidden' name='slug' value='{s}'>"
        linhas += (f"<tr><td><b>{e(c['nome'])}</b><div class='mudo'>{e(c['nicho'])} · {e(c['cidade'])} · <a href='/c/{s}'>/c/{s}</a></div></td><td>{c['agendamentos_futuros']}</td>"
                   f"<td>{form('suporte', oculto, 'Entrar como suporte')}"
                   f"<a href='/dev/exportar/{s}'>exportar</a> · <a href='/dev/exportar/{s}?com_pacientes=1'>com pacientes</a>"
                   f"<details><summary>Acesso do cliente</summary>{form('acesso', oculto + '<input name=email type=email placeholder=e-mail required><input name=senha type=password minlength=10 placeholder=senha required>', 'Definir')}</details>"
                   f"<details><summary>Personalizar</summary>{form('personalizar', oculto + '<input name=cor type=color value=' + e(nx.personalizacao(c).get('cor') or '#0f766e') + '><input name=agendar placeholder=\"texto do botão de agendar\" value=\"' + e(nx.personalizacao(c).get('rotulos', {}).get('agendar', '')) + '\"><input name=profs placeholder=\"nome da equipe (ex.: Barbeiros)\" value=\"' + e(nx.personalizacao(c).get('rotulos', {}).get('profs', '')) + '\">', 'Salvar')}</details>"
                   f"<details><summary>Apagar</summary>{form('apagar', oculto + '<input name=confirmar placeholder=\"digite ' + s + '\" required>', 'Apagar para sempre', 'perigo')}</details></td></tr>")
    caixa = (f"<div class='aviso'><b>Chave criada (aparece só agora):</b><br><code style='word-break:break-all'>{e(nova['chave'])}</code></div>" if nova else "")
    chv = "".join(f"<tr><td>{e(k['nome'])}</td><td><code>ad_{e(k['prefixo'])}…</code></td><td>{e(k['ultimo_uso'] or 'nunca usada')}</td><td>{form('revogar_chave', f'<input type=hidden name=id value={k['id']}>', 'Revogar', 'perigo')}</td></tr>" for k in chaves)
    cfg = json.dumps({"mcpServers": {"agenda-clinica": {"type": "http", "url": f"{base}/mcp", "headers": {"Authorization": "Bearer ad_SUA_CHAVE"}}}}, indent=2)
    return pagina("Meus clientes — conta de dev", f"""<h1>Meus clientes</h1>{_erro(erro)}{'<p class="ok">' + e(msg) + '</p>' if msg else ''}{caixa}
<p class="mudo">{e(dev['email'])} · você vê nome e telefone dos pacientes dos seus clientes: é você quem dá o suporte.</p>
<div class="cartao">{f'<table><tr><th>Cliente</th><th>Agend. futuros</th><th></th></tr>{linhas}</table>' if linhas else "<p class='mudo'>Nenhum cliente ainda. Crie o primeiro abaixo.</p>"}</div>
<h2>Novo cliente</h2>
<form method="post" action="/dev/acao" class="cartao">{_csrf(tok)}<input type="hidden" name="acao" value="criar_clinica">
<div class="linha"><label>Nome<input name="nome" required maxlength="100"></label><label>Tipo<select name="nicho">{''.join(f'<option value="{e(k)}">{e(k)}</option>' for k in nx.NICHOS)}</select></label>
<label>Endereço (opcional)<input name="slug" placeholder="meu-cliente" maxlength="40"></label><label>Cidade<input name="cidade" maxlength="80"></label></div><button>Criar cliente</button></form>
<h2>Chaves de API e MCP</h2><div class="cartao">{f'<table><tr><th>Nome</th><th>Chave</th><th>Último uso</th><th></th></tr>{chv}</table>' if chv else "<p class='mudo'>Nenhuma chave ainda.</p>"}</div>
<form method="post" action="/dev/acao" class="cartao">{_csrf(tok)}<input type="hidden" name="acao" value="criar_chave"><div class="linha"><label>Nome<input name="nome" placeholder="meu agente" required></label></div><button>Criar chave de dev</button></form>
<p class="mudo">A chave de dev age em qualquer cliente seu: passe <code>clinica=&lt;endereço&gt;</code>. Conectar um agente (MCP):</p><pre>{e(cfg)}</pre>
<form method="post" action="/dev/sair" class="in">{_csrf(tok)}<button class="sec">Sair</button></form>""",
                  indexar=False, marca="Conta de dev", home="/dev", nav='<a href="/devs">Para devs</a><a href="/docs">Para agentes</a>')


def protocolo(base: str) -> str:
    return pagina("Protocolo aberto — agenda-clinica", f"""<h1>Protocolo aberto</h1>
<p>O contrato do agenda-clinica é <b>aberto (MIT)</b>: qualquer servidor que fale isto é compatível com os agentes, as chaves e os arquivos de quem usa o nosso, e dá para sair de um servidor para outro sem pedir licença.</p>
<div class="grade"><div class="cartao"><b>API e MCP</b><p class="mudo"><a href="/openapi.json">/openapi.json</a> descreve cada operação; o MCP fica em <code>{e(base)}/mcp</code>. REST e MCP são a mesma tabela.</p></div>
<div class="cartao"><b>Arquivo de intercâmbio</b><p class="mudo"><code>agenda-clinica/1</code>: <a href="/schema/agenda-clinica-1.json">esquema JSON</a>. Exportar e importar uma clínica inteira, com pacientes só se pedido.</p></div>
<div class="cartao"><b>Texto completo</b><p class="mudo"><a href="/protocolo.md">PROTOCOLO.md</a>: escopos, erros, compatibilidade e o que cada servidor precisa fazer. <a href="/devs">Para devs</a>.</p></div></div>""",
                  desc="Contrato aberto do agenda-clinica: API REST, MCP e o arquivo de intercâmbio para migrar entre servidores.", canonical=f"{base}/protocolo" if base else "",
                  nav='<a href="/devs">Para devs</a><a href="/docs">Para agentes</a>', fundo="minimalista", modo="vidro")
