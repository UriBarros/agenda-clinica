"""O dev personaliza o cliente (cor e rótulos). A regra é número, não gosto: contraste 4,5:1, sem HTML, só rótulo que existe."""
import json
import threading

import pytest

import app as ap
import devs as dv
import nichos as nx
import nucleo as n
from test_http import req


@pytest.fixture
def srv(tmp_path):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def _dev_e_chave(bd, email="dev@x.test"):
    d = dv.criar(bd, email, "senha-bem-longa")
    return d, {"Authorization": f"Bearer {dv.criar_chave(bd, d['id'], 'k')['chave']}"}


@pytest.mark.parametrize("cor", ["#ffff00", "#ffffff", "#aaaaaa"])
def test_cor_clara_que_apaga_o_texto_branco_do_botao_e_recusada(cor):
    with pytest.raises(ValueError, match="contraste"):
        nx.validar_personalizacao(cor, None)


@pytest.mark.parametrize("cor", ["vermelho", "#12", "#12345g", 12, "#0f766e;}</style><script>"])
def test_cor_que_nao_e_hexadecimal_e_recusada(cor):
    with pytest.raises(ValueError):
        nx.validar_personalizacao(cor, None)


@pytest.mark.parametrize("rotulos", [{"agendar": "<b>x</b>"}, {"agendar": 'a"b'}, {"agendar": "a" * 81}, {"pool": "x"}, {"ld": "Hack"}, {"nome": "x"}, {"inexistente": "x"}, ["agendar"]])
def test_rotulo_com_html_aspas_ou_de_chave_que_nao_e_editavel_e_recusado(rotulos):
    with pytest.raises(ValueError):
        nx.validar_personalizacao(None, rotulos)


def test_cor_padrao_da_casa_passa_no_contraste_e_vazio_limpa():
    assert nx.contraste_com_branco("#0f766e") >= 4.5 and nx.validar_personalizacao("", {}) == {}


def test_dev_personaliza_o_cliente_e_a_pagina_publica_muda_so_dele(srv):
    porta, a = srv
    d, cab = _dev_e_chave(a.bd)
    for nome in ("Cliente Um", "Cliente Dois"):
        dv.criar_clinica(a.bd, d, nome, "barbearia")
    st, r, _ = req(porta, "POST", "/api/v1/dev/clinicas/cliente-um/personalizar", corpo={"cor": "#7c2d12", "rotulos": {"agendar": "Marcar horário", "profs": "Nossos barbeiros"}}, cab=cab)
    assert st == 200 and r["personalizar"]["cor"] == "#7c2d12"
    um, dois = req(porta, "GET", "/c/cliente-um")[1], req(porta, "GET", "/c/cliente-dois")[1]
    assert "Marcar horário" in um and "Nossos barbeiros" in um and "--c:#7c2d12" in um and "prefers-color-scheme:light" in um
    assert "Marcar horário" not in dois and "--c:#7c2d12" not in dois and "Agendar horário" in dois


def test_dev_nao_personaliza_cliente_de_outro_dev(srv):
    porta, a = srv
    d1, cab = _dev_e_chave(a.bd, "um@x.test")
    d2 = dv.criar(a.bd, "dois@x.test", "senha-bem-longa")
    dv.criar_clinica(a.bd, d2, "Cliente Alheio", "clinica")
    assert req(porta, "POST", "/api/v1/dev/clinicas/cliente-alheio/personalizar", corpo={"cor": "#7c2d12"}, cab=cab)[0] == 403
    assert a.bd.um("select personalizar from clinicas where slug='cliente-alheio'")["personalizar"] in ("", None)
    assert d1


def test_valor_ruim_gravado_direto_no_banco_nao_vira_css_nem_html(srv):
    porta, a = srv
    d, _ = _dev_e_chave(a.bd)
    dv.criar_clinica(a.bd, d, "Cliente Sujo", "clinica")
    sujo = {"cor": "red;}</style><script>alert(1)</script>", "rotulos": {"agendar": "<img src=x onerror=alert(1)>", "profs": "Equipe & Cia"}}
    with a.bd.escrita() as con:
        con.execute("update clinicas set personalizar=? where slug='cliente-sujo'", (json.dumps(sujo),))
    html = req(porta, "GET", "/c/cliente-sujo")[1]
    assert "<script>alert(1)" not in html and "<img src=x" not in html and "--c:red" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html and "Equipe &amp; Cia" in html  # o que passou da validação ainda sai escapado


def test_personalizacao_chega_nas_paginas_do_cliente_final_e_limpar_volta_ao_padrao(srv):
    porta, a = srv
    d, cab = _dev_e_chave(a.bd)
    dv.criar_clinica(a.bd, d, "Cliente Final", "clinica")
    dv.personalizar(a.bd, d, "cliente-final", "#7c2d12", {"sua": "Sua visita", "cancelar": "Desmarcar"})
    c = n.clinica_por_slug(a.bd, "cliente-final")
    serv = n.salvar_servico(a.bd, c["id"], {"nome": "Visita", "duracao_min": 30})
    loc = n.salvar_local(a.bd, c["id"], {"nome": "L"})
    prof = n.salvar_profissional(a.bd, c["id"], {"nome": "P"})
    n.definir_disponibilidade(a.bd, c["id"], prof, [{"dia": d_, "inicio": "09:00", "fim": "12:00", "local_id": loc} for d_ in range(7)])
    from conftest import proxima
    ag = n.agendar(a.bd, n.clinica_por_slug(a.bd, "cliente-final"), serv, prof, proxima(3, 3), "09:00", "Ana", "48999990000", consentimento=True)
    pagina = req(porta, "GET", f"/m/{ag['codigo']}")[1]
    assert "Sua visita" in pagina and "Desmarcar" in pagina and "--c:#7c2d12" in pagina
    assert req(porta, "POST", "/api/v1/dev/clinicas/cliente-final/personalizar", corpo={"cor": "", "rotulos": {}}, cab=cab)[1]["personalizar"] == {}
    assert "Sua consulta" in req(porta, "GET", f"/m/{ag['codigo']}")[1]


def test_painel_do_dev_edita_cor_e_dois_rotulos_sem_apagar_os_outros_que_a_api_definiu(srv):
    porta, a = srv
    d, _ = _dev_e_chave(a.bd)
    dv.criar_clinica(a.bd, d, "Cliente Painel", "clinica")
    dv.personalizar(a.bd, d, "cliente-painel", None, {"cancelar": "Desmarcar", "agendar": "Antigo"})
    tok = dv.sessao_de(a.bd, d["id"])
    st, _, r = req(porta, "POST", "/dev/acao", form={"acao": "personalizar", "slug": "cliente-painel", "cor": "#7c2d12", "agendar": "Marcar visita", "profs": "", "csrf": n.csrf_de(tok)},
                   cab={"Cookie": f"dev_sessao={tok}"})
    assert st in (302, 303) and "erro=" not in r.getheader("Location")
    assert nx.personalizacao(n.clinica_por_slug(a.bd, "cliente-painel")) == {"cor": "#7c2d12", "rotulos": {"cancelar": "Desmarcar", "agendar": "Marcar visita"}}
    st, _, r = req(porta, "POST", "/dev/acao", form={"acao": "personalizar", "slug": "cliente-painel", "cor": "#ffff00", "csrf": n.csrf_de(tok)}, cab={"Cookie": f"dev_sessao={tok}"})
    assert "erro=" in r.getheader("Location")  # cor clara demais: recusada e a anterior continua
    assert nx.personalizacao(n.clinica_por_slug(a.bd, "cliente-painel"))["cor"] == "#7c2d12"


def test_mcp_aceita_o_objeto_de_rotulos(srv):
    porta, a = srv
    d, cab = _dev_e_chave(a.bd)
    dv.criar_clinica(a.bd, d, "Cliente Mcp", "clinica")
    r = req(porta, "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "dev_clinica_personalizar",
            "arguments": {"clinica": "cliente-mcp", "rotulos": {"agendar": "Marcar"}}}}, cab)[1]
    assert not r["result"].get("isError") and nx.personalizacao(n.clinica_por_slug(a.bd, "cliente-mcp"))["rotulos"] == {"agendar": "Marcar"}
