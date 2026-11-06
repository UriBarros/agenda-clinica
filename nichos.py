"""Nichos como DADO (nichos.json): vocabulário, pool de fotos e demonstração de cada tipo de negócio.
Nicho novo = um objeto no JSON (mesmas chaves de "clinica"; o teste cobra) + 3 fotos em static/fundos. Nenhum código por nicho."""
from __future__ import annotations

import json
import re
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


NAO_EDITAVEIS = {"nome", "ld"}  # o que é string no nicho e o dev PODE reescrever: os demais rótulos
COR = re.compile(r"^#[0-9a-fA-F]{6}$")
ROTULO = re.compile(r"^[^<>&\"'`\\\x00-\x1f]{0,80}$")  # sem HTML nem aspas: o rótulo entra em página e em atributo


def rotulos_editaveis() -> list[str]:
    return [k for k, v in NICHOS[PADRAO].items() if isinstance(v, str) and k not in NAO_EDITAVEIS]


def personalizacao(c) -> dict:
    """{"cor": "#rrggbb", "rotulos": {...}} gravado pelo dev; clínica sem a coluna (banco antigo) ou com JSON ruim = sem personalização."""
    try:
        d = json.loads(c["personalizar"] or "{}")
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def contraste_com_branco(cor: str) -> float:
    canal = lambda v: (v / 255 / 12.92) if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4  # noqa: E731
    r, g, b = (canal(int(cor[i:i + 2], 16)) for i in (1, 3, 5))
    return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05)


def validar_personalizacao(cor, rotulos) -> dict:
    """Regra determinística, não gosto: cor de botão precisa dar 4,5:1 com o texto branco (WCAG AA); rótulo só de chave editável e sem HTML."""
    out: dict = {}
    if cor not in (None, ""):
        if not isinstance(cor, str) or not COR.match(cor):
            raise ValueError("cor deve ser #rrggbb")
        if contraste_com_branco(cor) < 4.5:
            raise ValueError("cor clara demais: o texto branco do botão precisa de contraste 4,5:1 (use um tom mais escuro)")
        out["cor"] = cor.lower()
    if rotulos not in (None, {}):
        if not isinstance(rotulos, dict):
            raise ValueError("rotulos deve ser um objeto {chave: texto}")
        ok = set(rotulos_editaveis())
        ruim = [k for k in rotulos if k not in ok]
        if ruim:
            raise ValueError(f"rótulo desconhecido: {ruim[0]!r} (editáveis: {', '.join(sorted(ok))})")
        if any(not isinstance(v, str) or not ROTULO.match(v) for v in rotulos.values()):
            raise ValueError("rótulo com mais de 80 caracteres ou com < > & aspas")
        out["rotulos"] = dict(rotulos)
    return out


def vocab(c) -> dict:
    base = NICHOS[chave(c)]
    ed = set(rotulos_editaveis())
    return {**base, **{k: v for k, v in personalizacao(c).get("rotulos", {}).items() if k in ed and isinstance(v, str)}}


def tema(c) -> str:
    """Cor de destaque do cliente (já validada ao gravar; confere de novo ao ler: dado de banco antigo ou editado à mão não vira CSS)."""
    cor = personalizacao(c).get("cor", "")
    return cor if isinstance(cor, str) and COR.match(cor) and contraste_com_branco(cor) >= 4.5 else ""
