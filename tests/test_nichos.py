"""Nicho é dado (nichos.json): cada tipo de negócio fala a própria língua e usa as próprias fotos, sem código por nicho."""
import json
import re
import threading
from pathlib import Path

import pytest

import app as ap
import nichos as nx
import nucleo as n
import paginas as pg
from conftest import proxima
from test_http import req

AQUI = Path(__file__).resolve().parents[1]
# Palavras que só fazem sentido numa clínica: se aparecerem na barbearia, o vocabulário vazou (\b deixa passar "consultar").
PALAVRAS_DE_CLINICA = re.compile(r"\b(consultas?|cl[ií]nicas?|pacientes?|profission\w+|sa[úu]de|m[ée]dic\w+)\b", re.I)


def visivel(html: str) -> str:
    """Só o texto que a pessoa lê: sem script, estilo, atributos (name="profissional" é do formulário) nem o nome do software."""
    sem = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    return re.sub(r"agenda-clinica", "", re.sub(r"<[^>]+>", " ", sem))


@pytest.fixture
def srv(tmp_path):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    ap.semear_demo(a.bd)
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def _chaves(d, ref=None, caminho=""):
    ref = ref if ref is not None else nx.NICHOS[nx.PADRAO]
    for k, v in ref.items():
        assert k in d, f"falta a chave {caminho}{k}"
        if isinstance(v, dict):
            _chaves(d[k], v, f"{caminho}{k}.")


@pytest.mark.parametrize("nicho", list(nx.NICHOS))
def test_nicho_sem_alguma_chave_da_clinica_quebraria_uma_pagina_so_em_producao(nicho):
    _chaves(nx.NICHOS[nicho])


@pytest.mark.parametrize("nicho", list(nx.NICHOS))
def test_foto_de_nicho_sem_arquivo_nos_tres_tamanhos_ou_sem_credito_vira_imagem_quebrada(nicho):
    creditos = json.loads((AQUI / "static" / "creditos.json").read_text(encoding="utf-8"))
    assert len(nx.NICHOS[nicho]["pool"]) >= 3
    for f in nx.NICHOS[nicho]["pool"]:
        assert f in creditos and creditos[f]["pagina"].startswith("https://")
        for suf in ("", "-m", "-b"):
            assert (AQUI / "static" / "fundos" / f"{f}{suf}.jpg").stat().st_size > 5000


def test_foto_da_barbearia_nunca_aparece_numa_clinica_nem_o_contrario():
    assert not set(nx.NICHOS["clinica"]["pool"]) & set(nx.NICHOS["barbearia"]["pool"])
    for slug in ("a", "b", "c", "d", "e", "f", "g", "h"):
        assert pg.fundo_de(slug, {"nicho": "barbearia"}) in nx.NICHOS["barbearia"]["pool"]
        assert pg.fundo_de(slug, {"nicho": "clinica"}) in nx.NICHOS["clinica"]["pool"]
        assert pg.fundo_de(slug) in nx.NICHOS["clinica"]["pool"]


def test_banco_antigo_sem_a_coluna_nicho_ou_valor_desconhecido_cai_na_clinica():
    assert nx.chave({}) == nx.chave({"nicho": "pizzaria"}) == nx.chave(None) == "clinica"


def test_nicho_desconhecido_e_recusado_ao_criar_em_vez_de_virar_clinica_sem_aviso(bd):
    with pytest.raises(n.Erro) as e:
        n.criar_clinica(bd, "Pizza", "a@b.test", "senha-bem-longa", "pizza", "pizzaria")
    assert e.value.codigo == "nicho_invalido"


def test_banco_criado_antes_do_nicho_ganha_a_coluna_e_as_clinicas_antigas_ficam_clinica(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "agenda.db")
    con.executescript(n.SCHEMA)
    con.execute("insert into clinicas(slug,nome,email,criado) values('velha','Velha','','2026-01-01')")
    con.commit()
    assert "nicho" not in [r[1] for r in con.execute("pragma table_info(clinicas)")]  # o banco de antes do nicho, de verdade
    con.close()
    bd = n.Banco(tmp_path)
    assert bd.um("select nicho from clinicas where slug='velha'")["nicho"] == "clinica"


def test_site_de_barbearia_percorre_o_fluxo_inteiro_sem_uma_palavra_de_clinica(srv):
    porta, a = srv
    c = n.clinica_por_slug(a.bd, "demo-barbearia")
    info = n.info_publica(a.bd, c)
    corte = next(s for s in info["servicos"] if s["nome"] == "Corte")
    rafa = next(p for p in info["profissionais"] if p["nome"] == "Rafa Barbeiro")
    dia = proxima(3, 3)
    base = "/c/demo-barbearia"
    paginas = {"home": "/barbearia", "site": base, "servicos": f"{base}/agendar", "horarios": f"{base}/agendar?servico={corte['id']}",
               "confirmar": f"{base}/agendar?servico={corte['id']}&profissional={rafa['id']}&data={dia}&hora=10:00"}
    st, ok, _ = req(porta, "POST", f"{base}/agendar", form={"servico": corte["id"], "profissional": rafa["id"], "data": dia, "hora": "10:00",
                                                           "nome": "Caio", "telefone": "48999990000", "consentimento": "1"})
    assert st == 201 and "Agendado" in ok
    paginas["agendado"] = ok
    codigo = re.search(r"/m/([A-Za-z0-9]+)", ok).group(1)
    paginas.update({"meu": f"/m/{codigo}", "remarcar": f"/m/{codigo}/remarcar", "sem_lembrete": f"/m/{codigo}/sem-lembrete"})
    for nome, destino in paginas.items():
        html = destino if "<html" in destino else req(porta, "GET", destino)[1]
        assert "<html" in html, f"{nome} não abriu"
        achou = PALAVRAS_DE_CLINICA.findall(visivel(html))
        assert not achou, f"vocabulário de clínica vazou na página {nome}: {achou}"


def test_clinica_continua_falando_de_consulta_e_paciente_para_nao_regredir_quem_ja_usa(srv):
    porta, _ = srv
    st, html, _ = req(porta, "GET", "/")
    assert "Para o paciente" in html and "Criar minha clínica" in html and 'name="nicho" value="clinica"' in html
    assert "Agendar consulta" in req(porta, "GET", "/c/demo")[1]


def test_cadastro_pela_pagina_da_barbearia_cria_barbearia_e_a_pagina_dela_usa_as_fotos_dela(srv):
    porta, a = srv
    st, _, r = req(porta, "POST", "/criar", form={"nicho": "barbearia", "nome": "Navalha Fina", "email": "dono@navalha.test", "senha": "senha-bem-longa"})
    assert st in (302, 303) and a.bd.um("select nicho from clinicas where slug='navalha-fina'")["nicho"] == "barbearia"
    html = req(porta, "GET", "/c/navalha-fina")[1]
    assert any(f"/static/fundos/{f}" in html for f in nx.NICHOS["barbearia"]["pool"])
    assert "Agendar horário" in html


def test_cadastro_com_nicho_inventado_volta_erro_na_pagina_e_nao_cria_nada(srv):
    porta, a = srv
    st, html, _ = req(porta, "POST", "/criar", form={"nicho": "pizzaria", "nome": "Pizza Boa", "email": "p@p.test", "senha": "senha-bem-longa"})
    assert st == 422 and "tipo de negócio inválido" in html
    assert a.bd.um("select 1 from clinicas where slug='pizza-boa'") is None


def test_pagina_de_cada_nicho_entra_no_sitemap_e_a_demo_nao_conta_nas_metricas(srv):
    porta, a = srv
    mapa = req(porta, "GET", "/sitemap.xml")[1]
    assert "/barbearia</loc>" in mapa and "/c/demo-barbearia</loc>" in mapa
    assert ap.metricas(a.bd)["clinicas"] == 0
