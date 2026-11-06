"""Conta de dev: cadastro aberto, chave ad_, clientes dele (CRUD), suporte. O que NÃO pode acontecer: dev mexer em cliente de outro dev."""
import threading

import pytest

import app as ap
import devs as dv
import nucleo as n
import ops
from conftest import proxima
from test_http import req


@pytest.fixture
def srv(tmp_path):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    ap.semear_demo(a.bd)
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def _dev(bd, email="dev@x.test"):
    return dv.criar(bd, email, "senha-bem-longa", "Dev")


def _cliente(bd, dev, nome="Barbearia do Zé", slug=""):
    return dv.criar_clinica(bd, dev, nome, "barbearia", slug)["slug"]


def _marca(bd, slug):
    """Um agendamento no cliente, para provar o que o dev enxerga."""
    c = n.clinica_por_slug(bd, slug)
    loc = n.salvar_local(bd, c["id"], {"nome": "L"})
    prof = n.salvar_profissional(bd, c["id"], {"nome": "Rafa"})
    n.definir_disponibilidade(bd, c["id"], prof, [{"dia": d, "inicio": "09:00", "fim": "12:00", "local_id": loc} for d in range(7)])
    serv = n.salvar_servico(bd, c["id"], {"nome": "Corte", "duracao_min": 30})
    dia = proxima(3, 3)
    n.agendar(bd, c, serv, prof, dia, "09:00", "Maria Souza", "48999990000", consentimento=True)
    return dia


def test_cadastro_recusa_email_repetido_e_senha_curta_e_login_confere_a_senha(bd):
    _dev(bd)
    with pytest.raises(n.Erro) as e:
        _dev(bd)
    assert e.value.codigo == "email_em_uso"
    with pytest.raises(n.Erro) as e:
        dv.criar(bd, "outro@x.test", "curta")
    assert e.value.codigo == "senha_curta"
    assert dv.dev_da_sessao(bd, dv.entrar(bd, "DEV@x.test", "senha-bem-longa"))["email"] == "dev@x.test"
    for senha in ("errada-errada", ""):
        with pytest.raises(n.Erro):
            dv.entrar(bd, "dev@x.test", senha)


def test_conta_so_de_google_ou_github_nao_entra_com_senha_vazia(bd):
    dv.criar(bd, "so@oauth.test", "", google_sub="g1")
    for senha in ("", "qualquer-coisa-longa"):
        with pytest.raises(n.Erro):
            dv.entrar(bd, "so@oauth.test", senha)


def test_cadastro_pela_pagina_abre_o_painel_com_cookie_restrito_ao_caminho_dev(srv):
    porta, a = srv
    st, _, r = req(porta, "POST", "/dev/cadastro", form={"email": "novo@dev.test", "senha": "senha-bem-longa", "nome": "Novo"})
    cookie = r.getheader("Set-Cookie")
    assert st in (302, 303) and "dev_sessao=" in cookie and "Path=/dev" in cookie and "HttpOnly" in cookie
    st, html, _ = req(porta, "GET", "/dev", cab={"Cookie": cookie.split(";")[0]})
    assert st == 200 and "novo@dev.test" in html and "Nenhum cliente ainda" in html
    assert req(porta, "GET", "/dev")[0] in (302, 303)  # sem login volta para a entrada


def test_cadastro_aberto_tem_limite_por_endereco(srv):
    porta, _ = srv
    codigos = [req(porta, "POST", "/dev/cadastro", form={"email": f"d{i}@dev.test", "senha": "senha-bem-longa"})[0] for i in range(7)]
    assert codigos[:5] == [302] * 5 or all(c in (302, 303) for c in codigos[:5])
    assert codigos[-1] == 429


def test_chave_de_dev_lista_e_cria_clientes_e_chave_de_clinica_nao_entra_nas_rotas_de_dev(srv):
    porta, a = srv
    dev = _dev(a.bd)
    cab = {"Authorization": f"Bearer {dv.criar_chave(a.bd, dev['id'], 'agente')['chave']}"}
    st, r, _ = req(porta, "POST", "/api/v1/dev/clinicas", corpo={"nome": "Navalha Fina", "nicho": "barbearia"}, cab=cab)
    assert st == 201 and r["slug"] == "navalha-fina" and n.clinica_por_slug(a.bd, "navalha-fina")["dev_id"] == dev["id"]
    assert [c["slug"] for c in req(porta, "GET", "/api/v1/dev/clinicas", cab=cab)[1]["clinicas"]] == ["navalha-fina"]
    clinica_key = {"Authorization": f"Bearer {n.criar_chave(a.bd, n.clinica_por_slug(a.bd, 'demo')['id'], 't', 'escrita')['chave']}"}
    assert req(porta, "GET", "/api/v1/dev/clinicas", cab=clinica_key)[0] == 403
    assert req(porta, "GET", "/api/v1/dev/clinicas")[0] == 401


def test_chave_de_dev_revogada_deixa_de_valer(srv):
    porta, a = srv
    dev = _dev(a.bd)
    k = dv.criar_chave(a.bd, dev["id"], "x")
    cab = {"Authorization": f"Bearer {k['chave']}"}
    assert req(porta, "GET", "/api/v1/dev/clinicas", cab=cab)[0] == 200
    dv.revogar_chave(a.bd, dev["id"], dv.listar_chaves(a.bd, dev["id"])[0]["id"])
    assert req(porta, "GET", "/api/v1/dev/clinicas", cab=cab)[0] == 401


def test_dev_ve_nome_e_telefone_dos_pacientes_so_dos_proprios_clientes(srv):
    porta, a = srv
    d1, d2 = _dev(a.bd, "um@x.test"), _dev(a.bd, "dois@x.test")
    meu, alheio = _cliente(a.bd, d1, "Meu"), _cliente(a.bd, d2, "Alheio")
    dia = _marca(a.bd, meu)
    _marca(a.bd, alheio)
    cab = {"Authorization": f"Bearer {dv.criar_chave(a.bd, d1['id'], 'k')['chave']}"}
    st, r, _ = req(porta, "GET", f"/api/v1/agendamentos?clinica={meu}&de={dia}", cab=cab)
    assert st == 200 and r["agendamentos"][0]["paciente_nome"] == "Maria Souza" and r["agendamentos"][0]["paciente_telefone"] == "48999990000"
    assert req(porta, "GET", f"/api/v1/agendamentos?clinica={alheio}&de={dia}", cab=cab)[0] == 403
    assert req(porta, "GET", f"/api/v1/agendamentos?clinica=demo&de={dia}", cab=cab)[0] == 403  # nem a demonstração: não é cliente dele
    assert req(porta, "GET", f"/api/v1/agendamentos?de={dia}", cab=cab)[0] in (403, 404)  # sem dizer qual cliente, não adivinha
    assert req(porta, "POST", f"/api/v1/exportar?clinica={alheio}", cab=cab)[0] in (403, 404, 405)


def test_exportar_de_cliente_alheio_pela_api_e_pelo_painel_e_recusado(srv):
    porta, a = srv
    d1, d2 = _dev(a.bd, "um@x.test"), _dev(a.bd, "dois@x.test")
    meu, alheio = _cliente(a.bd, d1, "Meu"), _cliente(a.bd, d2, "Alheio")
    cab = {"Authorization": f"Bearer {dv.criar_chave(a.bd, d1['id'], 'k')['chave']}"}
    assert req(porta, "GET", f"/api/v1/exportar?clinica={meu}", cab=cab)[1]["clinica"]["slug"] == meu
    assert req(porta, "GET", f"/api/v1/exportar?clinica={alheio}", cab=cab)[0] == 403
    ck = {"Cookie": "dev_sessao=" + dv.sessao_de(a.bd, d1["id"])}
    assert req(porta, "GET", f"/dev/exportar/{meu}", cab=ck)[0] == 200
    assert req(porta, "GET", f"/dev/exportar/{alheio}", cab=ck)[0] == 403


def test_apagar_cliente_exige_confirmacao_e_so_apaga_o_proprio(srv):
    porta, a = srv
    d1, d2 = _dev(a.bd, "um@x.test"), _dev(a.bd, "dois@x.test")
    meu, alheio = _cliente(a.bd, d1, "Meu"), _cliente(a.bd, d2, "Alheio")
    cab = {"Authorization": f"Bearer {dv.criar_chave(a.bd, d1['id'], 'k')['chave']}"}
    assert req(porta, "DELETE", f"/api/v1/dev/clinicas/{meu}?confirmar=outro", cab=cab)[0] == 422
    assert req(porta, "DELETE", f"/api/v1/dev/clinicas/{alheio}?confirmar={alheio}", cab=cab)[0] == 403
    assert a.bd.um("select 1 from clinicas where slug=?", (alheio,)) is not None
    assert req(porta, "DELETE", f"/api/v1/dev/clinicas/{meu}?confirmar={meu}", cab=cab)[0] == 200
    assert a.bd.um("select 1 from clinicas where slug=?", (meu,)) is None


def test_limite_de_clientes_por_conta_de_dev(bd, monkeypatch):
    monkeypatch.setitem(n.LIMITES, "clinicas_por_dev", 2)
    dev = _dev(bd)
    _cliente(bd, dev, "Cliente Um")
    _cliente(bd, dev, "Cliente Dois")
    with pytest.raises(n.Erro) as e:
        _cliente(bd, dev, "Cliente Tres")
    assert e.value.codigo == "limite"


def test_dev_entrega_o_login_ao_cliente_e_as_sessoes_antigas_caem(bd):
    dev = _dev(bd)
    slug = _cliente(bd, dev)
    antiga = dv.sessao_suporte(bd, dev, slug)
    assert n.clinica_da_sessao(bd, antiga)["slug"] == slug
    dv.definir_acesso(bd, dev, slug, "cliente@ze.test", "senha-do-cliente-ok")
    assert n.clinica_da_sessao(bd, antiga) is None
    assert n.clinica_da_sessao(bd, n.entrar(bd, "cliente@ze.test", "senha-do-cliente-ok"))["slug"] == slug
    outro = _cliente(bd, dev, "Outro")
    with pytest.raises(n.Erro) as e:
        dv.definir_acesso(bd, dev, outro, "cliente@ze.test", "senha-do-cliente-ok")
    assert e.value.codigo == "email_em_uso"


def test_suporte_abre_o_painel_do_cliente_so_com_csrf_e_so_do_proprio_cliente(srv):
    porta, a = srv
    d1, d2 = _dev(a.bd, "um@x.test"), _dev(a.bd, "dois@x.test")
    meu, alheio = _cliente(a.bd, d1, "Meu Cliente"), _cliente(a.bd, d2, "Cliente Alheio")
    tok = dv.sessao_de(a.bd, d1["id"])
    cab = {"Cookie": f"dev_sessao={tok}"}
    assert req(porta, "POST", "/dev/acao", form={"acao": "suporte", "slug": meu}, cab=cab)[0] == 403  # sem csrf
    csrf = n.csrf_de(tok)
    st, _, r = req(porta, "POST", "/dev/acao", form={"acao": "suporte", "slug": meu, "csrf": csrf}, cab=cab)
    cookie = r.getheader("Set-Cookie").split(";")[0]
    assert st in (302, 303) and cookie.startswith("sessao=")
    assert "Meu Cliente" in req(porta, "GET", "/painel", cab={"Cookie": cookie})[1]
    st, _, r2 = req(porta, "POST", "/dev/acao", form={"acao": "suporte", "slug": alheio, "csrf": csrf}, cab=cab)
    assert r2.getheader("Set-Cookie") is None and "erro=" in r2.getheader("Location")


def test_painel_do_dev_escapa_nome_de_cliente_e_nunca_mostra_senha_nem_hash(srv):
    porta, a = srv
    dev = _dev(a.bd)
    dv.criar_clinica(a.bd, dev, "<script>alert(1)</script>", "clinica", "xss-teste")
    tok = dv.sessao_de(a.bd, dev["id"])
    html = req(porta, "GET", "/dev", cab={"Cookie": f"dev_sessao={tok}"})[1]
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "scrypt$" not in html and "senha-bem-longa" not in html


def test_mcp_so_mostra_ferramentas_de_dev_e_o_parametro_clinica_para_chave_de_dev(srv):
    porta, a = srv
    dev = _dev(a.bd)
    chaves = {"dev": dv.criar_chave(a.bd, dev["id"], "k")["chave"], "clinica": n.criar_chave(a.bd, n.clinica_por_slug(a.bd, "demo")["id"], "k", "escrita")["chave"]}
    def tools(k):
        r = req(porta, "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"Authorization": f"Bearer {k}"})[1]["result"]["tools"]
        return {t["name"]: t for t in r}
    td, tc = tools(chaves["dev"]), tools(chaves["clinica"])
    assert {"dev_clinicas_listar", "dev_clinica_criar", "dev_clinica_apagar", "dev_clinica_acesso"} <= set(td)
    assert not [x for x in tc if x.startswith("dev_")]
    assert "clinica" in td["listar_agendamentos"]["inputSchema"]["properties"] and "clinica" not in tc["listar_agendamentos"]["inputSchema"]["properties"]


def test_openapi_documenta_as_operacoes_de_dev_e_o_parametro_clinica(srv):
    porta, _ = srv
    paths = req(porta, "GET", "/openapi.json")[1]["paths"]
    assert "/api/v1/dev/clinicas" in paths and "/api/v1/dev/clinicas/{clinica}/acesso" in paths
    params = [p["name"] for p in paths["/api/v1/agendamentos"]["get"]["parameters"]]
    assert "clinica" in params


def test_privacidade_avisa_o_paciente_que_o_dev_de_suporte_ve_nome_e_telefone(srv):
    porta, _ = srv
    assert "conta de dev" in req(porta, "GET", "/privacidade")[1]


def test_todas_as_operacoes_de_dev_exigem_nivel_dev():
    assert {o["nome"] for o in ops.OPS.values() if o["por"] == "dev"} == {o["nome"] for o in ops.OPS.values() if o["nivel"] == "dev"}
