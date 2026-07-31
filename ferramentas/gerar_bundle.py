#!/usr/bin/env python3
"""Gera a versão de ARQUIVO ÚNICO (lincc_bundle.py) a partir do pacote src/lincc/.

O bundle serve para anexar em uma sessão de chat ou rodar sem instalar nada. É a mesma lógica do
pacote — sempre corrija no pacote e regenere, nunca o contrário.

    python ferramentas/gerar_bundle.py [-o lincc_bundle.py]
"""
from __future__ import annotations

import argparse
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PKG = RAIZ / "src" / "lincc"

CABECALHO = '''"""LINCC — Linguagem Natural em Curto-Circuito (arquivo único, autocontido).

GERADO por ferramentas/gerar_bundle.py a partir de src/lincc/. Não editar à mão: corrija no
pacote e regenere. Requer apenas numpy e scipy.

    from lincc_bundle import AnaModel, Solver
    M = AnaModel("caso.ANA"); S = Solver(M); S.factor()
    S.fault(BARRA, "3F")

NÃO substitui ferramenta homologada. Ver README para isenção de responsabilidade e limites.
"""

from __future__ import annotations

import numpy as np, pickle, re
import json as _json
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from collections import defaultdict

SB = 100.0   # potência base, MVA
'''

RODAPE = '''

__all__ = ["AnaModel", "Solver", "branches_at", "recomposicao_87b", "SB", "num", "zfin", "zn3"]
'''


def corpo(texto: str) -> str:
    """Remove docstring de módulo, imports e os imports internos do pacote."""
    linhas = texto.split("\n")
    i = 0
    if linhas[0].startswith('"""'):
        i = 1
        while '"""' not in linhas[i]:
            i += 1
        i += 1
    saida = []
    for ln in linhas[i:]:
        if ln.startswith(("import ", "from ")):
            continue
        if ln.startswith("SB = 100.0"):
            continue
        saida.append(ln)
    return "\n".join(saida).strip("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--saida", default=str(RAIZ / "lincc_bundle.py"))
    args = ap.parse_args()

    partes = [
        CABECALHO,
        "\n# ===================== helpers de leitura =====================\n",
        corpo((PKG / "_base.py").read_text(encoding="utf-8")),
        "\n\n# ===================== parser do .ANA =====================\n",
        corpo((PKG / "model.py").read_text(encoding="utf-8")),
        "\n\n# ===================== Ybus, LU e faltas =====================\n",
        corpo((PKG / "solver.py").read_text(encoding="utf-8")),
        RODAPE,
    ]
    texto = "\n".join(partes)
    destino = pathlib.Path(args.saida)
    destino.write_text(texto, encoding="utf-8")
    print(f"{destino}: {len(texto.splitlines())} linhas, {len(texto)} caracteres")
    print("Confira com:  python -c \"import lincc_bundle; print('ok')\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
