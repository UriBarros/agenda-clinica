"""Login de dev com Google e GitHub, provado contra um provedor FALSO local (nenhuma chamada à internet)."""
import base64
import hashlib
import http.server
import json
import threading
import urllib.parse

import pytest

import app as ap
import devs as dv
import nucleo as n
import oauth as oa
from test_http import req


class Provedor(http.server.BaseHTTPRequestHandler):
    """Faz o papel do Google e do GitHub: /token troca o código (conferindo segredo e PKCE) e /userinfo, /user, /emails dizem quem é."""
    identidades: dict = {}   # código -> {"google": {...}, "github": {"user": {...}, "emails": [...]}}
    desafios: dict = {}      # código -> code_challenge da etapa de autorização

    def log_message(self, *a): pass

    def _json(self, st, d):
        b = json.dumps(d).encode()
        self.send_response(st)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        f = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        cod = f.get("code", "")
        desafio = base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
        if f.get("client_secret") != "segredo-x" or cod not in self.identidades or self.desafios.get(cod) != desafio:
            return self._json(400, {"error": "invalid_grant"})
        self._json(200, {"access_token": "tok-" + cod})

    def do_GET(self):
        cod = (self.headers.get("Authorization") or "")[len("Bearer tok-"):]
        ident = self.identidades.get(cod)
        if not ident:
            return self._json(401, {})
        if self.path == "/userinfo":
            return self._json(200, ident["google"])
        self._json(200, ident["github"]["emails"] if self.path == "/emails" else ident["github"]["user"])


@pytest.fixture
def prov(monkeypatch):
    Provedor.identidades, Provedor.desafios = {}, {}
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provedor)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    for p, urls in {"google": {"token": base + "/token", "usuario": base + "/userinfo"}, "github": {"token": base + "/token", "usuario": base + "/user", "emails": base + "/emails"}}.items():
        for k, v in urls.items():
            monkeypatch.setitem(oa.PROVEDORES[p], k, v)
    for p in ("GOOGLE", "GITHUB"):
        monkeypatch.setenv(f"{p}_CLIENT_ID", "id-x")
        monkeypatch.setenv(f"{p}_CLIENT_SECRET", "segredo-x")
    yield s
    s.shutdown()
    s.server_close()


@pytest.fixture
def srv(tmp_path, prov):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def _google(email="g@x.test", verificado=True, sub="g-1"):
    return {"google": {"sub": sub, "email": email, "email_verified": verificado, "name": "Gê"}, "github": {}}


def _github(emails, uid=77, publico="publico@x.test"):
    return {"google": {}, "github": {"user": {"id": uid, "login": "gh", "name": "Gi", "email": publico}, "emails": emails}}


def _login(porta, provedor, codigo, identidade, *, estado_errado=False, sem_cookie=False, verificador_errado=False):
    """Percorre o fluxo inteiro: início (cookie + endereço do provedor) -> o provedor devolve o código -> retorno."""
    st, _, r = req(porta, "GET", f"/entrar/{provedor}")
    assert st in (302, 303)
    destino = urllib.parse.urlparse(r.getheader("Location"))
    q = {k: v[0] for k, v in urllib.parse.parse_qs(destino.query).items()}
    cookie = r.getheader("Set-Cookie").split(";")[0]
    if verificador_errado:
        cookie = cookie.split(".")[0] + ".verificador-trocado"
    Provedor.identidades[codigo] = identidade
    Provedor.desafios[codigo] = q["code_challenge"]
    estado = "estado-forjado" if estado_errado else q["state"]
    return req(porta, "GET", f"/entrar/{provedor}/retorno?code={codigo}&state={estado}", cab=None if sem_cookie else {"Cookie": cookie}), q, r


def test_sem_credencial_configurada_nao_ha_rota_nem_botao(tmp_path, monkeypatch):
    for p in ("GOOGLE", "GITHUB"):
        monkeypatch.delenv(f"{p}_CLIENT_ID", raising=False)
        monkeypatch.delenv(f"{p}_CLIENT_SECRET", raising=False)
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    porta = s.server_address[1]
    assert req(porta, "GET", "/entrar/google")[0] == 404 and req(porta, "GET", "/entrar/github/retorno?code=x&state=y")[0] == 404
    assert "Continuar com" not in req(porta, "GET", "/dev/cadastro")[1]
    s.shutdown()
    s.server_close()


def test_com_credencial_aparecem_os_botoes_e_o_inicio_leva_ao_provedor_com_pkce_e_cookie_restrito(srv):
    porta, _ = srv
    html = req(porta, "GET", "/dev/entrar")[1]
    assert "Continuar com Google" in html and "Continuar com GitHub" in html
    st, _, r = req(porta, "GET", "/entrar/github")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(r.getheader("Location")).query).items()}
    assert q["client_id"] == "id-x" and q["redirect_uri"] == "http://t.test/entrar/github/retorno" and q["code_challenge_method"] == "S256" and q["state"]
    cookie = r.getheader("Set-Cookie")
    assert "Path=/entrar" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie and q["state"] in cookie
    assert "verifier" not in r.getheader("Location") and "segredo" not in r.getheader("Location")


def test_login_google_cria_a_conta_uma_vez_e_o_segundo_login_volta_na_mesma(srv):
    porta, a = srv
    (st, _, r), _, _ = _login(porta, "google", "c1", _google())
    assert st in (302, 303) and r.getheader("Location") == "/dev" and "dev_sessao=" in r.getheader("Set-Cookie") and "Path=/dev" in r.getheader("Set-Cookie")
    d = a.bd.um("select * from devs where email='g@x.test'")
    assert d["google_sub"] == "g-1" and d["senha"] == ""
    _login(porta, "google", "c2", _google())
    assert a.bd.um("select count(*) q from devs")["q"] == 1
    tok = r.getheader("Set-Cookie").split(";")[0].split("=", 1)[1]
    assert dv.dev_da_sessao(a.bd, tok)["id"] == d["id"]


def test_login_liga_a_conta_que_ja_existe_com_o_mesmo_email_verificado(srv):
    porta, a = srv
    antiga = dv.criar(a.bd, "g@x.test", "senha-bem-longa")
    _login(porta, "google", "c1", _google())
    assert a.bd.um("select count(*) q from devs")["q"] == 1 and a.bd.um("select google_sub from devs where id=?", (antiga["id"],))["google_sub"] == "g-1"


def test_email_nao_verificado_no_provedor_e_recusado_e_nao_cria_nem_liga_conta(srv):
    porta, a = srv
    dv.criar(a.bd, "vitima@x.test", "senha-bem-longa")
    (st, html, _), _, _ = _login(porta, "google", "c1", _google("vitima@x.test", verificado=False, sub="atacante"))
    assert st == 422 and "verificado" in html
    assert a.bd.um("select google_sub from devs where email='vitima@x.test'")["google_sub"] is None and a.bd.um("select count(*) q from devs")["q"] == 1


def test_github_usa_so_o_email_primario_verificado_e_ignora_o_do_perfil(srv):
    porta, a = srv
    emails = [{"email": "outro@x.test", "primary": False, "verified": True}, {"email": "Principal@X.test", "primary": True, "verified": True}]
    _login(porta, "github", "c1", _github(emails))
    d = a.bd.um("select * from devs")
    assert d["email"] == "principal@x.test" and d["github_id"] == "77"
    (st, _, _), _, _ = _login(porta, "github", "c2", _github([{"email": "nao@x.test", "primary": True, "verified": False}], uid=88))
    assert st == 422 and a.bd.um("select count(*) q from devs")["q"] == 1  # sem e-mail verificado não entra, mesmo com e-mail público no perfil


@pytest.mark.parametrize("falha", ["estado_errado", "sem_cookie", "verificador_errado"])
def test_retorno_sem_estado_valido_ou_com_pkce_trocado_nao_loga_ninguem(srv, falha):
    porta, a = srv
    (st, html, r), _, _ = _login(porta, "google", "c1", _google(), **{falha: True})
    assert st in (400, 401) and "dev_sessao" not in (r.getheader("Set-Cookie") or "") and a.bd.um("select count(*) q from devs")["q"] == 0


def test_provedor_que_recusa_ou_cai_vira_erro_na_pagina_sem_criar_conta(srv, prov):
    porta, a = srv
    st, html, _ = req(porta, "GET", "/entrar/google/retorno?error=access_denied&state=x")
    assert st == 401 and a.bd.um("select count(*) q from devs")["q"] == 0
    prov.shutdown()
    prov.server_close()
    (st, html, _), _, _ = _login_sem_provedor(porta)
    assert st == 502 and "provedor" in html


def _login_sem_provedor(porta):
    _, _, r = req(porta, "GET", "/entrar/google")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(r.getheader("Location")).query).items()}
    return req(porta, "GET", f"/entrar/google/retorno?code=c&state={q['state']}", cab={"Cookie": r.getheader("Set-Cookie").split(";")[0]}), q, r


def test_conta_nova_pelo_google_respeita_o_limite_diario_mas_quem_ja_tem_conta_entra(srv):
    porta, a = srv
    _login(porta, "google", "c1", _google())
    a.lim.passa("dev_novo_global", "*", 0, 86400)  # zera o balde: nenhuma conta nova hoje
    for _ in range(n.LIMITES["devs_novos_por_dia"]):
        a.lim.passa("dev_novo_global", "*", n.LIMITES["devs_novos_por_dia"], 86400)
    (st, _, _), _, _ = _login(porta, "google", "c2", _google("outro@x.test", sub="g-2"))
    assert st == 429 and a.bd.um("select count(*) q from devs")["q"] == 1
    (st, _, r), _, _ = _login(porta, "google", "c3", _google())
    assert st in (302, 303) and "dev_sessao=" in r.getheader("Set-Cookie")
