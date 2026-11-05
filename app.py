"""agenda-clinica: site de clínica com agendamento online, API REST e servidor MCP.

Só biblioteca padrão do Python (imagem pequena, nada para atualizar). Dados em SQLite na pasta DATA_DIR.

    python3 app.py            servidor em PORT (padrão 8080)
    python3 app.py demo       cria a clínica de demonstração em /c/demo (idempotente)
    python3 app.py backup X   cópia consistente do banco em X
    python3 app.py delistar X tira a clínica X do sitemap e a marca noindex (moderação; toda clínica nasce indexável); listar X desfaz
    python3 app.py metricas   clínicas, consultas por origem (web/api/mcp) e chaves em uso (sem dado de paciente)

Variáveis: PORT, DATA_DIR (padrão ./data), BASE_URL (ex.: https://agenda.exemplo.com), REPO_URL.
Rotas: ver ops.py (REST e MCP saem da mesma tabela) e paginas.py (site e painel).
"""
from __future__ import annotations

import ipaddress
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import nucleo as n
import ops
import paginas as pg

VERSAO = "1.0.0"
REPO_URL = os.environ.get("REPO_URL", "https://github.com/thiagopatzdorf/agenda-clinica")
MAX_CORPO = 64 * 1024
MCP_VERSOES = ("2025-06-18", "2025-03-26", "2024-11-05")
CSP = ("default-src 'self'; style-src 'unsafe-inline'; img-src 'self' https: data:; script-src 'none'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
INSTRUCOES_MCP = ("Agendamento de consultas. Fluxo: clinica_info -> horarios_livres -> agendar (guarde o `codigo`). "
                  "Nunca invente horário. Só envie consentimento=true se o paciente concordou. "
                  "O sistema não envia mensagens: avise o paciente ao cancelar ou remarcar. Não grave dado clínico.")


Limitador = n.Limitador


LIMITES_TAXA = {"criar": (5, 3600), "login": (10, 300), "agendar": (20, 3600), "api": (240, 60),
                # Por conta (e-mail), além do IP: força bruta distribuída por vários IPs não adivinha uma senha.
                "login_conta": (15, 3600)}
MAX_LOTE_MCP = 10
MAX_CONEXOES = 256
TIMEOUT_SOCKET_S = 15


def semear_demo(bd: n.Banco) -> None:
    if bd.um("select 1 from clinicas where slug='demo'"):
        return
    c = n.criar_clinica(bd, "Clínica Demonstração", "demo@exemplo.invalid", os.urandom(12).hex(), "demo")
    n.salvar_clinica(bd, bd.um("select * from clinicas where id=?", (c["id"],)), {
        "descricao": "Clínica fictícia para testar o agendamento e a API. Os dados daqui são de teste e podem ser apagados.",
        "cidade": "Florianópolis", "telefone": "48999990000"})
    cid = c["id"]
    centro = n.salvar_local(bd, cid, {"nome": "Unidade Centro", "endereco": "Rua Exemplo, 100", "cidade": "Florianópolis"})
    praia = n.salvar_local(bd, cid, {"nome": "Unidade Praia", "endereco": "Av. da Praia, 200", "cidade": "Florianópolis"})
    ana = n.salvar_profissional(bd, cid, {"nome": "Dra. Ana Lima", "especialidade": "Psicologia", "registro": "CRP 00/00000", "bio": "Atendimento adulto e de casal."})
    bia = n.salvar_profissional(bd, cid, {"nome": "Dra. Bia Souza", "especialidade": "Nutrição", "registro": "CRN 0/00000", "bio": "Reeducação alimentar e esportiva."})
    n.definir_disponibilidade(bd, cid, ana, [{"dia": d, "inicio": "09:00", "fim": "12:00", "local_id": centro} for d in (1, 3)]
                              + [{"dia": d, "inicio": "14:00", "fim": "18:00", "local_id": praia} for d in (2, 4)])
    n.definir_disponibilidade(bd, cid, bia, [{"dia": d, "inicio": "08:00", "fim": "12:00", "local_id": centro} for d in range(1, 6)])
    n.salvar_servico(bd, cid, {"nome": "Consulta", "duracao_min": 50, "preco_centavos": 20000})
    n.salvar_servico(bd, cid, {"nome": "Retorno", "duracao_min": 30, "preco_centavos": 12000})


def listar_clinica(bd: n.Banco, slug: str, listar: bool = True) -> None:
    """Moderação do operador. Toda clínica nasce `listada` (indexável e no sitemap: decisão do dono, "indexa tudo");
    `delistar` tira uma específica do índice (marca alheia, spam) sem apagar a página nem os dados."""
    n.clinica_por_slug(bd, slug)
    with bd.escrita() as con:
        con.execute("update clinicas set listada=? where slug=?", (1 if listar else 0, slug))


def metricas(bd: n.Banco) -> dict:
    """Números do lançamento, medidos no banco (sem dado de paciente): clínicas, consultas por origem, chaves de API em uso."""
    um = lambda sql: bd.um(sql)[0]
    return {"clinicas": um("select count(*) from clinicas where slug!='demo'"),
            "clinicas_com_agenda_montada": um("select count(distinct clinica_id) from disponibilidade d join profissionais p on p.id=d.profissional_id where p.clinica_id in (select id from clinicas where slug!='demo')"),
            "agendamentos_confirmados": um("select count(*) from agendamentos a join clinicas c on c.id=a.clinica_id where c.slug!='demo' and a.status='confirmado'"),
            "agendamentos_por_origem": {r[0]: r[1] for r in bd.ler("select a.origem, count(*) from agendamentos a join clinicas c on c.id=a.clinica_id where c.slug!='demo' group by 1")},
            "chaves_de_api_usadas": um("select count(*) from chaves where ultimo_uso is not null")}


def backup_diario(bd: n.Banco, pasta: Path, manter: int = 7) -> Path:
    destino = pasta / f"agenda-{dt.date.today():%Y%m%d}.db"
    pasta.mkdir(parents=True, exist_ok=True)
    if not destino.exists():
        bd.copia_segura(destino)
    for velho in sorted(pasta.glob("agenda-*.db"))[:-manter]:
        velho.unlink()
    return destino


class App:
    def __init__(self, bd: n.Banco, base_url: str = ""):
        self.bd, self.base_url, self.lim = bd, base_url.rstrip("/"), Limitador()

    def base(self, h) -> str:
        if self.base_url:
            return self.base_url
        host = h.headers.get("Host", "localhost").lower()
        if not re.fullmatch(r"[a-z0-9.-]+(:\d+)?", host):
            host = "localhost"
        # https por padrão: só localhost/127.* (desenvolvimento) fala http. O cabeçalho X-Forwarded-Proto, do cliente, não decide mais.
        return f"{'http' if host.startswith(('localhost', '127.')) else 'https'}://{host}"


def _cookie(h, nome: str) -> str:
    for parte in h.headers.get("Cookie", "").split(";"):
        k, _, v = parte.strip().partition("=")
        if k == nome:
            return v
    return ""


def ip_do_cliente(peer: str, cf_connecting_ip: str = "") -> str:
    """IP para o limite de taxa. `CF-Connecting-IP` só vale quando quem fala com o pod é um proxy interno (cloudflared:
    endereço privado; a NetworkPolicy só deixa o namespace `plataforma` chegar aqui). De peer público o cabeçalho é forjável
    e é ignorado; `X-Forwarded-For` nunca vale. IPv6 conta por /64, senão cada endereço do prefixo seria um cliente novo."""
    try:
        alvo = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not alvo.is_global:  # privado, loopback, link-local: só um proxy nosso fala assim
        try:
            alvo = ipaddress.ip_address(cf_connecting_ip.strip()) if cf_connecting_ip.strip() else alvo
        except ValueError:
            pass
    if alvo.version == 6:
        return str(ipaddress.ip_network(f"{alvo}/64", strict=False))
    return str(alvo)


def _ip(h) -> str:
    return ip_do_cliente(h.client_address[0], h.headers.get("CF-Connecting-IP", ""))


def _quinzena(bd, c, servico_id: int, prof: int | None = None) -> list[dict]:
    hoje = n.agora_local(c["tz"])[0]
    return n.horarios_livres(bd, c, servico_id, prof, hoje.isoformat(), (hoje + dt.timedelta(days=13)).isoformat(), limite=400)


def _auth_chave(app: App, h) -> tuple | None:
    cab = h.headers.get("Authorization", "")
    if cab.lower().startswith("bearer "):
        a = n.autenticar_chave(app.bd, cab[7:].strip())
        if not a:
            raise n.Erro(401, "chave_invalida", "chave de API inválida ou revogada")
        return a
    return None


def mcp(app: App, corpo, auth, ip: str = "") -> tuple[int, object]:
    """JSON-RPC 2.0 do MCP (Streamable HTTP, só POST e resposta JSON, sem sessão). Devolve (status HTTP, corpo)."""
    if isinstance(corpo, list):
        # Lote: no máximo MAX_LOTE_MCP itens e sem lista dentro de lista. Antes, 64 KB cabiam ~350 chamadas pesadas
        # (GBs de resposta) e um lote aninhado driblava a conta de agendamentos; o limite por requisição era 1.
        if not corpo or len(corpo) > MAX_LOTE_MCP or any(isinstance(m, list) for m in corpo):
            return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": f"lote inválido: de 1 a {MAX_LOTE_MCP} itens, sem listas aninhadas"}}
        resp = [r for r in (mcp(app, m, auth, ip)[1] for m in corpo) if r is not None]
        return (200, resp) if resp else (202, None)
    if not isinstance(corpo, dict) or corpo.get("jsonrpc") != "2.0":
        return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "requisição JSON-RPC 2.0 inválida"}}
    m, rid, p = corpo.get("method", ""), corpo.get("id"), corpo.get("params") or {}
    if rid is None and m.startswith("notifications/"):
        return 202, None

    def ok(r):
        return 200, {"jsonrpc": "2.0", "id": rid, "result": r}

    if m == "initialize":
        v = p.get("protocolVersion")
        return ok({"protocolVersion": v if v in MCP_VERSOES else MCP_VERSOES[0], "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "agenda-clinica", "version": VERSAO}, "instructions": INSTRUCOES_MCP})
    if m == "ping":
        return ok({})
    if m == "tools/list":
        return ok({"tools": ops.ferramentas_mcp(auth)})
    if m == "tools/call":
        try:
            nome = str(p.get("name", ""))
            # Cobrança POR CHAMADA (não por requisição): agendar tem teto por hora e cada chamada gasta o balde de requisições.
            if nome == "agendar" and not app.lim.passa("agendar", ip, *LIMITES_TAXA["agendar"]):
                raise n.Erro(429, "muitas_requisicoes", "limite de agendamentos por hora excedido")
            if not isinstance(p.get("arguments") or {}, dict):
                raise n.Erro(422, "argumentos_invalidos", "arguments deve ser um objeto")
            dados, _ = ops.executar(app.bd, nome, p.get("arguments") or {}, auth, origem="mcp")
            return ok({"content": [{"type": "text", "text": json.dumps(dados, ensure_ascii=False)}], "structuredContent": dados})
        except n.Erro as e:
            return ok({"isError": True, "content": [{"type": "text", "text": json.dumps({"erro": {"codigo": e.codigo, "mensagem": e.mensagem}}, ensure_ascii=False)}]})
    return 200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"método {m!r} não suportado"}}


def fazer_handler(app: App):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "agenda-clinica"
        # Sem timeout, 600 sockets que mandam meio cabeçalho seguravam 600 threads para sempre (slowloris).
        timeout = TIMEOUT_SOCKET_S

        def log_message(self, *a):  # log só de erro: não escreve IP nem URL de paciente
            pass

        # -------- saída
        def _enviar(self, status: int, corpo: bytes | str, tipo: str = "text/html; charset=utf-8", extra: dict | None = None):
            b = corpo.encode() if isinstance(corpo, str) else corpo
            for k, v in (extra or {}).items():
                # CR/LF num valor viraria cabeçalho novo (injeção); o valor vem de formulário em alguns redirecionamentos.
                if any(ch in str(v) + k for ch in "\r\n\x00"):
                    raise ValueError("valor de cabeçalho com caractere de controle")
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if tipo.startswith("text/html"):
                self.send_header("Content-Security-Policy", CSP)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b)

        def _json(self, status: int, obj, extra: dict | None = None):
            self._enviar(status, json.dumps(obj, ensure_ascii=False) if obj is not None else "", "application/json; charset=utf-8",
                         {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store", **(extra or {})})

        def _ir(self, destino: str, extra: dict | None = None):
            self._enviar(303, "", extra={"Location": destino, "Cache-Control": "no-store", **(extra or {})})

        def _corpo(self) -> bytes:
            return self._bruto  # lido em _rodar, antes de qualquer resposta (senão o keep-alive desalinha)

        def _form(self) -> dict:
            return {k: v[0] for k, v in urllib.parse.parse_qs(self._corpo().decode("utf-8", "replace"), keep_blank_values=True).items()}

        # -------- entrada
        def do_OPTIONS(self):
            self._enviar(204, "", "text/plain", {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
                                                 "Access-Control-Allow-Headers": "Authorization, Content-Type, Mcp-Protocol-Version", "Access-Control-Max-Age": "86400"})

        def do_GET(self): self._rodar("GET")
        def do_POST(self): self._rodar("POST")
        def do_PUT(self): self._rodar("PUT")
        def do_PATCH(self): self._rodar("PATCH")
        def do_DELETE(self): self._rodar("DELETE")

        def _rodar(self, metodo: str):
            u = urllib.parse.urlsplit(self.path)
            caminho, q = (u.path.rstrip("/") or "/"), {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            api = caminho.startswith("/api/v1/") or caminho == "/mcp"
            self._bruto = b""
            try:
                if self.headers.get("Transfer-Encoding"):
                    self.close_connection = True  # só lemos Content-Length: chunked desalinharia a conexão (contrabando de requisição)
                    raise n.Erro(400, "transfer_encoding", "Transfer-Encoding não é suportado; envie Content-Length")
                try:
                    tam = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    self.close_connection = True
                    raise n.Erro(400, "content_length", "Content-Length inválido") from None
                if tam > MAX_CORPO or tam < 0:
                    self.close_connection = True
                    raise n.Erro(413, "corpo_grande", "corpo da requisição grande demais")
                self._bruto = self.rfile.read(tam) if tam else b""
                if api:
                    self._api(metodo, caminho, q)
                else:
                    self._site(metodo, caminho, q)
            except n.Erro as e:
                if api:
                    self._json(e.status, {"erro": {"codigo": e.codigo, "mensagem": e.mensagem}})
                else:
                    self._enviar(e.status, pg.pagina("Ops", f"<h1>{e.status}</h1><p>{pg.e(e.mensagem)}</p><p><a href='/'>Voltar ao início</a></p>", indexar=False))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as ex:  # nunca devolve rastro ao cliente
                print(f"erro interno em {metodo} {caminho}: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
                if api:
                    self._json(500, {"erro": {"codigo": "erro_interno", "mensagem": "erro interno"}})
                else:
                    self._enviar(500, pg.pagina("Erro", "<h1>Algo deu errado</h1><p>Tente de novo em instantes.</p>", indexar=False))

        # -------- API REST e MCP
        def _api(self, metodo: str, caminho: str, q: dict):
            if not app.lim.passa("api", _ip(self), *LIMITES_TAXA["api"]):
                raise n.Erro(429, "muitas_requisicoes", "limite de requisições por minuto excedido")
            auth = _auth_chave(app, self)
            if caminho == "/mcp":
                if metodo != "POST":
                    return self._json(405, {"erro": {"codigo": "metodo", "mensagem": "use POST (JSON-RPC)"}}, {"Allow": "POST"})
                try:
                    corpo = json.loads(self._corpo() or b"null")
                except ValueError:
                    return self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}})
                # Cada chamada além da primeira de um lote gasta o balde geral: lote não é atalho em volta do limite.
                for _ in range(max(0, (len(corpo) if isinstance(corpo, list) else 1) - 1)):
                    if not app.lim.passa("api", _ip(self), *LIMITES_TAXA["api"]):
                        raise n.Erro(429, "muitas_requisicoes", "limite de requisições por minuto excedido")
                st, resp = mcp(app, corpo, auth, _ip(self))
                return self._json(st, resp)
            achou = ops.rota(metodo, caminho[len("/api/v1"):])
            if not achou:
                raise n.Erro(404, "rota_desconhecida", f"{metodo} {caminho} não existe; veja /openapi.json")
            o, em_caminho = achou
            args = {**q}
            if metodo in ("POST", "PUT", "PATCH"):
                try:
                    b = json.loads(self._corpo() or b"{}")
                except ValueError:
                    raise n.Erro(400, "json_invalido", "corpo não é JSON válido") from None
                if not isinstance(b, dict):
                    raise n.Erro(400, "json_invalido", "o corpo deve ser um objeto JSON")
                args.update(b)
            args.update(em_caminho)
            if o["nome"] == "agendar" and not app.lim.passa("agendar", _ip(self), *LIMITES_TAXA["agendar"]):
                raise n.Erro(429, "muitas_requisicoes", "limite de agendamentos por hora excedido")
            dados, st = ops.executar(app.bd, o["nome"], args, auth, origem="api")
            self._json(st, dados)

        # -------- site e painel
        def _site(self, metodo: str, caminho: str, q: dict):
            base = app.base(self)
            if caminho == "/health":
                return self._enviar(200, "ok", "text/plain")
            if caminho == "/robots.txt":
                return self._enviar(200, f"User-agent: *\nAllow: /\nDisallow: /painel\nDisallow: /api/\nDisallow: /m/\nSitemap: {base}/sitemap.xml\n", "text/plain")
            if caminho == "/sitemap.xml":
                urls = ["", "/docs", "/privacidade"] + [f"/c/{r['slug']}" for r in app.bd.ler("select slug from clinicas where listada=1 order by id limit 5000")]
                return self._enviar(200, '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                    + "".join(f"<url><loc>{pg.e(base + u)}</loc></url>" for u in urls) + "</urlset>", "application/xml")
            if caminho == "/openapi.json" and metodo == "GET":
                return self._json(200, ops.openapi(base))
            if caminho == "/llms.txt":
                return self._enviar(200, ops.llms_txt(base), "text/plain; charset=utf-8")
            if caminho == "/docs":
                return self._enviar(200, pg.docs(base))
            if caminho == "/privacidade":
                return self._enviar(200, pg.privacidade())
            if caminho == "/":
                return self._enviar(200, pg.home(REPO_URL, bool(app.bd.um("select 1 from clinicas where slug='demo'"))))
            if caminho == "/criar" and metodo == "POST":
                if not app.lim.passa("criar", _ip(self), *LIMITES_TAXA["criar"]):
                    raise n.Erro(429, "muitas_requisicoes", "muitas clínicas criadas deste endereço; tente mais tarde")
                if not app.lim.passa("criar_global", "*", n.LIMITES["clinicas_novas_por_dia"], 86400):
                    raise n.Erro(429, "cadastros_pausados", "o limite diário de novas clínicas foi atingido; tente amanhã")
                f = self._form()
                try:
                    n.criar_clinica(app.bd, f.get("nome", ""), f.get("email", ""), f.get("senha", ""))
                except n.Erro as e:
                    return self._enviar(e.status, pg.home(REPO_URL, False, e.mensagem))
                return self._entrar_e_ir(f.get("email", ""), f.get("senha", ""), "/painel/equipe?" + urllib.parse.urlencode(
                    {"msg": "Clínica criada. Cadastre locais, profissionais, serviços e horários."}))
            if caminho == "/entrar":
                if metodo == "GET":
                    return self._enviar(200, pg.entrar())
                if not app.lim.passa("login", _ip(self), *LIMITES_TAXA["login"]):
                    raise n.Erro(429, "muitas_requisicoes", "muitas tentativas de login; aguarde alguns minutos")
                f = self._form()
                if not app.lim.passa("login_conta", f.get("email", "").strip().lower()[:120], *LIMITES_TAXA["login_conta"]):
                    raise n.Erro(429, "muitas_requisicoes", "muitas tentativas para esta conta; aguarde")
                try:
                    return self._entrar_e_ir(f.get("email", ""), f.get("senha", ""), "/painel")
                except n.Erro as e:
                    return self._enviar(e.status, pg.entrar(e.mensagem))
            if caminho == "/sair":
                tok = _cookie(self, "sessao")
                if tok:
                    n.sair(app.bd, tok)
                return self._ir("/", {"Set-Cookie": "sessao=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"})
            if caminho.startswith("/painel"):
                return self._painel(metodo, caminho, q, base)
            partes = caminho.strip("/").split("/")
            if partes[0] == "c" and len(partes) in (2, 3):
                return self._clinica(metodo, partes, q, base)
            if partes[0] == "m" and len(partes) in (2, 3):
                return self._paciente(metodo, partes, base)
            raise n.Erro(404, "nao_encontrado", "página não encontrada")

        def _entrar_e_ir(self, email: str, senha: str, destino: str):
            tok = n.entrar(app.bd, email, senha)
            seguro = "; Secure" if app.base(self).startswith("https") else ""
            self._ir(destino, {"Set-Cookie": f"sessao={tok}; Max-Age=1209600; Path=/; HttpOnly; SameSite=Lax{seguro}"})

        def _clinica(self, metodo, partes, q, base):
            c = n.clinica_por_slug(app.bd, partes[1])
            info = n.info_publica(app.bd, c)
            if len(partes) == 2:
                return self._enviar(200, pg.site_clinica(info, base))
            if partes[2] != "agendar":
                raise n.Erro(404, "nao_encontrado", "página não encontrada")
            if metodo == "POST":
                if not app.lim.passa("agendar", _ip(self), *LIMITES_TAXA["agendar"]):
                    raise n.Erro(429, "muitas_requisicoes", "muitos agendamentos deste endereço; tente mais tarde")
                f = self._form()
                try:
                    ag = n.agendar(app.bd, c, int(f.get("servico") or 0), int(f.get("profissional") or 0), f.get("data", ""), f.get("hora", ""),
                                   f.get("nome", ""), f.get("telefone", ""), f.get("email", ""), "web", f.get("consentimento") == "1")
                except n.Erro as e:
                    qq = {k: f.get(k, "") for k in ("servico", "profissional", "data", "hora")}
                    hs = _quinzena(app.bd, c, int(f.get("servico") or 0)) if _ascii_digitos(f.get("servico", "")) else []
                    return self._enviar(e.status, pg.agendar(info, hs, qq, e.mensagem))
                return self._enviar(201, pg.agendado(info, ag, base), extra={"Cache-Control": "no-store"})
            sid = int(q["servico"]) if _ascii_digitos(q.get("servico", "")) else 0
            hs = _quinzena(app.bd, c, sid) if any(s["id"] == sid for s in info["servicos"]) else []
            return self._enviar(200, pg.agendar(info, hs, q))

        def _paciente(self, metodo, partes, base):
            r, c = n.agendamento_por_codigo(app.bd, partes[1])
            clin = {"nome": c["nome"], "slug": c["slug"]}
            acao = partes[2] if len(partes) == 3 else ""
            ver = lambda erro="": self._enviar(200, pg.consulta(n._ag_dict(app.bd, r, False), clin, erro), extra={"Cache-Control": "no-store"})
            if not acao:
                return ver()
            if acao == "cancelar" and metodo == "POST":
                try:
                    n.cancelar(app.bd, r, "paciente")
                except n.Erro as e:
                    return ver(e.mensagem)
                return self._ir(f"/m/{r['codigo']}")
            if acao == "remarcar":
                ag = n._ag_dict(app.bd, r, False)
                profs = {p["id"]: p["nome"] for p in app.bd.ler("select id,nome from profissionais where clinica_id=?", (c["id"],))}
                if metodo == "POST":
                    f = self._form()
                    try:
                        n.remarcar(app.bd, c, r, f.get("data", ""), f.get("hora", ""), int(f.get("profissional") or 0) or None, "paciente")
                    except n.Erro as e:
                        return self._enviar(e.status, pg.remarcar_paciente(ag, clin, _quinzena(app.bd, c, r["servico_id"]), profs, e.mensagem))
                    return self._ir(f"/m/{r['codigo']}")
                return self._enviar(200, pg.remarcar_paciente(ag, clin, _quinzena(app.bd, c, r["servico_id"]), profs))
            raise n.Erro(404, "nao_encontrado", "página não encontrada")

        def _painel(self, metodo, caminho, q, base):
            tok = _cookie(self, "sessao")
            c = n.clinica_da_sessao(app.bd, tok)
            if not c:
                return self._ir("/entrar")
            nocache = {"Cache-Control": "no-store"}
            if caminho == "/painel/acao" and metodo == "POST":
                f = self._form()
                if f.get("csrf") != n.csrf_de(tok):
                    raise n.Erro(403, "csrf", "sessão expirada ou formulário inválido; recarregue a página")
                return self._acao(c, tok, f, base)
            if metodo != "GET":
                raise n.Erro(405, "metodo", "método não permitido")
            info = n.info_publica(app.bd, c)
            if caminho == "/painel":
                dia = n.data_valida(q["data"]) if q.get("data") else n.agora_local(c["tz"])[0]
                ags = n.listar_agendamentos(app.bd, c, dia.isoformat())
                return self._enviar(200, pg.painel(c, tok, dia, ags, n.listar_bloqueios(app.bd, c), info["profissionais"], q.get("msg", ""), q.get("erro", "")), extra=nocache)
            if caminho == "/painel/equipe":
                return self._enviar(200, pg.equipe(c, tok, info, q.get("msg", ""), q.get("erro", "")), extra=nocache)
            if caminho == "/painel/api":
                return self._enviar(200, pg.painel_api(c, tok, n.listar_chaves(app.bd, c["id"]), base), extra=nocache)
            if caminho == "/painel/remarcar":
                r = n.agendamento_da_clinica(app.bd, c, int(q.get("id") or 0))
                return self._enviar(200, pg.remarcar_painel(c, tok, n._ag_dict(app.bd, r), _quinzena(app.bd, c, r["servico_id"]),
                                                            {p["id"]: p["nome"] for p in info["profissionais"]}), extra=nocache)
            raise n.Erro(404, "nao_encontrado", "página não encontrada")

        def _acao(self, c, tok: str, f: dict, base: str):
            volta = f.get("volta", "/painel")
            if not volta.startswith("/painel") or "//" in volta or any(ord(ch) < 32 for ch in volta):
                volta = "/painel"  # nunca redireciona para fora do painel
            a = f.get("acao", "")
            try:
                if a not in ACOES:
                    raise n.Erro(400, "acao", "ação desconhecida")
                msg = ACOES[a](app.bd, c, f)
            except n.Erro as e:
                if a == "criar_chave":
                    return self._enviar(e.status, pg.painel_api(c, tok, n.listar_chaves(app.bd, c["id"]), base, erro=e.mensagem))
                return self._ir(volta + ("&" if "?" in volta else "?") + urllib.parse.urlencode({"erro": e.mensagem}))
            if isinstance(msg, dict):  # chave recém-criada: mostra uma única vez, sem redirecionar
                return self._enviar(201, pg.painel_api(c, tok, n.listar_chaves(app.bd, c["id"]), base, nova=msg), extra={"Cache-Control": "no-store"})
            self._ir(volta + ("&" if "?" in volta else "?") + urllib.parse.urlencode({"msg": msg}))

    return H


# ---- ações do painel: cada uma devolve a mensagem de sucesso (ou a chave nova)

def _ascii_digitos(t: str) -> bool:
    """isdigit() aceita "²" e int("²") levanta ValueError (500 no site); aqui só 0-9."""
    return t.isascii() and t.isdigit()


def _i(v, padrao=None):
    t = str(v or "").strip().lstrip("-")
    return int(v) if t.isascii() and t.isdigit() else padrao


def _a_cancelar(bd, c, f):
    n.cancelar(bd, n.agendamento_da_clinica(bd, c, _i(f.get("id"), 0)), "clinica")
    return "Consulta cancelada. Avise o paciente."


def _a_remarcar(bd, c, f):
    n.remarcar(bd, c, n.agendamento_da_clinica(bd, c, _i(f.get("id"), 0)), f.get("data", ""), f.get("hora", ""), _i(f.get("profissional_id")), "clinica")
    return "Consulta remarcada. Avise o paciente."


def _a_bloquear(bd, c, f):
    b = n.bloquear(bd, c, f.get("inicio", ""), f.get("fim", ""), _i(f.get("profissional_id")), f.get("motivo", ""), f.get("cancelar_conflitos") == "1")
    return "Agenda bloqueada." + (f" {len(b['consultas_canceladas'])} consulta(s) cancelada(s): avise os pacientes." if b["consultas_canceladas"] else "")


def _a_remover_bloqueio(bd, c, f):
    n.remover_bloqueio(bd, c, _i(f.get("id"), 0))
    return "Bloqueio removido."


def _a_clinica(bd, c, f):
    n.salvar_clinica(bd, c, {k: f[k] for k in ("nome", "descricao", "telefone", "email", "cidade", "passo_min", "antecedencia_min") if k in f})
    return "Dados salvos."


def _a_local(bd, c, f):
    n.salvar_local(bd, c["id"], f)
    return "Local salvo."


def _a_profissional(bd, c, f):
    n.salvar_profissional(bd, c["id"], f)
    return "Profissional salvo(a)."


def _a_servico(bd, c, f):
    reais = str(f.get("preco") or "").replace(",", ".").strip()
    try:
        preco = round(float(reais) * 100) if reais else None
    except ValueError:
        raise n.Erro(422, "preco_invalido", "preço inválido") from None
    n.salvar_servico(bd, c["id"], {"nome": f.get("nome"), "duracao_min": f.get("duracao_min") or 30, "preco_centavos": preco})
    return "Serviço salvo."


def _a_disponibilidade(bd, c, f):
    janelas = []
    for d in range(7):
        for k in range(2):
            ini, fim = f.get(f"i{d}_{k}", ""), f.get(f"f{d}_{k}", "")
            if ini and fim:
                janelas.append({"dia": d, "inicio": ini, "fim": fim, "local_id": _i(f.get(f"l{d}_{k}"), 0)})
    n.definir_disponibilidade(bd, c["id"], _i(f.get("profissional_id"), 0), janelas)
    return "Horários salvos."


def _a_criar_chave(bd, c, f):
    return n.criar_chave(bd, c["id"], f.get("nome", ""), f.get("escopo", "leitura"))


def _a_revogar_chave(bd, c, f):
    n.revogar_chave(bd, c["id"], _i(f.get("id"), 0))
    return "Chave revogada."


ACOES = {"cancelar": _a_cancelar, "remarcar": _a_remarcar, "bloquear": _a_bloquear, "remover_bloqueio": _a_remover_bloqueio,
         "clinica": _a_clinica, "salvar_local": _a_local, "salvar_profissional": _a_profissional, "salvar_servico": _a_servico,
         "disponibilidade": _a_disponibilidade, "criar_chave": _a_criar_chave, "revogar_chave": _a_revogar_chave}


class Servidor(ThreadingHTTPServer):
    """Uma thread por conexão, com teto: passou de `max_conexoes`, a nova é derrubada em vez de empilhar thread."""
    daemon_threads = True

    def __init__(self, *a, max_conexoes: int = MAX_CONEXOES, **k):
        super().__init__(*a, **k)
        self._vagas = threading.BoundedSemaphore(max_conexoes)

    def process_request(self, request, client_address):
        if not self._vagas.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._vagas.release()


def servidor(pasta: str | Path, porta: int = 0, base_url: str = "", max_conexoes: int = MAX_CONEXOES) -> tuple[Servidor, App]:
    app = App(n.Banco(pasta), base_url)
    return Servidor(("0.0.0.0", porta), fazer_handler(app), max_conexoes=max_conexoes), app


def _rotina_backup(bd: n.Banco, pasta: Path):
    while True:
        try:
            n.purgar_sessoes(bd)
            backup_diario(bd, pasta)
        except Exception as ex:
            print(f"backup falhou: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
        time.sleep(6 * 3600)


if __name__ == "__main__":
    dados = Path(os.environ.get("DATA_DIR", "data"))
    if sys.argv[1:2] == ["demo"]:
        semear_demo(n.Banco(dados))
        print("clínica demo pronta em /c/demo")
    elif sys.argv[1:2] in (["listar"], ["delistar"]) and len(sys.argv) == 3:
        listar_clinica(n.Banco(dados), sys.argv[2], sys.argv[1] == "listar")
        print(f"{sys.argv[2]}: {'listada' if sys.argv[1] == 'listar' else 'fora da lista'}")
    elif sys.argv[1:2] == ["metricas"]:
        print(json.dumps(metricas(n.Banco(dados)), ensure_ascii=False, indent=2))
    elif sys.argv[1:2] == ["backup"] and len(sys.argv) == 3:
        n.Banco(dados).copia_segura(sys.argv[2])
        print("backup em", sys.argv[2])
    else:
        srv, app = servidor(dados, int(os.environ.get("PORT", "8080")), os.environ.get("BASE_URL", ""))
        if os.environ.get("DEMO", "") == "1":
            semear_demo(app.bd)
        threading.Thread(target=_rotina_backup, args=(app.bd, dados / "backups"), daemon=True).start()
        print(f"agenda-clinica {VERSAO} em :{srv.server_address[1]} (dados em {dados})", flush=True)
        srv.serve_forever()
