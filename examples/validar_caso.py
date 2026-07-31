#!/usr/bin/env python3
"""Valida o motor contra o relatório da ferramenta de referência, barra a barra.

Reproduz o fluxo de trabalho que originou o projeto: dado um caso .ANA e o relatório de saída
da ferramenta oficial para o MESMO caso, compara a impedância de Thévenin de cada barra e
reporta a distribuição de erro, estratificada por classe de tensão.

Uso:
    python examples/validar_caso.py CASO.ANA RELATORIO.LST
    python examples/validar_caso.py CASO.ANA RELATORIO.LST --piores 30

O relatório precisa conter a seção 'RELATORIO DE DADOS DE CURTO-CIRCUITO'. Para validação fina,
prefira a seção 'RELATORIO DE IMPEDANCIAS DE BARRA', que traz mais dígitos: aparentes desvios
acima do critério na seção curta são, com frequência, quantização do relatório e não erro do
solver.

Critério de aceitação: erro INDIVIDUAL por barra abaixo de 1%, nas duas sequências.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

from lincc import AnaModel, Solver


def ler_gabarito(caminho: str, secao: str = "RELATORIO DE DADOS DE CURTO-CIRCUITO") -> tuple[dict, dict]:
    """Extrai {barra: |Z1|} e {barra: |Z0|} em pu da seção pedida do relatório.

    A leitura é ANCORADA na seção: começa no cabeçalho e termina no próximo 'RELATORIO DE'.
    Sem essa âncora, linhas de outras seções (matriz Zbarra, impedâncias de barra) casam com o
    mesmo padrão de colunas e contaminam o gabarito com valores de outro significado.

    Régua da linha de dados (0-based): NUM[1:7], Z1MOD[21:29], Z1ANG[30:38],
    Z0MOD[39:47], Z0ANG[48:56].
    """
    with open(caminho, "rb") as f:
        linhas = f.read().decode("cp1252", errors="replace").splitlines()

    ini = next((i for i, ln in enumerate(linhas) if secao in ln), None)
    if ini is None:
        raise ValueError(f"seção {secao!r} não encontrada em {caminho}")
    fim = next((i for i in range(ini + 1, len(linhas)) if "RELATORIO DE" in linhas[i]), len(linhas))

    z1: dict[int, float] = {}
    z0: dict[int, float] = {}
    for ln in linhas[ini + 1:fim]:
        if len(ln) < 56 or not ln[1:7].strip().isdigit():
            continue
        barra = int(ln[1:7])
        for campo, destino in ((ln[21:29], z1), (ln[39:47], z0)):
            try:
                v = float(campo)
            except ValueError:
                continue
            if v > 1e-5:
                destino[barra] = v
    return z1, z0


def erros(lu, n: int, idx: dict, gabarito: dict) -> tuple[list[int], np.ndarray]:
    """Erro percentual por barra: (|Zth_motor| - |Zth_ref|) / |Zth_ref| * 100."""
    alvos = [(b, idx[b], za) for b, za in gabarito.items() if za and b in idx]
    if not alvos:
        return [], np.array([])
    chaves = np.array([k for _, k, _ in alvos])
    z = np.zeros(len(alvos), dtype=complex)
    for ini in range(0, len(alvos), 300):          # em lotes, para não alocar matriz densa
        ks = chaves[ini:ini + 300]
        e = np.zeros((n, len(ks)), dtype=complex)
        for coluna, k in enumerate(ks):
            e[k, coluna] = 1
        z[ini:ini + len(ks)] = lu.solve(e)[ks, np.arange(len(ks))]
    ref = np.array([za for _, _, za in alvos])
    return [b for b, _, _ in alvos], (np.abs(z) - ref) / ref * 100


def resumo(nome: str, err: np.ndarray) -> None:
    if not len(err):
        print(f"  {nome}: nenhuma barra comparável")
        return
    a = np.abs(err)
    print(f"  {nome}: n={len(a):6d}  <1%={(a < 1).mean() * 100:7.3f}%  "
          f"<5%={(a < 5).mean() * 100:7.3f}%  mediana={np.median(a):.4f}%  máx={a.max():.3f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("caso", help="arquivo .ANA")
    ap.add_argument("relatorio", help="relatório de saída da ferramenta de referência (.LST/.txt)")
    ap.add_argument("--piores", type=int, default=20, help="quantas barras piores listar")
    ap.add_argument("--limite", type=float, default=1.0, help="critério de erro, em %%")
    ap.add_argument("--secao", default="RELATORIO DE DADOS DE CURTO-CIRCUITO",
                    help="seção do relatório usada como gabarito")
    args = ap.parse_args()

    print(f"Lendo {args.caso} ...")
    M = AnaModel(args.caso)
    print(f"  barras={len(M.bus_kv)} ramos={len(M.branches)} geradores={len(M.gens)} "
          f"shunts={len(M.shunts)} mútuas={len(M.mutuas)} reatores de linha={len(M.shl)}")

    print("Montando as redes de sequência e fatorando ...")
    S = Solver(M)
    S.factor()
    print(f"  Y1 {S.YP.shape} nnz={S.YP.nnz} | Y0 {S.Y0.shape} nnz={S.Y0.nnz}")

    print(f"Lendo o gabarito de {args.relatorio} ...")
    g1, g0 = ler_gabarito(args.relatorio, args.secao)
    if not g1 and not g0:
        print(f"ERRO: seção {args.secao!r} encontrada, mas nenhuma linha de dados reconhecida.",
              file=sys.stderr)
        return 2
    print(f"  barras no gabarito: Z1={len(g1)}  Z0={len(g0)}")

    b1, e1 = erros(S.luP, len(S.BLP), S.IDXP, g1)
    b0, e0 = erros(S.lu0, len(S.BL0), S.I0P, g0)

    print("\nERRO INDIVIDUAL POR BARRA")
    resumo("Z1", e1)
    resumo("Z0", e0)

    print("\nPor classe de tensão (% de barras abaixo do critério)")
    faixas = [(440, 9e9, "500+"), (230, 440, "230-345"), (69, 230, "69-138"),
              (1, 69, "<69"), (0, 1, "kV=0")]
    for lo, hi, rot in faixas:
        m1 = [i for i, b in enumerate(b1) if lo <= M.bus_kv.get(b, 0) < hi]
        m0 = [i for i, b in enumerate(b0) if lo <= M.bus_kv.get(b, 0) < hi]
        if not m1 and not m0:
            continue
        p1 = (np.abs(e1[m1]) < args.limite).mean() * 100 if m1 else float("nan")
        p0 = (np.abs(e0[m0]) < args.limite).mean() * 100 if m0 else float("nan")
        print(f"  {rot:>8}: Z1 {p1:6.1f}%   Z0 {p0:6.1f}%")

    for rot, barras, err in (("Z1", b1, e1), ("Z0", b0, e0)):
        fora = [(b, err[i]) for i, b in enumerate(barras) if abs(err[i]) >= args.limite]
        if not fora:
            print(f"\n{rot}: nenhuma barra acima de {args.limite}%.")
            continue
        fora.sort(key=lambda t: -abs(t[1]))
        print(f"\n{rot}: {len(fora)} barra(s) acima de {args.limite}% — piores {min(args.piores, len(fora))}:")
        for b, e in fora[:args.piores]:
            print(f"  {b:>7} {M.bus_name.get(b, ''):<14} {M.bus_kv.get(b, 0):6.1f} kV  {e:+9.3f}%")
        print("  Antes de tratar como erro do solver: reavalie na seção de impedâncias de barra "
              "(mais dígitos) e verifique se o erro é disperso (quantização) ou concentrado numa "
              "classe de barras (regra de leitura errada). Ver docs/validacao.md.")

    ok = (len(e1) == 0 or (np.abs(e1) < args.limite).all()) and \
         (len(e0) == 0 or (np.abs(e0) < args.limite).all())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
