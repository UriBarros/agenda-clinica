"""Achados da revisão de segurança de 05/11 (um agente atacou o código; cada defeito real virou um teste).
O nome descreve a falha que o teste impede."""
import datetime as dt
import http.client
import json
import socket
import sqlite3
import threading
import urllib.parse

import pytest

import app as ap
import nucleo as n
import ops
from conftest import proxima


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "LIM_CLINICA", n.Limitador())
    s, a = ap.servidor(tmp_path, 0, "")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    ap.semear_demo(a.bd)
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def rq(porta, metodo, caminho, corpo=None, cab=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=20)
    h = dict(cab or {})
    if corpo is not None:
        raw, h["Content-Type"] = json.dumps(corpo), "application/json"
    c.request(metodo, caminho, raw, h)
    r = c.getresponse()
    t = r.read().decode()
    c.close()
    return r.status, t, r


def chamada(i, nome, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": nome, "arguments": args}}


def demo(a):
    c = n.clinica_por_slug(a.bd, "demo")
    info = n.info_publica(a.bd, c)
    return c, info["servicos"][1]["id"], info["profissionais"][1]["id"]


def horarios_demo(a, c, sv, prof, quantos):
    hoje = n.agora_local(c["tz"])[0]
    return n.horarios_livres(a.bd, c, sv, prof, hoje.isoformat(), (hoje + dt.timedelta(days=13)).isoformat())[:quantos]


# ---------------------------------------------------------------- MCP em lote (A1, M1)

def test_lote_mcp_acima_do_teto_e_recusado_sem_executar_nenhuma_chamada(srv):
    porta, a = srv
    c, sv, _ = demo(a)
    hoje = n.agora_local(c["tz"])[0].isoformat()
    lote = [chamada(i, "horarios_livres", {"clinica": "demo", "servico_id": sv, "de": hoje}) for i in range(ap.MAX_LOTE_MCP + 1)]
    st, t, _ = rq(porta, "POST", "/mcp", lote)
    assert st == 400 and json.loads(t)["error"]["code"] == -32600
    assert rq(porta, "POST", "/mcp", lote[: ap.MAX_LOTE_MCP])[0] == 200  # no teto ainda passa


def test_lote_mcp_aninhado_nao_driblia_a_conta_de_agendamentos(srv):
    porta, a = srv
    st, t, _ = rq(porta, "POST", "/mcp", [[chamada(1, "clinica_info", {"clinica": "demo"})]])
    assert st == 400
    assert rq(porta, "POST", "/mcp", [])[0] == 400


def test_agendar_em_lotes_mcp_e_cobrado_por_chamada_e_nao_passa_de_20_por_hora(srv):
    porta, a = srv
    c, sv, prof = demo(a)
    slots = horarios_demo(a, c, sv, prof, 30)
    assert len(slots) == 30
    ok = 0
    for ini in range(0, 30, 10):  # três requisições de 10 chamadas
        lote = [chamada(i, "agendar", {"clinica": "demo", "servico_id": sv, "profissional_id": prof, "data": s["data"], "hora": s["hora"],
                                       "nome": "x", "telefone": f"4899999{ini + i:04d}", "consentimento": True}) for i, s in enumerate(slots[ini:ini + 10])]
        st, t, _ = rq(porta, "POST", "/mcp", lote)
        assert st == 200
        ok += sum(1 for r in json.loads(t) if not r["result"].get("isError"))
    assert ok == ap.LIMITES_TAXA["agendar"][0]


# ---------------------------------------------------------------- conexões e protocolo (M2, smuggling)

def test_conexao_parada_nao_segura_thread_para_sempre_e_o_teto_de_conexoes_derruba_a_excedente(tmp_path):
    handler = ap.fazer_handler(ap.App(n.Banco(tmp_path)))
    assert handler.timeout == ap.TIMEOUT_SOCKET_S == 15
    s, _ = ap.servidor(tmp_path / "d", 0, "", max_conexoes=2)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    porta = s.server_address[1]
    ocupadas = [socket.create_connection(("127.0.0.1", porta)) for _ in range(2)]
    try:
        terceira = socket.create_connection(("127.0.0.1", porta))
        terceira.settimeout(5)
        assert terceira.recv(1) == b""  # o servidor fechou em vez de abrir uma 3ª thread
        terceira.close()
    finally:
        for o in ocupadas:
            o.close()
        s.shutdown()
        s.server_close()


def test_transfer_encoding_e_content_length_invalido_sao_recusados_com_400(srv):
    porta, _ = srv
    assert rq(porta, "POST", "/api/v1/clinicas/demo/agendamentos", cab={"Transfer-Encoding": "chunked"}, raw="0\r\n\r\n")[0] == 400
    sock = socket.create_connection(("127.0.0.1", porta))
    sock.sendall(b"POST /mcp HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
    sock.settimeout(5)
    assert sock.recv(64).startswith(b"HTTP/1.1 400")
    sock.close()


# ---------------------------------------------------------------- IP e limites de taxa (M3)

def test_cabecalho_de_ip_forjado_so_vale_vindo_de_proxy_interno_e_ipv6_conta_por_prefixo():
    assert ap.ip_do_cliente("8.8.8.8", "1.2.3.4") == "8.8.8.8"      # peer público: cabeçalho é forjável, ignorado
    assert ap.ip_do_cliente("10.0.0.5", "1.2.3.4") == "1.2.3.4"             # cloudflared (privado): vale o IP que a Cloudflare pôs
    assert ap.ip_do_cliente("10.0.0.5", "lixo") == "10.0.0.5"
    assert ap.ip_do_cliente("2001:db8::1", "") == ap.ip_do_cliente("2001:db8::ffff", "") == "2001:db8::/64"


def test_login_tem_limite_por_conta_mesmo_trocando_de_ip_a_cada_tentativa(srv):
    porta, _ = srv
    codigos = [rq(porta, "POST", "/entrar", cab={"CF-Connecting-IP": f"203.0.113.{i}", "Content-Type": "application/x-www-form-urlencoded"},
                  raw="email=alvo%40x.test&senha=errada-errada")[0] for i in range(18)]
    assert codigos[:15] == [401] * 15 and 429 in codigos[15:]


def test_limitador_nao_cresce_sem_fim_nem_varre_a_tabela_a_cada_requisicao():
    lim = n.Limitador()
    lim.TETO = 50
    for i in range(500):
        assert lim.passa("b", f"chave-{i}", 5, 3600, agora=1000.0 + i)
    assert len(lim._t) <= lim.TETO


# ---------------------------------------------------------------- cabeçalhos e entrada (B2, B4, B7, B9, B11)

def _sessao(a, email="dono@x.test", nome="Clínica X"):
    c = n.criar_clinica(a.bd, nome, email, "senha-bem-longa-1")
    return c, n.entrar(a.bd, email, "senha-bem-longa-1")


def test_quebra_de_linha_no_destino_do_redirecionamento_do_painel_nao_vira_cabecalho(srv):
    porta, a = srv
    _, tok = _sessao(a)
    form = urllib.parse.urlencode({"csrf": n.csrf_de(tok), "acao": "salvar_local", "nome": "L", "volta": "/painel\r\nX-Injected: yes"})
    st, _, r = rq(porta, "POST", "/painel/acao", cab={"Cookie": f"sessao={tok}", "Content-Type": "application/x-www-form-urlencoded"}, raw=form)
    assert st == 303 and r.getheader("X-Injected") is None
    assert "\r" not in r.getheader("Location") and r.getheader("Location").startswith("/painel?")


def test_cookie_de_sessao_leva_secure_fora_do_localhost_mesmo_sem_cabecalho_de_proxy(srv):
    porta, _ = srv
    form = "nome=Clinica+Cookie&email=c%40cookie.test&senha=senha-bem-longa-1"
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    _, _, r = rq(porta, "POST", "/criar", cab={**h, "Host": "agenda.exemplo.com", "CF-Connecting-IP": "203.0.113.1"}, raw=form)
    assert "Secure" in r.getheader("Set-Cookie")
    _, _, r = rq(porta, "POST", "/criar", cab={**h, "Host": "localhost:8080", "CF-Connecting-IP": "203.0.113.2"}, raw=form.replace("c%40", "d%40"))
    assert "Secure" not in r.getheader("Set-Cookie")


def test_entrada_malformada_vira_erro_do_cliente_e_nao_500(srv):
    porta, a = srv
    assert rq(porta, "GET", "/c/demo/agendar?servico=%C2%B2")[0] == 200  # '²'.isdigit() é True e int('²') quebrava
    c, _, _ = demo(a)
    k = n.criar_chave(a.bd, c["id"], "t", "escrita")["chave"]
    cab = {"Authorization": f"Bearer {k}"}
    assert rq(porta, "POST", "/api/v1/servicos", cab=cab, raw='{"nome":"x","duracao_min":1e400}')[0] == 422
    assert rq(porta, "POST", "/api/v1/servicos", cab=cab, corpo={"nome": "x", "duracao_min": "abc"})[0] == 422
    assert rq(porta, "PUT", "/api/v1/profissionais/1/disponibilidade", cab=cab, corpo={"janelas": [1, "a"]})[0] == 422


def test_json_ld_com_comentario_html_no_nome_nao_engole_o_resto_da_pagina(srv):
    porta, a = srv
    n.criar_clinica(a.bd, "<!--<script>x", "h@x.test", "senha-bem-longa-1", "clinica-html")
    pagina = rq(porta, "GET", "/c/clinica-html")[1]
    bloco = pagina.split('<script type="application/ld+json">')[1].split("</script>")[0]
    assert "<" not in bloco and "</main>" in pagina


# ---------------------------------------------------------------- dados do paciente e da clínica (B1, B3)

def test_cancelar_e_remarcar_por_codigo_nao_devolvem_nome_nem_telefone_do_paciente(srv):
    porta, a = srv
    c, sv, prof = demo(a)
    s1, s2 = horarios_demo(a, c, sv, prof, 2)
    ag = n.agendar(a.bd, c, sv, prof, s1["data"], s1["hora"], "Maria Secreta", "48911112222", consentimento=True)
    _, t, _ = rq(porta, "POST", f"/api/v1/consultas/{ag['codigo']}/remarcar", {"data": s2["data"], "hora": s2["hora"]})
    assert "48911112222" not in t and "Maria Secreta" not in t and json.loads(t)["hora"] == s2["hora"]
    _, t, _ = rq(porta, "POST", f"/api/v1/consultas/{ag['codigo']}/cancelar")
    assert "48911112222" not in t and json.loads(t)["status"] == "cancelado"


def test_email_de_login_nao_vira_contato_publico_da_clinica(srv):
    porta, a = srv
    n.criar_clinica(a.bd, "Clinica Privada", "login-secreto@privada.test", "senha-bem-longa-1", "privada")
    assert "login-secreto@privada.test" not in rq(porta, "GET", "/api/v1/clinicas/privada")[1]
    assert "login-secreto@privada.test" not in rq(porta, "GET", "/c/privada")[1]


# ---------------------------------------------------------------- cadastro aberto (M6) e custo (A1, M4, M5)

def test_clinica_nova_nasce_indexavel_e_o_operador_consegue_tirar_so_uma_do_indice(srv):
    """Decisão do dono ("indexa tudo"): nasce no sitemap e sem noindex; `delistar` é a válvula contra marca alheia e spam."""
    porta, a = srv
    n.criar_clinica(a.bd, "Hospital Famoso", "spam@x.test", "senha-bem-longa-1", "hospital-famoso")
    assert 'name="robots"' not in rq(porta, "GET", "/c/hospital-famoso")[1]
    assert "hospital-famoso" in rq(porta, "GET", "/sitemap.xml")[1]
    ap.listar_clinica(a.bd, "hospital-famoso", False)
    assert 'name="robots" content="noindex"' in rq(porta, "GET", "/c/hospital-famoso")[1]
    sitemap = rq(porta, "GET", "/sitemap.xml")[1]
    assert "hospital-famoso" not in sitemap and "/c/demo" in sitemap  # só a delistada saiu


def test_horarios_de_clinica_gigante_vem_cortados_e_janela_maior_que_14_dias_e_recusada(srv):
    porta, a = srv
    c = n.criar_clinica(a.bd, "Gigante", "g@g.test", "senha-bem-longa-1", "gigante")
    loc = n.salvar_local(a.bd, c["id"], {"nome": "L"})
    sv = n.salvar_servico(a.bd, c["id"], {"nome": "S", "duracao_min": 10})
    n.salvar_clinica(a.bd, a.bd.um("select * from clinicas where id=?", (c["id"],)), {"passo_min": 10, "antecedencia_min": 0})
    for i in range(30):
        p = n.salvar_profissional(a.bd, c["id"], {"nome": f"P{i}"})
        n.definir_disponibilidade(a.bd, c["id"], p, [{"dia": d, "inicio": "00:00", "fim": "23:59", "local_id": loc} for d in range(7)])
    hoje = n.agora_local("America/Sao_Paulo")[0]
    de, ate = hoje.isoformat(), (hoje + dt.timedelta(days=13)).isoformat()
    _, t, _ = rq(porta, "GET", f"/api/v1/clinicas/gigante/horarios?servico_id={sv}&de={de}&ate={ate}")
    r = json.loads(t)
    assert r["truncado"] is True and len(r["horarios"]) == n.LIMITES["linhas_horarios"] and len(t) < 100_000
    st, _, _ = rq(porta, "GET", f"/api/v1/clinicas/gigante/horarios?servico_id={sv}&de={de}&ate={(hoje + dt.timedelta(days=14)).isoformat()}")
    assert st == 422


def test_agendamento_anonimo_tem_teto_por_clinica_e_a_chave_da_clinica_nao_entra_na_conta(srv, monkeypatch):
    porta, a = srv
    monkeypatch.setitem(n.LIMITES, "anonimos_por_clinica_hora", 2)
    c, sv, prof = demo(a)
    slots = horarios_demo(a, c, sv, prof, 5)
    corpo = lambda i: {"servico_id": sv, "profissional_id": prof, "data": slots[i]["data"], "hora": slots[i]["hora"], "nome": "x",
                       "telefone": f"4899999{i:04d}", "consentimento": True}
    codigos = [rq(porta, "POST", "/api/v1/clinicas/demo/agendamentos", corpo(i))[0] for i in range(3)]
    assert codigos == [201, 201, 429]
    k = n.criar_chave(a.bd, c["id"], "t", "escrita")["chave"]
    assert rq(porta, "POST", "/api/v1/clinicas/demo/agendamentos", corpo(3), cab={"Authorization": f"Bearer {k}"})[0] == 201


def test_consulta_marcada_na_janela_entre_ler_conflitos_e_gravar_bloqueio_nao_fica_viva_dentro_do_bloqueio(bd, clinica):
    """Com os conflitos lidos FORA da transação, um agendar que entrasse nessa janela ficava confirmado dentro do bloqueio."""
    seg = proxima(1)
    original, estado = bd.escrita, {"feito": False}

    def escrita_com_intruso():
        if not estado["feito"]:  # roda um agendar exatamente antes da transação do bloqueio abrir
            estado["feito"] = True
            n.agendar(bd, clinica["row"], clinica["retorno"], clinica["ana"], seg, "10:00", "Intruso", "48977770000", consentimento=True)
        return original()

    bd.escrita = escrita_com_intruso
    try:
        b = n.bloquear(bd, clinica["row"], f"{seg}T08:00", f"{seg}T12:00", clinica["ana"], "x", cancelar_conflitos=True)
    finally:
        del bd.escrita
    assert [a for a in n.listar_agendamentos(bd, clinica["row"], seg) if a["status"] == "confirmado"] == []
    assert len(b["consultas_canceladas"]) == 1


# ---------------------------------------------------------------- migração do banco já em produção

def test_banco_criado_antes_da_coluna_listada_e_migrado_sem_perder_clinica(tmp_path):
    caminho = tmp_path / "agenda.db"
    con = sqlite3.connect(caminho)
    con.executescript("create table clinicas(id integer primary key, slug text unique not null, nome text not null, descricao text default '', "
                      "telefone text default '', email text default '', cidade text default '', tz text default 'America/Sao_Paulo', "
                      "passo_min integer default 30, antecedencia_min integer default 120, criado text);"
                      "insert into clinicas(slug,nome) values('antiga','Clínica Antiga');")
    con.commit()
    con.close()
    bd = n.Banco(tmp_path)
    r = bd.um("select nome, listada from clinicas where slug='antiga'")
    assert (r["nome"], r["listada"]) == ("Clínica Antiga", 1)  # clínica que já existia continua indexável
