"""Protocolo aberto: o esquema JSON descreve EXATAMENTE o que o servidor exporta (se o código mudar sem o esquema, falha), e os arquivos saem do ar."""
import json
import re
import threading
from pathlib import Path

import pytest

import app as ap
import migracao as mig
import nucleo as n
from conftest import proxima
from test_http import req

AQUI = Path(__file__).resolve().parents[1]
ESQUEMA = json.loads((AQUI / "schema" / "agenda-clinica-1.schema.json").read_text(encoding="utf-8"))


def valida(dado, esq, caminho="$") -> list[str]:
    """Validador mínimo do subconjunto de JSON Schema que o esquema usa (sem dependência externa, como o resto do projeto)."""
    erros: list[str] = []
    tipos = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list, "null": type(None)}
    if "const" in esq and dado != esq["const"]:
        erros.append(f"{caminho}: esperado {esq['const']!r}")
    if "enum" in esq and dado not in esq["enum"]:
        erros.append(f"{caminho}: {dado!r} fora de {esq['enum']}")
    if "type" in esq:
        ts = esq["type"] if isinstance(esq["type"], list) else [esq["type"]]
        if not any(isinstance(dado, tipos[t]) and not (t == "integer" and isinstance(dado, bool)) for t in ts):
            return erros + [f"{caminho}: tipo {type(dado).__name__} não é {ts}"]
    if isinstance(dado, str):
        if "pattern" in esq and not re.search(esq["pattern"], dado):
            erros.append(f"{caminho}: {dado!r} não casa {esq['pattern']}")
        if "maxLength" in esq and len(dado) > esq["maxLength"]:
            erros.append(f"{caminho}: texto longo demais")
    if isinstance(dado, int) and not isinstance(dado, bool):
        if "minimum" in esq and dado < esq["minimum"] or "maximum" in esq and dado > esq["maximum"]:
            erros.append(f"{caminho}: {dado} fora dos limites")
    if isinstance(dado, dict):
        erros += [f"{caminho}: falta {k!r}" for k in esq.get("required", []) if k not in dado]
        props = esq.get("properties", {})
        if esq.get("additionalProperties") is False:
            erros += [f"{caminho}: campo {k!r} não existe no esquema" for k in dado if k not in props]
        for k, v in dado.items():
            if k in props:
                erros += valida(v, props[k], f"{caminho}.{k}")
            elif isinstance(esq.get("additionalProperties"), dict):
                erros += valida(v, esq["additionalProperties"], f"{caminho}.{k}")
    if isinstance(dado, list) and "items" in esq:
        for i, v in enumerate(dado):
            erros += valida(v, esq["items"], f"{caminho}[{i}]")
    return erros


def _completo(bd, clinica):
    """Uma clínica com TUDO que o formato carrega: agendamento, bloqueio, personalização."""
    c = clinica["row"]
    n.agendar(bd, c, clinica["consulta"], clinica["ana"], proxima(1, 3), "09:00", "Maria", "48999990000", "m@x.test", consentimento=True)
    n.bloquear(bd, c, proxima(2, 3) + "T08:00", proxima(2, 3) + "T10:00", clinica["bia"], "folga")
    with bd.escrita() as con:
        con.execute("update clinicas set personalizar=? where id=?", (json.dumps({"cor": "#0f766e", "rotulos": {"agendar": "Marcar"}}), c["id"]))
    return n.clinica_por_slug(bd, "aurora")


def test_o_que_o_servidor_exporta_cumpre_o_esquema_com_e_sem_pacientes(bd, clinica):
    c = _completo(bd, clinica)
    for com in (False, True):
        arquivo = json.loads(json.dumps(mig.exportar(bd, c, com_pacientes=com)))
        assert valida(arquivo, ESQUEMA) == [], com


def test_o_esquema_nao_tem_campo_que_o_servidor_nunca_exporta_nem_o_contrario(bd, clinica):
    """Deriva do contrato: campo novo no código sem o esquema (ou esquema com campo morto) derruba este teste."""
    c = _completo(bd, clinica)
    arquivo = mig.exportar(bd, c, com_pacientes=True)
    assert set(arquivo) == set(ESQUEMA["properties"])
    for secao in ("clinica", "locais", "profissionais", "servicos", "bloqueios", "agendamentos"):
        esq = ESQUEMA["properties"][secao]
        esq_item = esq["items"] if esq["type"] == "array" else esq
        item = arquivo[secao][0] if isinstance(arquivo[secao], list) else arquivo[secao]
        assert set(item) == set(esq_item["properties"]), secao
    assert set(arquivo["profissionais"][0]["janelas"][0]) == set(ESQUEMA["properties"]["profissionais"]["items"]["properties"]["janelas"]["items"]["properties"])


@pytest.mark.parametrize("estraga", [lambda a: a.update(formato="agenda-clinica/2"), lambda a: a["clinica"].pop("nome"), lambda a: a["servicos"][0].update(duracao_min="longa"),
                                     lambda a: a["profissionais"][0]["janelas"][0].update(dia=9), lambda a: a.update(campo_novo=1), lambda a: a["clinica"].update(passo_min=7)])
def test_o_validador_pega_arquivo_fora_do_esquema(bd, clinica, estraga):
    arquivo = json.loads(json.dumps(mig.exportar(bd, clinica["row"])))
    estraga(arquivo)
    assert valida(arquivo, ESQUEMA)


def test_ida_e_volta_preserva_a_personalizacao(bd, clinica, tmp_path):
    c = _completo(bd, clinica)
    novo = n.Banco(tmp_path / "outro")
    mig.importar(novo, json.loads(json.dumps(mig.exportar(bd, c))), "dev@novo.test", "senha-nova-bem-longa")
    assert json.loads(n.clinica_por_slug(novo, "aurora")["personalizar"]) == {"cor": "#0f766e", "rotulos": {"agendar": "Marcar"}}


def test_importar_nao_aceita_personalizacao_com_html_ou_cor_clara(bd, clinica, tmp_path):
    arquivo = json.loads(json.dumps(mig.exportar(bd, clinica["row"])))
    arquivo["personalizar"] = {"rotulos": {"agendar": "<script>x</script>"}}
    with pytest.raises(n.Erro):
        mig.importar(n.Banco(tmp_path / "a"), arquivo, "dev@novo.test", "senha-nova-bem-longa")
    arquivo["personalizar"] = {"cor": "#ffff00"}
    with pytest.raises(n.Erro):
        mig.importar(n.Banco(tmp_path / "b"), arquivo, "dev@novo.test", "senha-nova-bem-longa")


@pytest.fixture
def srv(tmp_path):
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


def test_o_contrato_sai_do_ar_como_esta_no_repositorio_e_a_pagina_aponta_para_ele(srv):
    porta, _ = srv
    st, esq, r = req(porta, "GET", "/schema/agenda-clinica-1.json")
    assert st == 200 and esq == ESQUEMA and "schema+json" in r.getheader("Content-Type")
    st, md, r = req(porta, "GET", "/protocolo.md")
    assert st == 200 and md == (AQUI / "PROTOCOLO.md").read_text(encoding="utf-8") and "agenda-clinica/1" in md
    st, html, _ = req(porta, "GET", "/protocolo")
    assert st == 200 and "/schema/agenda-clinica-1.json" in html and "/protocolo.md" in html and "MIT" in html
    assert "/protocolo</loc>" in req(porta, "GET", "/sitemap.xml")[1]


def test_o_documento_do_protocolo_cita_so_operacoes_e_codigos_que_existem():
    import ops
    texto = (AQUI / "PROTOCOLO.md").read_text(encoding="utf-8")
    for codigo in ("escopo_insuficiente", "chave_obrigatoria", "outra_clinica"):
        assert codigo in texto and codigo in (AQUI / "ops.py").read_text(encoding="utf-8") + (AQUI / "devs.py").read_text(encoding="utf-8")
    assert {"leitura", "escrita", "dev"} <= set(ops.NIVEL) and "ad_" in texto and "ac_" in texto


def test_dockerfile_leva_o_esquema_e_o_documento_do_protocolo():
    d = (AQUI / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY schema" in d and "PROTOCOLO.md" in d
