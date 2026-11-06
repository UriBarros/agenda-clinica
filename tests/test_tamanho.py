"""Catraca de tamanho da engine única: um repositório MIT, um motor, N nichos como dado. O código só pode encolher, e nicho novo nunca entra em .py."""
import json
import re
from pathlib import Path

import pytest

import nichos as nx

AQUI = Path(__file__).resolve().parents[1]
TETO = json.loads((AQUI / "tamanho.json").read_text(encoding="utf-8"))
CODIGO = sorted(AQUI.glob("*.py"))
TOLERANCIA = 0.02  # sobra máxima antes de exigir que o teto desça: sem isso a catraca vira folga eterna


def _linhas() -> int:
    return sum(len(p.read_text(encoding="utf-8").splitlines()) for p in CODIGO)


def test_codigo_da_engine_nao_cresce_acima_do_teto_sem_alguem_decidir():
    assert _linhas() <= TETO["linhas_codigo"], (f"{_linhas()} linhas > teto {TETO['linhas_codigo']}: reuse o que existe (nicho é dado em nichos.json) "
                                                "ou, se o crescimento é legítimo, suba o teto em tamanho.json explicando no PR")


def test_teto_desce_junto_quando_o_codigo_encolhe():
    assert _linhas() >= TETO["linhas_codigo"] * (1 - TOLERANCIA), f"o código encolheu para {_linhas()}: baixe linhas_codigo em tamanho.json (a catraca só desce)"


def test_nichos_json_nao_incha_sem_decisao():
    tam = (AQUI / "nichos.json").stat().st_size
    assert TETO["bytes_nichos_json"] * (1 - TOLERANCIA) <= tam <= TETO["bytes_nichos_json"], f"nichos.json tem {tam} bytes; ajuste bytes_nichos_json se foi de propósito"


@pytest.mark.parametrize("nicho", [k for k in nx.NICHOS if k != nx.PADRAO])
def test_nicho_novo_nao_vira_codigo_python_so_dado(nicho):
    for p in CODIGO:
        assert not re.search(rf"\b{nicho}\b", p.read_text(encoding="utf-8"), re.I), f"{p.name} cita o nicho {nicho!r}: o que muda por nicho vive em nichos.json"
        assert nicho not in p.name


def test_foto_de_fundo_continua_leve_porque_site_que_carrega_eternamente_nao_vende():
    fundos = AQUI / "static" / "fundos"
    limites = {"-m": TETO["foto_celular_max_bytes"], "-b": TETO["foto_desfocada_max_bytes"], "": TETO["foto_cheia_max_bytes"]}
    for f in nx.POOL_TODOS:
        for suf, maximo in limites.items():
            tam = (fundos / f"{f}{suf}.jpg").stat().st_size
            assert tam <= maximo, f"{f}{suf}.jpg tem {tam} bytes (máx {maximo}): recomprima"
