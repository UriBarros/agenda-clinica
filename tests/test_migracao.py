"""Migração: exportar do nosso servidor, importar no do dev, apagar o que ficou. O que não pode vazar e o que não pode ficar pela metade."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import app as ap
import migracao as mig
import nucleo as n
from conftest import proxima
from test_http import req

AQUI = Path(__file__).resolve().parents[1]


def _com_agendamento(bd, clinica):
    c = clinica["row"]
    dia = proxima(1, 3)
    ag = n.agendar(bd, c, clinica["consulta"], clinica["ana"], dia, "09:00", "Maria Souza", "48999990000", "maria@x.test", consentimento=True)
    return ag, dia


def test_exportar_nunca_leva_senha_chave_sessao_nem_instancia_do_whatsapp(bd, clinica):
    c = clinica["row"]
    chave = n.criar_chave(bd, c["id"], "agente", "escrita")["chave"]
    n.salvar_whatsapp(bd, c, True, "minha-instancia-secreta", 24, True)
    senha_hash = bd.um("select senha from usuarios where clinica_id=?", (c["id"],))["senha"]
    texto = json.dumps(mig.exportar(bd, n.clinica_por_slug(bd, "aurora"), com_pacientes=True), ensure_ascii=False)
    assert chave not in texto and senha_hash not in texto and "minha-instancia-secreta" not in texto and "dona@aurora.test" not in texto


def test_exportar_sem_pacientes_nao_leva_agendamento_nem_telefone(bd, clinica):
    _com_agendamento(bd, clinica)
    c = n.clinica_por_slug(bd, "aurora")
    sem, com = mig.exportar(bd, c), mig.exportar(bd, c, com_pacientes=True)
    assert "agendamentos" not in sem and "48999990000" not in json.dumps(sem) and "Maria Souza" not in json.dumps(sem)
    assert com["agendamentos"][0]["paciente_nome"] == "Maria Souza"


def test_ida_e_volta_recria_a_mesma_agenda_e_o_codigo_do_paciente_continua_valendo(bd, clinica, tmp_path):
    ag, dia = _com_agendamento(bd, clinica)
    c = n.clinica_por_slug(bd, "aurora")
    arquivo = json.loads(json.dumps(mig.exportar(bd, c, com_pacientes=True)))  # passa pelo JSON como na vida real
    novo = n.Banco(tmp_path / "outro")
    res = mig.importar(novo, arquivo, "dev@novo.test", "senha-nova-bem-longa")
    assert res["slug"] == "aurora" and res["profissionais"] == 2 and res["agendamentos"] == 1
    c2 = n.clinica_por_slug(novo, "aurora")
    chaves = lambda info: ([(p["nome"], [(j["dia"], j["inicio"], j["fim"]) for j in p["disponibilidade"]]) for p in info["profissionais"]],  # noqa: E731
                           [(s["nome"], s["duracao_min"], s["preco_centavos"]) for s in info["servicos"]], [loc["nome"] for loc in info["locais"]])
    assert chaves(n.info_publica(novo, c2)) == chaves(n.info_publica(bd, c))
    serv2 = n.info_publica(novo, c2)["servicos"][0]["id"]
    horas = lambda b_, c_, s_: [(h["data"], h["hora"]) for h in n.horarios_livres(b_, c_, s_, None, dia, limite=50)]  # noqa: E731
    assert horas(novo, c2, serv2) == horas(bd, c, clinica["consulta"])  # o horário das 09:00 continua ocupado no servidor novo
    r, cl = n.agendamento_por_codigo(novo, ag["codigo"])
    assert r["paciente_nome"] == "Maria Souza" and cl["slug"] == "aurora"
    assert n.entrar(novo, "dev@novo.test", "senha-nova-bem-longa")


def test_importar_nao_traz_chave_nem_liga_whatsapp(bd, clinica, tmp_path):
    c = clinica["row"]
    n.criar_chave(bd, c["id"], "agente", "escrita")
    n.salvar_whatsapp(bd, c, True, "instancia-x", 24, True)
    novo = n.Banco(tmp_path / "outro")
    mig.importar(novo, mig.exportar(bd, n.clinica_por_slug(bd, "aurora")), "dev@novo.test", "senha-nova-bem-longa")
    c2 = n.clinica_por_slug(novo, "aurora")
    assert not c2["whatsapp_ativo"] and c2["whatsapp_instancia"] == "" and n.listar_chaves(novo, c2["id"]) == []


def test_arquivo_com_referencia_quebrada_nao_deixa_clinica_pela_metade(bd, clinica, tmp_path):
    arquivo = mig.exportar(bd, n.clinica_por_slug(bd, "aurora"))
    arquivo["profissionais"][0]["janelas"][0]["local"] = 99999  # aponta para um local que não existe
    novo = n.Banco(tmp_path / "outro")
    with pytest.raises(n.Erro) as e:
        mig.importar(novo, arquivo, "dev@novo.test", "senha-nova-bem-longa")
    assert e.value.codigo == "arquivo_invalido"
    assert novo.um("select count(*) q from clinicas")["q"] == 0 and novo.um("select count(*) q from usuarios")["q"] == 0
    mig.importar(novo, mig.exportar(bd, n.clinica_por_slug(bd, "aurora")), "dev@novo.test", "senha-nova-bem-longa")  # o e-mail não ficou preso


@pytest.mark.parametrize("lixo", [{}, {"formato": "outro/9"}, {"formato": mig.FORMATO}, [1, 2], {"formato": mig.FORMATO, "clinica": {"nome": "X"}, "locais": "não é lista"}])
def test_arquivo_que_nao_e_nosso_e_recusado_sem_criar_nada(bd, lixo):
    with pytest.raises(n.Erro):
        mig.importar(bd, lixo, "dev@novo.test", "senha-nova-bem-longa")
    assert bd.um("select count(*) q from clinicas")["q"] == 0


def test_apagar_remove_tudo_da_clinica_e_nenhuma_linha_de_outra(bd, clinica):
    _com_agendamento(bd, clinica)
    outra = n.criar_clinica(bd, "Outra", "o@o.test", "senha-bem-longa", "outra")
    n.salvar_local(bd, outra["id"], {"nome": "L"})
    c = clinica["row"]
    n.criar_chave(bd, c["id"], "k", "leitura")
    mig.apagar_clinica(bd, "aurora")
    for tabela in ("locais", "profissionais", "servicos", "bloqueios", "agendamentos", "chaves", "usuarios"):
        assert bd.um(f"select count(*) q from {tabela} where clinica_id=?", (c["id"],))["q"] == 0, tabela
    assert bd.um("select count(*) q from disponibilidade")["q"] == 0 and bd.um("select count(*) q from lembretes")["q"] == 0
    assert bd.um("select count(*) q from locais where clinica_id=?", (outra["id"],))["q"] == 1


def test_importar_duas_vezes_nao_sobrescreve_o_agendamento_da_primeira(bd, clinica, tmp_path):
    ag, _ = _com_agendamento(bd, clinica)
    arquivo = mig.exportar(bd, n.clinica_por_slug(bd, "aurora"), com_pacientes=True)
    novo = n.Banco(tmp_path / "outro")
    a = mig.importar(novo, arquivo, "um@novo.test", "senha-nova-bem-longa")
    b = mig.importar(novo, arquivo, "dois@novo.test", "senha-nova-bem-longa")
    assert a["slug"] == "aurora" and b["slug"] != "aurora" and b["agendamentos"] == 0
    assert n.agendamento_por_codigo(novo, ag["codigo"])[1]["slug"] == "aurora"


@pytest.fixture
def srv(tmp_path):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    ap.semear_demo(a.bd)
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def test_rota_de_exportar_exige_chave_e_so_leva_paciente_se_pedido(srv):
    porta, a = srv
    c = n.clinica_por_slug(a.bd, "demo")
    info = n.info_publica(a.bd, c)
    n.agendar(a.bd, c, info["servicos"][0]["id"], info["profissionais"][1]["id"], proxima(1, 3), "08:00", "Paciente Teste", "48999990000", consentimento=True)
    assert req(porta, "GET", "/api/v1/exportar")[0] == 401
    k = n.criar_chave(a.bd, c["id"], "t", "leitura")["chave"]
    cab = {"Authorization": f"Bearer {k}"}
    st, sem, _ = req(porta, "GET", "/api/v1/exportar", cab=cab)
    assert st == 200 and sem["formato"] == mig.FORMATO and "agendamentos" not in sem
    st, com, _ = req(porta, "GET", "/api/v1/exportar?com_pacientes=true", cab=cab)
    assert com["agendamentos"][0]["paciente_nome"] == "Paciente Teste"
    mcp = req(porta, "POST", "/mcp", corpo={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, cab=cab)[1]
    assert "exportar_clinica" in [t["name"] for t in mcp["result"]["tools"]]


def test_download_do_painel_exige_login_e_sai_como_arquivo(srv):
    porta, a = srv
    n.criar_clinica(a.bd, "Dev Clinic", "dev@c.test", "senha-bem-longa", "dev-clinic")
    assert req(porta, "GET", "/painel/exportar")[0] in (302, 303)
    _, _, r = req(porta, "POST", "/entrar", form={"email": "dev@c.test", "senha": "senha-bem-longa"})
    cab = {"Cookie": r.getheader("Set-Cookie").split(";")[0]}
    st, corpo, r2 = req(porta, "GET", "/painel/exportar", cab=cab)
    assert st == 200 and 'attachment; filename="dev-clinic-agenda.json"' in r2.getheader("Content-Disposition") and corpo["clinica"]["slug"] == "dev-clinic"


def test_pagina_para_devs_tem_o_link_do_git_o_caminho_de_migracao_e_entra_no_sitemap(srv):
    porta, _ = srv
    st, html, _ = req(porta, "GET", "/devs")
    assert st == 200 and ap.REPO_URL in html and "app.py importar" in html and "/api/v1/exportar" in html and "MIT" in html
    assert "/devs</loc>" in req(porta, "GET", "/sitemap.xml")[1] and 'href="/devs"' in req(porta, "GET", "/")[1]


def test_comandos_exportar_e_importar_de_linha_de_comando_fecham_o_ciclo(bd, clinica, tmp_path):
    origem = tmp_path / "origem"
    bd_origem = n.Banco(origem)
    n.criar_clinica(bd_origem, "Barbearia Fina", "b@b.test", "senha-bem-longa", "fina", "barbearia")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    saida = subprocess.run([sys.executable, str(AQUI / "app.py"), "exportar", "fina"], capture_output=True, text=True, env={**env, "DATA_DIR": str(origem)}, check=True).stdout
    arq = tmp_path / "fina.json"
    arq.write_text(saida, encoding="utf-8")
    r = subprocess.run([sys.executable, str(AQUI / "app.py"), "importar", str(arq)], capture_output=True, text=True,
                       env={**env, "DATA_DIR": str(tmp_path / "destino"), "AGENDA_EMAIL": "dev@x.test", "AGENDA_SENHA": "senha-nova-bem-longa"})
    assert r.returncode == 0 and "importada" in r.stdout, r.stderr
    assert n.clinica_por_slug(n.Banco(tmp_path / "destino"), "fina")["nicho"] == "barbearia"
