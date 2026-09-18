"""Motor de cálculos de proteção.

Constrói sobre o motor de curto-circuito (`solver`) as grandezas que um estudo de
proteção pede — envelopes por bay, corrente mínima de recomposição, e o que vier das
funções do Submódulo 2.11. Nada aqui altera o cálculo de curto: o solver é a fonte das
correntes, e este módulo as compõe e seleciona.

Separado do solver de propósito. O cálculo de curto-circuito é validado barra a barra
contra o ANAFAS e não deve mudar quando um critério de proteção mudar; manter os dois no
mesmo arquivo convida a isso.

    from lincc import envelope_contribuicoes, tabela_envelope, recomposicao_87b
"""
from __future__ import annotations

import numpy as np

from ._base import SB, zfin, zn3
from .solver import Solver, branches_at

def recomposicao_87b(model, bus, kinds=('3F','1FT')):
    """ICC_MIN de recomposicao para 87B: falta na barra energizada por UM elemento de cada vez.
    Para cada ramo (L ou perna 138 de banco de trafo) incidente na barra, isola a barra a esse
    unico elemento (dropa todos os demais incidentes) e calcula a falta. Retorna
    (tabela: [(rotulo,(bf,bt,nc),{kind:I_kA})], icc_min:{kind:I_kA}). Elementos que nao
    energizam a barra (Icc~0) aparecem na tabela e devem ser excluidos do ICC_MIN pelo analista."""
    inc=branches_at(model, bus)
    tab=[]; mins={k:float('inf') for k in kinds}
    for keep in inc:
        drop=[b for b in inc if b!=keep]
        S=Solver(model, drop_branches=drop); S.factor()
        vals={}
        for k in kinds:
            I=S.fault(bus, kind=k)
            vals[k]=I
            if I is not None and I>1e-3: mins[k]=min(mins[k], I)
        br=next(b for b in model.branches if (b['bf'],b['bt'],b['nc'])==keep)
        o=br['bt'] if br['bf']==bus else br['bf']
        rot=f"{br['tipo']} p/ {model.bus_name.get(o,'')[:12]}"
        tab.append((rot, keep, vals))
    return tab, mins



def envelope_contribuicoes(model, barra, tipos=('3F', '1FT', '2F', '2FT'),
                           vizinhanca=1, p_close_in=0.005, solver=None):
    """Envelope de correntes por bay, para ajuste de proteção de barra.

    Executa o conjunto de casos que um estudo de barra pede, sem que seja preciso
    enumerá-los a cada vez:

      * os quatro tipos de defeito: monofásico, trifásico, bifásico e bifásico-terra;
      * sistema completo e contingência simples (N-1) até `vizinhanca` barras;
      * as contingências sendo RETIRADA de equipamento e FALTA NA LINHA COM O TERMINAL
        OPOSTO ABERTO, que é a condição de abertura sequencial de disjuntor;
      * defeito na própria barra e defeito close-in dentro de cada equipamento.

    Devolve, POR BAY, a maior e a menor corrente do loop fase-fase e do loop de terra
    (3I0), com o cenário em que cada extremo ocorreu — que é o que alimenta a corrente
    mínima de operação e a de alarme.

    Estrutura devolvida:

        {bay: {'fase': {'max': (kA, cenario), 'min': (kA, cenario)},
               'terra': {'max': (kA, cenario), 'min': (kA, cenario)},
               'casos': [(cenario, tipo, I_fase_kA, I_3I0_kA), ...]}}

    O bay é identificado pela tupla (tipo, bf, bt, nc) do elemento incidente. O mínimo
    considera apenas cenários em que o bay está em serviço e a corrente é não nula: um
    bay retirado não define mínimo de sensibilidade.
    """
    S0 = solver or Solver(model)
    if not hasattr(S0, 'luP'):
        S0.factor(avisar=False)
    incid = [(br['tipo'], br['bf'], br['bt'], br['nc'])
             for br in model.branches if barra in (br['bf'], br['bt'])
             and (br['bf'], br['bt'], br['nc']) not in S0.dropB]
    if not incid:
        return {}

    # --- cenários: (rótulo, drop_branches, barra_em_falta, ramo_close_in) -------------
    cen = [('sistema completo', [], barra, None)]
    # close-in dentro de cada equipamento incidente
    for e in incid:
        cen.append((f'close-in em {e[0]} {e[1]}-{e[2]}/{e[3]}', [], barra, e))
    # N-1: retirada de cada elemento incidente e dos elementos das barras vizinhas
    alvos = set(incid)
    if vizinhanca >= 1:
        viz = {e[2] if e[1] == barra else e[1] for e in incid}
        for br in model.branches:
            if (br['bf'] in viz or br['bt'] in viz):
                alvos.add((br['tipo'], br['bf'], br['bt'], br['nc']))
    for e in sorted(alvos):
        if e in incid and len(incid) == 1:
            continue                      # não deixar a barra sem alimentação
        cen.append((f'N-1 sem {e[0]} {e[1]}-{e[2]}/{e[3]}', [(e[1], e[2], e[3])], barra, None))
    # falta na linha com o terminal oposto aberto
    for e in incid:
        if e[0] == 'L':
            cen.append((f'terminal oposto aberto em {e[1]}-{e[2]}/{e[3]}',
                        [(e[1], e[2], e[3])], barra, ('LEO',) + e[1:]))

    saida = {e: {'casos': []} for e in incid}
    cache = {}
    for rot, drop, fb, extra in cen:
        chave = tuple(sorted(drop))
        if chave not in cache:
            try:
                S = S0 if not drop else Solver(model, drop_branches=list(drop))
                if drop:
                    S.factor(avisar=False)
                cache[chave] = S
            except Exception:
                cache[chave] = None
        S = cache[chave]
        if S is None or fb not in S.IDXP:
            continue
        for tipo in tipos:
            try:
                prof = S._seq_profile(fb, tipo)
            except Exception:
                prof = None
            if prof is None:
                continue
            V0 = prof['V0']
            for e in incid:
                if (e[1], e[2], e[3]) in S.dropB:
                    continue
                try:
                    r = S.branch_current(fb, e[1], e[2], e[3], tipo)
                except Exception:
                    r = None
                if not r:
                    continue
                ifase = r['Imax']
                kvb = model.bus_kv.get(barra, 0)
                Ib = SB / (np.sqrt(3) * kvb) if kvb else 0
                br = S._find_branch(e[1], e[2], e[3])
                i3i0 = 0.0
                if V0 is not None and br is not None and Ib:
                    i3i0 = abs(3 * S.corrente_seq0_ramo(V0, br, barra)) * Ib
                saida[e]['casos'].append((f'{rot} · {tipo}', tipo, ifase, i3i0))

    for e, d in saida.items():
        for campo, idx in (('fase', 2), ('terra', 3)):
            vals = [(c[idx], c[0]) for c in d['casos'] if c[idx] > 1e-9]
            if not vals:
                d[campo] = {'max': (0.0, '—'), 'min': (0.0, '—')}
                continue
            d[campo] = {'max': max(vals), 'min': min(vals)}
    return saida


def tabela_envelope(env, model=None, largura=46):
    """Formata o resultado de `envelope_contribuicoes` como texto pronto para relatório."""
    linhas = []
    cab = f"{'BAY':<26} {'FASE máx':>10} {'FASE mín':>10} {'3I0 máx':>10} {'3I0 mín':>10}"
    linhas.append(cab)
    linhas.append('-' * len(cab))
    for e, d in env.items():
        nome = f"{e[0]} {e[1]}-{e[2]}/{e[3]}"
        linhas.append(f"{nome:<26} {d['fase']['max'][0]:10.3f} {d['fase']['min'][0]:10.3f} "
                      f"{d['terra']['max'][0]:10.3f} {d['terra']['min'][0]:10.3f}")
    linhas.append('')
    linhas.append('Cenário de cada extremo (kA primários):')
    for e, d in env.items():
        nome = f"{e[0]} {e[1]}-{e[2]}/{e[3]}"
        linhas.append(f"  {nome}")
        for campo, rot in (('fase', 'fase-fase'), ('terra', '3I0')):
            for extremo in ('max', 'min'):
                val, cen = d[campo][extremo]
                linhas.append(f"     {rot:<10} {extremo:>3}: {val:9.3f}   {cen[:largura]}")
    return '\n'.join(linhas)

