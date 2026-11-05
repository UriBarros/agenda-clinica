"""Põe a pasta do app no caminho (os módulos são soltos, sem pacote) e dá a fixture de uma clínica pronta."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nucleo as n  # noqa: E402


def proxima(dia_semana: int, minimo_dias: int = 2) -> str:
    """Primeira data (AAAA-MM-DD) com esse dia da semana (0=dom) a pelo menos `minimo_dias` de hoje."""
    d = n.agora_local("America/Sao_Paulo")[0] + dt.timedelta(days=minimo_dias)
    while n.dia_semana(d) != dia_semana:
        d += dt.timedelta(days=1)
    return d.isoformat()


@pytest.fixture
def bd(tmp_path):
    return n.Banco(tmp_path)


@pytest.fixture
def clinica(bd):
    """Clínica com dois locais, duas profissionais e dois serviços.
    Ana: seg/qua 09-12 no Centro, ter/qui 14-18 na Praia. Bia: seg a sex 08-12 no Centro."""
    c = n.criar_clinica(bd, "Clínica Aurora", "dona@aurora.test", "senha-bem-longa", "aurora")
    cid = c["id"]
    centro = n.salvar_local(bd, cid, {"nome": "Centro", "endereco": "Rua A, 1"})
    praia = n.salvar_local(bd, cid, {"nome": "Praia", "endereco": "Av. B, 2"})
    ana = n.salvar_profissional(bd, cid, {"nome": "Ana", "especialidade": "Psicologia"})
    bia = n.salvar_profissional(bd, cid, {"nome": "Bia", "especialidade": "Nutrição"})
    n.definir_disponibilidade(bd, cid, ana, [{"dia": 1, "inicio": "09:00", "fim": "12:00", "local_id": centro},
                                              {"dia": 3, "inicio": "09:00", "fim": "12:00", "local_id": centro},
                                              {"dia": 2, "inicio": "14:00", "fim": "18:00", "local_id": praia},
                                              {"dia": 4, "inicio": "14:00", "fim": "18:00", "local_id": praia}])
    n.definir_disponibilidade(bd, cid, bia, [{"dia": d, "inicio": "08:00", "fim": "12:00", "local_id": centro} for d in range(1, 6)])
    consulta = n.salvar_servico(bd, cid, {"nome": "Consulta", "duracao_min": 50, "preco_centavos": 20000})
    retorno = n.salvar_servico(bd, cid, {"nome": "Retorno", "duracao_min": 30})
    return {"row": bd.um("select * from clinicas where id=?", (cid,)), "id": cid, "centro": centro, "praia": praia,
            "ana": ana, "bia": bia, "consulta": consulta, "retorno": retorno}
