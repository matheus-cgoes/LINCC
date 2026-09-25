#!/usr/bin/env python3
"""Gera a versão de ARQUIVO ÚNICO (lincc_bundle.py) a partir do pacote src/lincc/.

O bundle serve para anexar em uma sessão de chat ou rodar sem instalar nada. É a mesma lógica do
pacote — sempre corrija no pacote e regenere, nunca o contrário.

    python ferramentas/gerar_bundle.py [-o lincc_bundle.py]
"""
from __future__ import annotations

import argparse
import re
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
        s = ln.lstrip()
        if s.startswith("from .") or s.startswith("from . import"):
            ind = ln[:len(ln) - len(s)]
            # no arquivo único todos os nomes são globais; o alias de submódulo aponta
            # para o espaço de nome equivalente criado no rodapé
            m = re.match(r"from \. import (\w+) as (\w+)", s)
            saida.append(f"{ind}{m.group(2)} = {m.group(1)}" if m else f"{ind}pass")
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

    init = (PKG / "__init__.py").read_text(encoding="utf-8")
    doc = init.split('"""')[1]
    cabecalho = ('"""' + doc.rstrip() + """

ARQUIVO ÚNICO. Gerado por ferramentas/gerar_bundle.py a partir de src/lincc/ — não editar
à mão. Aqui todos os nomes do pacote são globais: use `import lincc_bundle as lincc` e as
chamadas documentadas acima valem como estão, inclusive lincc.fluxo.*, lincc.curvas.*,
lincc.sm211.* e lincc.dados_externos.*. Requer apenas numpy e scipy.
\"\"\"
""".replace('\\"', '"') + CABECALHO.split('"""', 2)[2])
    ini = init.index("_ORIENTACAO = ")
    fim = init.index("\n", init.index("def orientacao"))
    corpo_orient = init[ini:]
    # até o fim da função orientacao (próximo bloco de topo ou fim do arquivo)
    linhas_o = corpo_orient.split("\n")
    k = next(j for j, l in enumerate(linhas_o) if l.startswith("def orientacao"))
    j = k + 1
    while j < len(linhas_o) and (linhas_o[j].startswith((" ", "\t")) or not linhas_o[j].strip()):
        j += 1
    orient = "\n".join(linhas_o[:j])
    todos = re.search(r"__all__ = \[(.*?)\]", init, re.S).group(1)
    nomes = [x.strip().strip('"\'') for x in todos.replace("\n", " ").split(",") if x.strip()]

    def publicos(mod):
        fonte = (PKG / f"{mod}.py").read_text(encoding="utf-8")
        return sorted(set(re.findall(r"^def ([a-zA-Z]\w*)", fonte, re.M)) |
                      set(re.findall(r"^([A-Z][A-Z_0-9]+) =", fonte, re.M)))
    ns = ["", "# ===================== submódulos como espaços de nome =====================",
          "import types as _types"]
    for mod in ("curvas", "sm211", "dados_externos", "fluxo"):
        itens = ", ".join(f"{p}={p}" for p in publicos(mod))
        ns.append(f"{mod} = _types.SimpleNamespace({itens})")
    rodape = "\n".join(ns) + "\n\n__all__ = " + repr(nomes) + "\n"

    partes = [
        cabecalho,
        "\n# ===================== helpers de leitura =====================\n",
        corpo((PKG / "_base.py").read_text(encoding="utf-8")),
        "\n\n# ===================== parser do .ANA =====================\n",
        corpo((PKG / "parser_anafas.py").read_text(encoding="utf-8")),
        "\n\n# ===================== parser do .PWF (ANAREDE) =====================\n",
        corpo((PKG / "parser_anarede.py").read_text(encoding="utf-8")),
        "\n\n# ===================== Ybus, LU e faltas =====================\n",
        corpo((PKG / "solver.py").read_text(encoding="utf-8")),
        "\n\n# ===================== motor de protecao =====================\n",
        corpo((PKG / "protecao.py").read_text(encoding="utf-8")),
        "\n\n# ===================== protecao de distancia =====================\n",
        corpo((PKG / "distancia.py").read_text(encoding="utf-8")),
        "\n\n# ===================== motor de fluxo de potencia =====================\n",
        corpo((PKG / "fluxo.py").read_text(encoding="utf-8")),
        "\n\n# ===================== curvas de tempo inverso =====================\n",
        corpo((PKG / "curvas.py").read_text(encoding="utf-8")),
        "\n\n# ===================== Submodulo 2.11 =====================\n",
        corpo((PKG / "sm211.py").read_text(encoding="utf-8")),
        "\n\n# ===================== dados externos =====================\n",
        corpo((PKG / "dados_externos.py").read_text(encoding="utf-8")),
        "\n\n# ===================== orientação para agentes =====================\n",
        orient,
        rodape,
    ]
    texto = "\n".join(partes)
    destino = pathlib.Path(args.saida)
    destino.write_text(texto, encoding="utf-8")
    print(f"{destino}: {len(texto.splitlines())} linhas, {len(texto)} caracteres")
    print("Confira com:  python -c \"import lincc_bundle; print('ok')\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
