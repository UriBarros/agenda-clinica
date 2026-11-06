"""Nichos como DADO (nichos.json): vocabulário, pool de fotos e demonstração de cada tipo de negócio.
Nicho novo = um objeto no JSON (mesmas chaves de "clinica"; o teste cobra) + 3 fotos em static/fundos. Nenhum código por nicho."""
from __future__ import annotations

import json
from pathlib import Path

NICHOS: dict[str, dict] = json.loads((Path(__file__).resolve().parent / "nichos.json").read_text(encoding="utf-8"))
PADRAO = "clinica"
POOL_TODOS = [f for v in NICHOS.values() for f in v["pool"]]


def chave(c) -> str:
    """Aceita dict ou sqlite3.Row; clínica sem a coluna (banco antigo) ou com valor desconhecido cai no padrão."""
    try:
        k = c["nicho"]
    except (KeyError, IndexError, TypeError):
        return PADRAO
    return k if k in NICHOS else PADRAO


def vocab(c) -> dict:
    return NICHOS[chave(c)]
