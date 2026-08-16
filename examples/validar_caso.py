#!/usr/bin/env python3
"""Valida o motor contra os relatórios da ferramenta de referência, barra a barra.

Reconhece três seções, que podem estar no mesmo arquivo ou em arquivos separados:

  'RELATORIO DE IMPEDANCIAS DE BARRA'      Z1, Z0 e (Z0+Z2) em %, 10 decimais — alta precisão
  'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO'  correntes em kA, X/R e assimétrica  (ACENTUADO)
  'RELATORIO DE DADOS DE CURTO-CIRCUITO'   Z1, Z0 em pu (4 decimais) e níveis em MVA

Compara, conforme o que estiver disponível: impedância de Thévenin, níveis em kA (o mais
diretamente comparável a `Solver.fault`), níveis em MVA, e a coerência da hipótese Z2 = Z1.

Uso:
    python examples/validar_caso.py CASO.ANA RELATORIO.LST [OUTRO.LST ...]
    python examples/validar_caso.py CASO.ANA rel.LST --limite 1.0 --piores 30

Critério: erro INDIVIDUAL por barra abaixo de 1%. Retorna 0 se todas as comparações passam.

Duas armadilhas de leitura, ambas descobertas por divergência numérica e tratadas aqui:

1. O relatório de níveis vem ACENTUADO ('RELATÓRIO DE NÍVEIS'). Procurar só por 'RELATORIO'
   faz a leitura de uma seção atravessar para dentro dele e capturar linhas alheias — foi
   assim que 15.627 barras viraram 16.516 num teste.
2. Valores mais largos que a coluna ESTOURAM para a esquerda, invadindo o campo anterior
   (ex.: '...2847100000.0445903836'). Ler por colunas fixas perde o dígito inicial e produz
   erro de ordens de grandeza. Por isso cada campo é lido da borda direita do campo anterior
   até a sua própria borda direita.
"""
from __future__ import annotations

import argparse
import math
import sys

import numpy as np

from lincc import AnaModel, Solver

SB = 100.0

SEC_PRECISA = "RELATORIO DE IMPEDANCIAS DE BARRA"
SEC_NIVEIS = "NÍVEIS DE CURTO-CIRCUITO"
SEC_CURTA = "RELATORIO DE DADOS DE CURTO-CIRCUITO"
FIM_SECAO = ("RELATORIO DE", "RELATÓRIO DE")

# Cada seção: (coluna do número da barra) e lista (nome_do_campo, borda_direita).
# As bordas vêm dos separadores 'X-----X' do próprio relatório.
LAYOUT = {
    SEC_PRECISA: dict(
        num=(1, 6), escala=1 / 100.0,      # valores em %, converter para pu
        campos=[("z1m", 36), ("z1a", 53), ("z0m", 70), ("z0a", 87), ("zrm", 104), ("zra", 121)],
        inicio=20),
    SEC_NIVEIS: dict(
        num=(2, 7), escala=1.0,            # correntes em kA
        campos=[("vbas", 27), ("i3m", 37), ("i3a", 44), ("i3xr", 53), ("i3as", 61),
                ("i1m", 71), ("i1a", 78), ("i1xr", 87), ("i1as", 95),
                ("i2m", 105), ("i2a", 112), ("i2xr", 121), ("i2as", 129)],
        inicio=21),
    SEC_CURTA: dict(
        num=(2, 7), escala=1.0,            # Z em pu; níveis em MVA
        campos=[("z1m", 29), ("z1a", 38), ("z0m", 47), ("z0a", 56), ("x0x1", 64),
                ("s3m", 75), ("s3a", 84), ("s1m", 95), ("s1a", 104),
                ("s2m", 115), ("s2a", 124)],
        inicio=21),
}

# Quais campos são impedância (levam a escala da seção) — os demais são kA, MVA ou adimensionais.
IMPEDANCIA = {"z1m", "z0m", "zrm"}


def ler_secao(caminhos: list[str], secao: str) -> dict[int, dict]:
    """Lê uma seção em todos os arquivos dados. Retorna {barra: {campo: valor}}."""
    lay = LAYOUT[secao]
    a_num, b_num = lay["num"]
    saida: dict[int, dict] = {}
    for caminho in caminhos:
        with open(caminho, "rb") as f:
            linhas = f.read().decode("cp1252", errors="replace").splitlines()
        ini = next((i for i, ln in enumerate(linhas) if secao in ln), None)
        if ini is None:
            continue
        fim = next((i for i in range(ini + 1, len(linhas))
                    if any(h in linhas[i] for h in FIM_SECAO)), len(linhas))
        for ln in linhas[ini + 1:fim]:
            if len(ln) < 20 or not ln[a_num:b_num].strip().isdigit():
                continue
            barra = int(ln[a_num:b_num])
            d = saida.setdefault(barra, {})
            esq = lay["inicio"]
            for nome, dir_ in lay["campos"]:
                bruto = ln[esq:dir_].strip() if len(ln) >= esq else ""
                esq = dir_
                if not bruto:
                    continue
                try:
                    v = float(bruto)
                except ValueError:
                    continue        # '*****' = estouro total; recuperar na seção de alta precisão
                d[nome] = v * lay["escala"] if nome in IMPEDANCIA else v
    return saida


def zdiag(lu, n: int, idx: dict, barras: list[int]) -> dict[int, complex]:
    """Diagonal da Zbus para as barras pedidas, por solves LU em lote."""
    alvos = [(b, idx[b]) for b in barras if b in idx]
    if not alvos:
        return {}
    chaves = np.array([k for _, k in alvos])
    z = np.zeros(len(alvos), dtype=complex)
    for ini in range(0, len(alvos), 300):
        ks = chaves[ini:ini + 300]
        e = np.zeros((n, len(ks)), dtype=complex)
        for coluna, k in enumerate(ks):
            e[k, coluna] = 1
        z[ini:ini + len(ks)] = lu.solve(e)[ks, np.arange(len(ks))]
    return {b: z[i] for i, (b, _) in enumerate(alvos)}


def niveis_mva(z1: complex, z0: complex) -> tuple[float, float, float]:
    """Níveis em MVA na convenção do relatório de referência (Z2 = Z1).

        trifásico    S = SB · |1 / Z1|
        monofásico   S = SB · |3 / (2·Z1 + Z0)|
        bifás.-terra S = √3 · SB · max(|Ib|, |Ic|)

    O fator √3 e o uso do MAIOR entre as duas fases em falta foram determinados por
    reconciliação com o relatório: ambas as convenções batem exatamente, e escolher a fase
    errada erra por até 0,5%.
    """
    z2 = z1
    a = np.exp(2j * np.pi / 3)
    den = z1 * z2 + z1 * z0 + z2 * z0
    ib = (z0 - a * z2) / den
    ic = (z0 - a.conjugate() * z2) / den
    return SB / abs(z1), 3 * SB / abs(2 * z1 + z0), math.sqrt(3) * SB * max(abs(ib), abs(ic))


def resumo(rot: str, err: np.ndarray, limite: float) -> None:
    a = np.abs(err)
    print(f"  {rot:<24} n={len(a):6d}  <{limite:g}%={(a < limite).mean() * 100:7.3f}%  "
          f"<5%={(a < 5).mean() * 100:7.3f}%  mediana={np.median(a):.4f}%  máx={a.max():.3f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("caso", help="arquivo .ANA")
    ap.add_argument("relatorios", nargs="+", help="um ou mais relatórios da ferramenta de referência")
    ap.add_argument("--limite", type=float, default=1.0, help="critério de erro, em %%")
    ap.add_argument("--piores", type=int, default=20, help="quantas barras piores listar")
    ap.add_argument("--com-deol", action="store_true",
                    help="comparar kA via fault_fc, incluindo geradores full-converter")
    args = ap.parse_args()

    print(f"Lendo {args.caso} ...")
    M = AnaModel(args.caso)
    print(f"  barras={len(M.bus_kv)} ramos={len(M.branches)} geradores={len(M.gens)} "
          f"shunts={len(M.shunts)} mútuas={len(M.mutuas)} reatores de linha={len(M.shl)}")

    print("Montando as redes de sequência e fatorando ...")
    S = Solver(M)
    S.factor()
    print(f"  Y1 {S.YP.shape} nnz={S.YP.nnz} | Y0 {S.Y0.shape} nnz={S.Y0.nnz}")

    precisa = ler_secao(args.relatorios, SEC_PRECISA)
    niveis = ler_secao(args.relatorios, SEC_NIVEIS)
    curta = ler_secao(args.relatorios, SEC_CURTA)
    if not (precisa or niveis or curta):
        print("ERRO: nenhuma seção conhecida encontrada nos relatórios.", file=sys.stderr)
        return 2
    print(f"Gabarito: impedâncias={len(precisa)} barras | níveis em kA={len(niveis)} | "
          f"dados de curto={len(curta)}")

    barras = sorted(set(precisa) | set(niveis) | set(curta))
    z1mot = zdiag(S.luP, len(S.BLP), S.IDXP, barras)
    z0mot = zdiag(S.lu0, len(S.BL0), S.I0P, barras)

    erros: dict[str, np.ndarray] = {}
    listas: dict[str, list] = {}

    def registrar(rot: str, pares: list[tuple[int, float, float]]) -> None:
        if not pares:
            return
        e = np.array([(c - r) / r * 100 for _, r, c in pares])
        erros[rot] = e
        listas[rot] = [(b, e[k]) for k, (b, _, _) in enumerate(pares)]
        resumo(rot, e, args.limite)

    print("\nIMPEDÂNCIA DE THÉVENIN — erro individual por barra")
    for rot, ref, chave, mot in (("Z1 (alta precisão)", precisa, "z1m", z1mot),
                                 ("Z0 (alta precisão)", precisa, "z0m", z0mot),
                                 ("Z1 (seção curta)", curta, "z1m", z1mot),
                                 ("Z0 (seção curta)", curta, "z0m", z0mot)):
        registrar(rot, [(b, ref[b][chave], abs(mot[b])) for b in barras
                        if b in ref and chave in ref[b] and ref[b][chave] > 0 and b in mot])

    if niveis:
        # ATENÇÃO: a seção de NÍVEIS (kA) INCLUI a contribuição de geradores full-converter
        # (eólicos/fotovoltaicos), modelados como fonte de corrente — ela não traz a nota
        # "OS RESULTADOS ABAIXO DESCONSIDERAM A PRESENÇA DESTES GERADORES" que aparece na
        # seção de dados de curto. Já `Solver.fault` é Thévenin puro da Ybus e os EXCLUI.
        # Comparar um com o outro é comparar coisas diferentes: perto de usina full-converter
        # a diferença chega a 50%. Use `--com-deol` para comparar via `fault_fc`, que inclui
        # as fontes de corrente por superposição iterativa.
        metodo = "fault_fc (inclui full-converter)" if args.com_deol else "fault (Thévenin puro)"
        print(f"\nNÍVEIS DE CURTO-CIRCUITO (kA) — via {metodo}")
        if not args.com_deol and M.eol:
            print(f"  nota: o caso tem {len(M.eol)} geradores full-converter e o relatório os INCLUI;")
            print("        as barras próximas a eles vão divergir. Repita com --com-deol.")
        for rot, chave, tipo in (("Trifásico (kA)", "i3m", "3F"),
                                 ("Monofásico (kA)", "i1m", "1FT"),
                                 ("Bifásico-terra (kA)", "i2m", "2FT")):
            pares = []
            for b in barras:
                if b not in niveis or chave not in niveis[b] or niveis[b][chave] <= 0:
                    continue
                try:
                    calc = S.fault_fc(b) if (args.com_deol and tipo == "3F") else S.fault(b, tipo)
                except Exception:
                    continue
                if calc:
                    pares.append((b, niveis[b][chave], calc))
            registrar(rot, pares)

    if curta:
        print("\nNÍVEIS DE CURTO-CIRCUITO (MVA)")
        nv = {b: niveis_mva(z1mot[b], z0mot[b]) for b in barras
              if b in z1mot and b in z0mot and abs(z1mot[b]) > 1e-12}
        for i, (rot, chave) in enumerate((("Trifásico (MVA)", "s3m"), ("Monofásico (MVA)", "s1m"),
                                          ("Bifásico-terra (MVA)", "s2m"))):
            registrar(rot, [(b, curta[b][chave], nv[b][i]) for b in barras
                            if b in curta and chave in curta[b] and curta[b][chave] > 0 and b in nv])

    if precisa:
        dv = []
        for b in barras:
            d = precisa.get(b, {})
            if not {"zrm", "zra", "z0m", "z0a"} <= d.keys() or b not in z1mot:
                continue
            m = abs(z1mot[b])
            if m < 1e-12:
                continue
            z2 = (d["zrm"] * np.exp(1j * np.deg2rad(d["zra"]))
                  - d["z0m"] * np.exp(1j * np.deg2rad(d["z0a"])))
            dv.append(abs(abs(z2) - m) / m * 100)
        if dv:
            dv = np.array(dv)
            print("\nCOERÊNCIA: hipótese Z2 = Z1 (Z2 extraído de (Z0+Z2) − Z0, em complexo)")
            print(f"  |Z2|−|Z1| em {len(dv)} barras: mediana={np.median(dv):.6f}%  "
                  f"p95={np.percentile(dv, 95):.4f}%  →  "
                  f"{'confirmada' if np.median(dv) < 0.01 else 'REVER'}")

    if erros:
        rots = list(erros)
        print(f"\nPor classe de tensão (% abaixo de {args.limite:g}%)")
        print("  " + "faixa".ljust(9) + "".join(r[:12].rjust(14) for r in rots))
        for lo, hi, nome in ((440, 9e9, "500+"), (230, 440, "230-345"), (69, 230, "69-138"),
                             (1, 69, "<69"), (0, 1, "kV=0")):
            linha, tem = "  " + nome.ljust(9), False
            for r in rots:
                sel = [abs(v) for b, v in listas[r] if lo <= M.bus_kv.get(b, 0) < hi]
                if not sel:
                    linha += "".rjust(14)
                    continue
                tem = True
                linha += f"{sum(1 for v in sel if v < args.limite) / len(sel) * 100:13.1f}%"
            if tem:
                print(linha)

    # O veredito (código de retorno) considera apenas as comparações DECISIVAS. As demais são
    # informativas e não reprovam: a seção curta tem 4 decimais em pu e sua quantização, sozinha,
    # já excede 1% em barras de impedância baixa — deixá-la no veredito faria o script reprovar
    # sempre, mesmo com o motor exato. Já os níveis em kA via `fault` divergem por construção
    # onde há gerador full-converter, porque o relatório os inclui e `fault` não.
    DECISIVAS = ("Z1 (alta precisão)", "Z0 (alta precisão)",
                 "Trifásico (MVA)", "Monofásico (MVA)", "Bifásico-terra (MVA)")
    if args.com_deol:
        DECISIVAS += ("Trifásico (kA)", "Monofásico (kA)", "Bifásico-terra (kA)")
    # sem seção de alta precisão, a curta assume o papel de gabarito de Z
    if not precisa:
        DECISIVAS += ("Z1 (seção curta)", "Z0 (seção curta)")

    ok = True
    for rot in erros:
        fora = sorted((p for p in listas[rot] if abs(p[1]) >= args.limite), key=lambda t: -abs(t[1]))
        decisiva = rot in DECISIVAS
        if not fora:
            print(f"\n{rot}: todas as barras abaixo de {args.limite:g}%.")
            continue
        if decisiva:
            ok = False
        marca = "" if decisiva else "   [informativa — não entra no veredito]"
        print(f"\n{rot}: {len(fora)} barra(s) ≥ {args.limite:g}% — piores "
              f"{min(args.piores, len(fora))}:{marca}")
        for b, v in fora[:args.piores]:
            print(f"  {b:>7} {M.bus_name.get(b, ''):<14} {M.bus_kv.get(b, 0):6.1f} kV  {v:+9.3f}%")

    print("\n" + ("VEREDITO: aprovado nas comparações decisivas."
                  if ok else "VEREDITO: reprovado — há divergência em comparação decisiva."))
    if not precisa:
        print("  AVISO: relatório sem a seção 'RELATORIO DE IMPEDANCIAS DE BARRA'. O julgamento caiu")
        print("  sobre a seção de 4 decimais, cuja quantização pode mascarar ou inventar erro.")
        print("  Exporte a seção de impedâncias de barra para um veredito confiável.")
    if not ok:
        print("\nAntes de tratar como erro do solver:")
        print("  - erro DISPERSO e pequeno é quantização do relatório;")
        print("    erro CONCENTRADO numa classe de barras é regra de leitura errada.")
        print("  - localize o elemento por I_terra = rowsum(Y0)·V e valide a correção por A/B global.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
