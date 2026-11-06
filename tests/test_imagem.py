"""A imagem só leva o que o Dockerfile copia: dado lido em tempo de import que ficou de fora derruba o pod em CrashLoop (06/11, nichos.json)."""
import fnmatch
import re
from pathlib import Path

AQUI = Path(__file__).resolve().parents[1]


def _copiado() -> list[str]:
    linhas = [ln.split()[1:-1] for ln in (AQUI / "Dockerfile").read_text(encoding="utf-8").splitlines() if ln.startswith("COPY ") and "--from" not in ln]
    return [p for partes in linhas for p in partes]


def test_dockerfile_copia_todo_arquivo_que_o_codigo_le_ao_subir():
    padroes = _copiado()
    citados = re.findall(r'/ "([\w.-]+\.json)"', "".join(p.read_text(encoding="utf-8") for p in AQUI.glob("*.py")))
    # só JSON da raiz: os de static/ (creditos.json) entram pelo `COPY static`, que este teste não precisa re-verificar
    lidos = {p.name for p in AQUI.glob("*.py")} | {n for n in citados if (AQUI / n).is_file()}
    faltando = sorted(n for n in lidos if not any(fnmatch.fnmatch(n, pad) for pad in padroes))
    assert not faltando, f"o Dockerfile não copia {faltando}: o pod subiria sem eles (CrashLoopBackOff)"
