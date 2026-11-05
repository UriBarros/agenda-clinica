"""Fluxos pela rede (servidor real em porta livre): REST, MCP, painel, site público."""
import http.client
import json
import re
import threading
import urllib.parse

import pytest

import app as ap
import nucleo as n
import ops
from conftest import proxima


@pytest.fixture
def srv(tmp_path):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    ap.semear_demo(a.bd)
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def req(porta, metodo, caminho, corpo=None, cab=None, form=None):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    h = dict(cab or {})
    dados = None
    if corpo is not None:
        dados, h["Content-Type"] = json.dumps(corpo), "application/json"
    if form is not None:
        dados, h["Content-Type"] = urllib.parse.urlencode(form), "application/x-www-form-urlencoded"
    c.request(metodo, caminho, dados, h)
    r = c.getresponse()
    txt = r.read().decode()
    c.close()
    try:
        return r.status, json.loads(txt), r
    except ValueError:
        return r.status, txt, r


def dados_demo(a):
    c = n.clinica_por_slug(a.bd, "demo")
    info = n.info_publica(a.bd, c)
    return c, info["servicos"][1]["id"], info["profissionais"][1]["id"]  # Retorno 30 min, Bia (seg a sex, 08-12)


def chave(a, escopo="escrita", slug="demo"):
    return n.criar_chave(a.bd, n.clinica_por_slug(a.bd, slug)["id"], "t", escopo)["chave"]


def test_fluxo_rest_completo_agendar_consultar_remarcar_cancelar_pelo_codigo(srv):
    porta, a = srv
    _, serv, prof = dados_demo(a)
    seg = proxima(1, 3)
    st, h, _ = req(porta, "GET", f"/api/v1/clinicas/demo/horarios?servico_id={serv}&de={seg}&profissional_id={prof}")
    assert st == 200 and h["horarios"][0]["hora"] == "08:00"
    corpo = {"servico_id": serv, "profissional_id": prof, "data": seg, "hora": "08:00", "nome": "Maria", "telefone": "48999990000", "consentimento": True}
    st, ag, _ = req(porta, "POST", "/api/v1/clinicas/demo/agendamentos", corpo)
    assert st == 201 and ag["status"] == "confirmado" and ag["codigo"]
    assert req(porta, "POST", "/api/v1/clinicas/demo/agendamentos", corpo)[0] == 409  # mesmo horário de novo
    st, ver, _ = req(porta, "GET", f"/api/v1/consultas/{ag['codigo']}")
    assert st == 200 and "paciente_nome" not in ver  # o código não entrega o cadastro inteiro
    st, rem, _ = req(porta, "POST", f"/api/v1/consultas/{ag['codigo']}/remarcar", {"data": seg, "hora": "08:30"})
    assert st == 200 and rem["hora"] == "08:30"
    st, can, _ = req(porta, "POST", f"/api/v1/consultas/{ag['codigo']}/cancelar")
    assert st == 200 and can["status"] == "cancelado" and can["cancelado_por"] == "paciente"


def test_rota_com_chave_exige_chave_e_escopo_e_da_a_clinica_certa(srv):
    porta, a = srv
    assert req(porta, "GET", "/api/v1/agendamentos?de=2026-11-10")[0] == 401
    leitura, escrita = chave(a, "leitura"), chave(a, "escrita")
    auth = lambda k: {"Authorization": f"Bearer {k}"}
    assert req(porta, "GET", "/api/v1/agendamentos?de=2026-11-10", cab=auth(leitura))[0] == 200
    st, r, _ = req(porta, "POST", "/api/v1/bloqueios", {"inicio": "2030-01-01T08:00", "fim": "2030-01-01T12:00"}, auth(leitura))
    assert st == 403 and r["erro"]["codigo"] == "escopo_insuficiente"
    assert req(porta, "POST", "/api/v1/bloqueios", {"inicio": "2030-01-01T08:00", "fim": "2030-01-01T12:00"}, auth(escrita))[0] == 201
    assert req(porta, "GET", "/api/v1/agendamentos?de=2026-11-10", cab=auth("ac_falsa_falsa"))[0] == 401
    n.criar_clinica(a.bd, "Outra", "o@o.test", "senha-bem-longa", "outra")
    st, r, _ = req(porta, "GET", "/api/v1/clinicas/outra", cab=auth(escrita))  # chave da demo olhando a outra
    assert st == 403 and r["erro"]["codigo"] == "outra_clinica"


def test_chave_de_uma_clinica_nao_enxerga_agendamento_de_outra(srv):
    porta, a = srv
    c, serv, prof = dados_demo(a)
    ag = n.agendar(a.bd, c, serv, prof, proxima(1, 3), "08:00", "Maria", "48999990000", consentimento=True)
    n.criar_clinica(a.bd, "Outra", "o@o.test", "senha-bem-longa", "outra")
    k = chave(a, "escrita", "outra")
    st, r, _ = req(porta, "GET", f"/api/v1/agendamentos/{ag['id']}", cab={"Authorization": f"Bearer {k}"})
    assert st == 404
    st, _, _ = req(porta, "POST", f"/api/v1/agendamentos/{ag['id']}/cancelar", cab={"Authorization": f"Bearer {k}"})
    assert st == 404


def test_mcp_lista_so_ferramentas_publicas_sem_chave_e_todas_com_chave(srv):
    porta, a = srv
    rpc = lambda m, p=None, cab=None, i=1: req(porta, "POST", "/mcp", {"jsonrpc": "2.0", "id": i, "method": m, "params": p or {}}, cab)
    st, init, _ = rpc("initialize", {"protocolVersion": "2025-06-18"})
    assert st == 200 and init["result"]["serverInfo"]["name"] == "agenda-clinica"
    pub = {t["name"] for t in rpc("tools/list")[1]["result"]["tools"]}
    com = {t["name"] for t in rpc("tools/list", cab={"Authorization": f"Bearer {chave(a)}"})[1]["result"]["tools"]}
    assert pub == {o["nome"] for o in ops.OPS.values() if o["nivel"] == "publico"} and com == set(ops.OPS)
    assert req(porta, "POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202


def test_mcp_agendar_e_erro_de_regra_volta_como_isError_com_codigo(srv):
    porta, a = srv
    _, serv, prof = dados_demo(a)
    seg = proxima(1, 3)
    chamar = lambda args: req(porta, "POST", "/mcp", {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "agendar", "arguments": args}})[1]["result"]
    args = {"clinica": "demo", "servico_id": serv, "profissional_id": prof, "data": seg, "hora": "09:00", "nome": "Joao", "telefone": "48988887777", "consentimento": True}
    ok = chamar(args)
    assert not ok.get("isError") and ok["structuredContent"]["origem"] == "mcp"
    de_novo = chamar({**args, "telefone": "48977776666"})
    assert de_novo["isError"] and json.loads(de_novo["content"][0]["text"])["erro"]["codigo"] == "horario_indisponivel"
    sem = chamar({k: v for k, v in args.items() if k != "consentimento"})
    assert sem["isError"] and "consentimento" in sem["content"][0]["text"]


def test_mcp_e_rest_e_openapi_cobrem_exatamente_as_mesmas_operacoes(srv):
    porta, a = srv
    spec = req(porta, "GET", "/openapi.json")[1]
    ids = {m["operationId"] for p in spec["paths"].values() for m in p.values()}
    assert ids == set(ops.OPS)
    for o in ops.OPS.values():  # toda operação é alcançável como rota REST
        caminho = re.sub(r"\{(\w+)\}", "x", o["caminho"])
        assert ops.rota(o["metodo"], caminho)[0]["nome"] == o["nome"]
    llms = req(porta, "GET", "/llms.txt")[1]
    assert all(nome in llms for nome in ops.OPS)


def test_painel_exige_login_csrf_e_nao_redireciona_para_fora(srv):
    porta, a = srv
    assert req(porta, "GET", "/painel")[2].getheader("Location") == "/entrar"
    st, _, r = req(porta, "POST", "/criar", form={"nome": "Minha Clínica", "email": "dono@minha.test", "senha": "uma-senha-longa-1"})
    assert st == 303
    ck = r.getheader("Set-Cookie").split(";")[0]
    assert "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Lax" in r.getheader("Set-Cookie")
    cab = {"Cookie": ck}
    st, pagina, _ = req(porta, "GET", "/painel/equipe", cab=cab)
    assert st == 200 and "Minha Clínica" in pagina
    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', pagina)[1]
    sem = req(porta, "POST", "/painel/acao", form={"acao": "salvar_local", "nome": "X"}, cab=cab)
    assert sem[0] == 403  # sem token CSRF a ação não roda
    st, _, r = req(porta, "POST", "/painel/acao", form={"acao": "salvar_local", "nome": "Sede", "csrf": csrf, "volta": "https://evil.test/x"}, cab=cab)
    assert st == 303 and r.getheader("Location").startswith("/painel")
    assert n.info_publica(a.bd, n.clinica_por_slug(a.bd, "minha-clinica"))["locais"][0]["nome"] == "Sede"


def test_painel_fluxo_de_ponta_a_ponta_equipe_horario_agendar_bloquear_cancelar(srv):
    porta, a = srv
    _, _, r = req(porta, "POST", "/criar", form={"nome": "Clínica Fluxo", "email": "f@fluxo.test", "senha": "uma-senha-longa-1"})
    cab = {"Cookie": r.getheader("Set-Cookie").split(";")[0]}
    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', req(porta, "GET", "/painel", cab=cab)[1])[1]
    acao = lambda **f: req(porta, "POST", "/painel/acao", form={"csrf": csrf, **f}, cab=cab)
    acao(acao="salvar_local", nome="Centro", endereco="Rua A")
    acao(acao="salvar_profissional", nome="Dra. Teste", especialidade="Clínica")
    acao(acao="salvar_servico", nome="Consulta", duracao_min="30", preco="150,50")
    c = n.clinica_por_slug(a.bd, "clinica-fluxo")
    info = n.info_publica(a.bd, c)
    assert info["servicos"][0]["preco_centavos"] == 15050
    pid, lid = info["profissionais"][0]["id"], info["locais"][0]["id"]
    seg = proxima(1, 3)
    acao(acao="disponibilidade", profissional_id=str(pid), **{"i1_0": "09:00", "f1_0": "11:00", "l1_0": str(lid)})
    # site público: página, agendar sem JS, confirmação
    assert "MedicalClinic" in req(porta, "GET", "/c/clinica-fluxo")[1]
    pagina = req(porta, "GET", f"/c/clinica-fluxo/agendar?servico={info['servicos'][0]['id']}")[1]
    assert f"data={seg}" in pagina.replace("&amp;", "&") and "09:00" in pagina
    st, conf, _ = req(porta, "POST", "/c/clinica-fluxo/agendar", form={"servico": info["servicos"][0]["id"], "profissional": pid, "data": seg,
                                                                      "hora": "09:00", "nome": "Maria", "telefone": "48999990000", "consentimento": "1"})
    assert st == 201 and "Agendado!" in conf
    codigo = re.search(r"/m/([\w-]+)", conf)[1]
    assert "confirmada" in req(porta, "GET", f"/m/{codigo}")[1]
    dia = req(porta, "GET", f"/painel?data={seg}", cab=cab)[1]
    assert "Maria" in dia
    ag_id = n.listar_agendamentos(a.bd, c, seg)[0]["id"]
    acao(acao="bloquear", inicio=f"{seg}T08:00", fim=f"{seg}T12:00", profissional_id=str(pid))  # recusa: há consulta
    assert n.listar_bloqueios(a.bd, c) == []
    acao(acao="bloquear", inicio=f"{seg}T08:00", fim=f"{seg}T12:00", profissional_id=str(pid), cancelar_conflitos="1")
    assert n.agendamento_da_clinica(a.bd, c, ag_id)["status"] == "cancelado" and len(n.listar_bloqueios(a.bd, c)) == 1


def test_texto_do_paciente_com_html_sai_escapado_no_painel(srv):
    porta, a = srv
    c, serv, prof = dados_demo(a)
    n.agendar(a.bd, c, serv, prof, proxima(1, 3), "08:00", "<script>alert(1)</script>", "48999990000", consentimento=True)
    n.criar_chave(a.bd, c["id"], "t", "leitura")  # a senha do demo é aleatória: entra por sessão direta
    u = a.bd.um("select id from usuarios where clinica_id=?", (c["id"],))["id"]
    import secrets as s
    tok = s.token_urlsafe(16)
    with a.bd.escrita() as con:
        con.execute("insert into sessoes values(?,?,?)", (n._sha(tok), u, "2099-01-01T00:00:00Z"))
    pagina = req(porta, "GET", f"/painel?data={proxima(1, 3)}", cab={"Cookie": f"sessao={tok}"})[1]
    assert "<script>alert(1)" not in pagina and "&lt;script&gt;" in pagina


def test_login_tem_limite_de_tentativas_por_ip(srv):
    porta, _ = srv
    codigos = [req(porta, "POST", "/entrar", form={"email": "x@x.test", "senha": "errada-errada"})[0] for _ in range(12)]
    assert 429 in codigos and codigos[0] == 401


def test_corpo_gigante_e_recusado_sem_derrubar_o_servidor(srv):
    porta, _ = srv
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    c.request("POST", "/api/v1/clinicas/demo/agendamentos", "x" * 70000, {"Content-Type": "application/json"})
    assert c.getresponse().status == 413
    assert req(porta, "GET", "/health")[0] == 200


def test_headers_de_seguranca_e_site_indexavel_mas_paciente_nao(srv):
    porta, a = srv
    _, home, r = req(porta, "GET", "/")
    assert "script-src 'none'" in r.getheader("Content-Security-Policy") and r.getheader("X-Content-Type-Options") == "nosniff"
    assert 'name="robots"' not in req(porta, "GET", "/c/demo")[1]  # a clínica é indexável
    assert "/c/demo" in req(porta, "GET", "/sitemap.xml")[1]
    c, serv, prof = dados_demo(a)
    ag = n.agendar(a.bd, c, serv, prof, proxima(1, 3), "08:00", "Maria", "48999990000", consentimento=True)
    assert 'content="noindex"' in req(porta, "GET", f"/m/{ag['codigo']}")[1]


def test_backup_diario_gera_copia_legivel_e_poda_as_antigas(tmp_path, bd, clinica):
    pasta = tmp_path / "bk"
    pasta.mkdir()
    for i in range(10):
        (pasta / f"agenda-2020010{i % 10}x{i}.db").write_bytes(b"")
    novo = ap.backup_diario(bd, pasta)
    copia = n.Banco(tmp_path / "restaurado")
    novo.replace(copia.caminho)
    assert n.clinica_por_slug(copia, "aurora")["nome"] == "Clínica Aurora"
    assert len(list(pasta.glob("agenda-*.db"))) <= 7


def test_metricas_do_lancamento_ignoram_a_demo_e_separam_web_api_e_mcp(srv):
    porta, a = srv
    c, serv, prof = dados_demo(a)
    n.agendar(a.bd, c, serv, prof, proxima(1, 3), "08:00", "Demo", "48999990000", consentimento=True)  # demo não conta
    real = n.criar_clinica(a.bd, "Real", "r@real.test", "senha-bem-longa", "real")
    cid = real["id"]
    loc, pr = n.salvar_local(a.bd, cid, {"nome": "L"}), n.salvar_profissional(a.bd, cid, {"nome": "P"})
    sv = n.salvar_servico(a.bd, cid, {"nome": "S", "duracao_min": 30})
    n.definir_disponibilidade(a.bd, cid, pr, [{"dia": 1, "inicio": "09:00", "fim": "12:00", "local_id": loc}])
    row = n.clinica_por_slug(a.bd, "real")
    n.agendar(a.bd, row, sv, pr, proxima(1, 3), "09:00", "Maria", "48999990001", origem="mcp", consentimento=True)
    n.agendar(a.bd, row, sv, pr, proxima(1, 3), "09:30", "Joao", "48999990002", origem="web", consentimento=True)
    assert ap.metricas(a.bd) == {"clinicas": 1, "clinicas_com_agenda_montada": 1, "agendamentos_confirmados": 2,
                                 "agendamentos_por_origem": {"mcp": 1, "web": 1}, "chaves_de_api_usadas": 0}


def test_agendar_base_e_indexavel_mas_variante_com_parametro_e_pagina_do_paciente_ficam_noindex(srv):
    """Decisão do dono ("indexa tudo"): a /agendar base entra no índice e no sitemap; combinações infinitas de URL e dado pessoal, não."""
    porta, a = srv
    assert 'name="robots"' not in req(porta, "GET", "/c/demo/agendar")[1]
    assert "/c/demo/agendar" in req(porta, "GET", "/sitemap.xml")[1]
    c, serv, prof = dados_demo(a)
    assert 'content="noindex"' in req(porta, "GET", f"/c/demo/agendar?servico={serv}")[1]
    ag = n.agendar(a.bd, c, serv, prof, proxima(1, 3), "08:00", "Maria", "48999990000", consentimento=True)
    assert 'content="noindex"' in req(porta, "GET", f"/m/{ag['codigo']}")[1]


# ---------------------------------------------------------------- fotos de fundo (Unsplash/Pexels servidas do nosso domínio)

def test_foto_de_fundo_sai_do_nosso_dominio_como_jpeg_com_cache(srv):
    porta, _ = srv
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    c.request("GET", "/static/fundos/psicologia.jpg")
    r = c.getresponse()
    corpo = r.read()
    c.close()
    assert r.status == 200 and r.getheader("Content-Type") == "image/jpeg" and "max-age" in r.getheader("Cache-Control")
    assert corpo[:3] == b"\xff\xd8\xff" and len(corpo) > 20_000  # é JPEG de verdade, não página de erro


@pytest.mark.parametrize("caminho", ["/static/fundos/../app.py", "/static/fundos/..%2fapp.py", "/static/fundos/inexistente.jpg",
                                     "/static/fundos/psicologia.png", "/static/fundos/creditos.json", "/static/fundos/"])
def test_rota_de_foto_so_serve_o_pool_e_nunca_arquivo_pelo_caminho_da_url(srv, caminho):
    porta, _ = srv
    st, corpo, _ = req(porta, "GET", caminho)
    assert st == 404 and "import " not in str(corpo)


def test_todo_arquivo_do_pool_existe_e_tem_credito_e_todo_credito_tem_arquivo():
    import paginas as pg
    arquivos = {p.stem for p in pg.FUNDOS_DIR.glob("*.jpg")}
    assert arquivos == set(pg.POOL) == set(pg.CREDITOS), "foto sem crédito (ou crédito sem foto) vira foto sem autoria na página"
    for c in pg.CREDITOS.values():
        assert c["fonte"] in ("Unsplash", "Pexels") and c["fotografo"] and c["pagina"].startswith("https://") and c["alt"]


def test_cada_clinica_ganha_a_mesma_foto_sempre_e_a_pagina_mostra_o_credito(srv):
    import paginas as pg
    porta, _ = srv
    assert pg.fundo_de("demo") == pg.fundo_de("demo") and pg.fundo_de("demo") in pg.POOL
    for caminho in ("/", "/c/demo", "/c/demo/agendar", "/entrar", "/docs", "/privacidade", "/creditos"):
        st, html, _ = req(porta, "GET", caminho)
        assert st == 200 and "/static/fundos/" in html and 'href="/creditos"' in html, caminho
    _, h1, _ = req(porta, "GET", "/c/demo")
    _, h2, _ = req(porta, "GET", "/c/demo")
    assert re.search(r"/static/fundos/([a-z-]+)\.jpg", h1).group(1) == re.search(r"/static/fundos/([a-z-]+)\.jpg", h2).group(1) == pg.fundo_de("demo")


def test_pagina_de_creditos_lista_todas_as_fotos_com_link_do_autor(srv):
    import paginas as pg
    porta, _ = srv
    _, html, _ = req(porta, "GET", "/creditos")
    for c in pg.CREDITOS.values():
        assert c["fotografo"] in html and c["pagina"] in html


def test_painel_continua_limpo_sem_foto_e_a_csp_continua_sem_script(srv):
    porta, a = srv
    _, html, r = req(porta, "GET", "/entrar")
    assert "script-src 'none'" in r.getheader("Content-Security-Policy") and "<script" not in html.replace('type="application/ld+json"', "")
    c = n.clinica_por_slug(a.bd, "demo")
    import paginas as pg
    assert "/static/fundos/" not in pg.painel(c, "tok", __import__("datetime").date.today(), [], [], [])  # tela de trabalho: sem foto
