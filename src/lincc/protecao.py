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

def recomposicao_87b(model, bus, kinds=('3F','1FT'), modo='completo'):
    """ICC_MIN de recomposicao para 87B: falta na barra energizada por UM elemento de cada vez.
    Para cada ramo (L ou perna 138 de banco de trafo) incidente na barra, isola a barra a esse
    unico elemento (dropa todos os demais incidentes) e calcula a falta. Retorna
    (tabela: [(rotulo,(bf,bt,nc),{kind:I_kA})], icc_min:{kind:I_kA}). Elementos que nao
    energizam a barra (Icc~0) aparecem na tabela e devem ser excluidos do ICC_MIN pelo analista."""
    inc=branches_at(model, bus)
    tab=[]; mins={k:float('inf') for k in kinds}
    for keep in inc:
        drop=[b for b in inc if b!=keep]
        # Energização por um só elemento: o reator de barra também é um vão e sai. É a
        # hipótese de menor corrente, e a que reproduz o ANAFAS na recomposição.
        S=Solver(model, drop_branches=drop, modo=modo, drop_reatores_barra=[bus])
        S.factor(avisar=False)
        if modo=='completo' and getattr(model, '_leitura_conferida', None):
            S.validado_completo=True
            S._selo_completo=dict(model._leitura_conferida, conferido_no_caso=True)
        elif modo=='completo':
            # A recomposição monta dezenas de cenários; cada um é um Solver novo, e o
            # bloqueio do modo completo é por instância. Propaga-se a liberação, porque a
            # decisão de usar o modo completo foi tomada por quem chamou.
            S.liberar_completo_sem_gabarito('cenário interno de recomposição')
        vals={}
        for k in kinds:
            I=S.fault(bus, kind=k, modo=modo)
            vals[k]=I
            if I is not None and I>1e-3: mins[k]=min(mins[k], I)
        br=next(b for b in model.branches if (b['bf'],b['bt'],b['nc'])==keep)
        o=br['bt'] if br['bf']==bus else br['bf']
        rot=f"{br['tipo']} p/ {model.bus_name.get(o,'')[:12]}"
        tab.append((rot, keep, vals))
    return tab, mins



def envelope_contribuicoes(model, barra, tipos=('3F', '1FT', '2F', '2FT'),
                           vizinhanca=1, p_close_in=0.005, solver=None, modo=None):
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
    S0 = solver or Solver(model, modo=modo or 'completo')
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
            # a topologia real (linha pendurada) é montada a partir da rede de origem
            cen.append((f'terminal oposto aberto em {e[1]}-{e[2]}/{e[3]}',
                        [], barra, ('LEO',) + e[1:]))

    saida = {e: {'casos': []} for e in incid}
    cache = {}
    for rot, drop, fb, extra in cen:
        # retirada integral do equipamento (transformador leva todas as pernas)
        drop_eq = []
        for r in drop:
            drop_eq += _equipamento(model, r, barra)
        chave = tuple(sorted(set(drop_eq)))
        if chave not in cache:
            try:
                cache[chave] = S0 if not drop_eq else _solver(
                    model, list(chave), getattr(S0, 'modo', 'completo'))
            except Exception as ex:
                cache[chave] = None
                for e in incid:
                    saida[e].setdefault('falhas', []).append(f'{rot}: {type(ex).__name__}')
        S = cache[chave]
        if S is None:
            continue
        for tipo in tipos:
            if extra and extra[0] == 'LEO':
                # terminal oposto aberto: topologia real, só o vão da própria linha
                e = next((x for x in incid if (x[1], x[2], x[3]) == tuple(extra[1:])), None)
                br = S._find_branch(*extra[1:]) if e else None
                if br is None:
                    continue
                try:
                    S2, X, nova = S._solver_terminal_aberto(br, barra)
                    pontas = [('junto ao disjuntor',
                               S2.fault_on_branch(barra, X, nova['nc'], 1e-3, tipo)),
                              ('na ponta aberta',
                               S2.branch_current(X, barra, X, nova['nc'], tipo))]
                except Exception as ex:
                    saida[e].setdefault('falhas', []).append(f'{rot}, {tipo}: {type(ex).__name__}')
                    continue
                for onde, r in pontas:
                    if not r:
                        continue
                    if 'Imax' in r:
                        ifs, i3 = r['Imax'], r['I3I0']
                    else:
                        ifs, i3 = r.get('I_term_%d' % barra), r.get('3I0_term_%d' % barra)
                    if ifs:
                        saida[e]['casos'].append((f'{rot}, falta {onde} · {tipo}', tipo,
                                                  ifs, i3 or 0.0))
                continue
            if extra:
                # close-in dentro do equipamento: falta logo após o TC do vão
                e = extra
                try:
                    r = S.fault_on_branch(barra, e[2] if e[1] == barra else e[1], e[3], 1e-3, tipo)
                except Exception as ex:
                    saida[e].setdefault('falhas', []).append(f'{rot}, {tipo}: {type(ex).__name__}')
                    continue
                if r and r.get('I_term_%d' % barra):
                    saida[e]['casos'].append((f'{rot} · {tipo}', tipo, r['I_term_%d' % barra],
                                              r.get('3I0_term_%d' % barra) or 0.0))
                continue
            for e in incid:
                if set(_equipamento(model, (e[1], e[2], e[3]), barra)) & set(chave):
                    continue                                  # vão fora de serviço
                try:
                    r = S.branch_current(fb, e[1], e[2], e[3], tipo)
                except Exception as ex:
                    saida[e].setdefault('falhas', []).append(f'{rot}, {tipo}: {type(ex).__name__}')
                    continue
                if r:
                    saida[e]['casos'].append((f'{rot} · {tipo}', tipo, r['Imax'], r['I3I0']))

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



# ====================================================================== #
#  Funções de alto nível                                                 #
#                                                                        #
#  Encapsulam os estudos recorrentes para que o pedido possa ser curto:   #
#  o protocolo — quais tipos de defeito, quais contingências, o que       #
#  declarar, o que não estimar — fica AQUI, e não no prompt do usuário.   #
# ====================================================================== #

_KINDS = ('3F', '1FT', '2F', '2FT')


def _premissas_curto(S):
    """Premissas presentes em todo cálculo de curto-circuito desta instância."""
    sel = S.selo_completo() if hasattr(S, 'selo_completo') else {}
    p = ['tensão pré-falta de 1,0 pu em todas as barras, sem carregamento prévio',
         'correntes em kA primários (A primários nos ajustes)',
         'sequência negativa igual à positiva: o .ANA não traz reatância de sequência '
         'negativa das máquinas; grandezas de sequência negativa (46, 67Q) têm essa '
         'limitação e não são conferidas contra o ANAFAS']
    if S.modo == 'completo' and S._tem_fc():
        p.append('modo completo: inclui a contribuição dos geradores conectados por '
                 'conversor, conforme a curva do Submódulo 2.10')
        p.append('leitura do caso conferida contra o relatório do ANAFAS'
                 if sel.get('conferido_no_caso') else
                 'leitura do caso NÃO conferida contra o relatório do ANAFAS')
    else:
        p.append('modo síncronas: Thévenin sem a contribuição dos geradores de conversor')
    return p


def _solver(model, drop=None, modo='completo', manter_reatores=None,
            drop_reatores_barra=None, bypass_capacitores=None):
    # avisar=False: numa chamada de alto nível o aviso apareceria uma vez por cenário
    # interno — o relatório declara o modo no retorno, que é onde interessa.
    S = Solver(model, drop_branches=list(drop) if drop else None, modo=modo,
               manter_reatores=manter_reatores, drop_reatores_barra=drop_reatores_barra,
               bypass_capacitores=bypass_capacitores)
    S.factor(avisar=False)
    conf = getattr(model, '_leitura_conferida', None)
    if modo == 'completo' and conf:
        S.validado_completo = True
        S._selo_completo = dict(conf, conferido_no_caso=True)
        return S
    if modo == 'completo':
        S.liberar_completo_sem_gabarito('chamada de alto nível sem gabarito do caso')
    return S


def impacto_entrada(model, ramos, limiar=10.0, kinds=_KINDS, kv_min=69.0,
                    modo='completo', i_min_kA=0.1):
    """Impacto da entrada em operação de um equipamento na evolução de curto-circuito.

    `ramos` são os ramos do equipamento NOVO, como [(bf, bt, nc), ...]. Se o equipamento
    já está representado na base — o caso usual em horizonte de planejamento — o cenário
    "antes" é o contrafactual: os ramos são removidos. Um banco de três enrolamentos exige
    TODAS as pernas do nó-estrela na lista, senão o equipamento continua parcialmente
    conectado e o resultado não significa nada.

    Varre as barras de `kv_min` para cima nos quatro tipos de defeito e devolve as que
    variam `limiar` % ou mais, com o tipo que governou. Barras abaixo de `i_min_kA` são
    ignoradas: ali o percentual não tem significado físico.

    Devolve dict com 'barras' (lista ordenada pela maior variação), 'limiar', 'modo' e
    'n_avaliadas'. Cada barra traz: num, nome, kv, antes, depois, variacao_pct, kind.

    O gatilho de 10% é o usual para exigir revisão dos estudos de proteção existentes.
    """
    ramos = [(int(a), int(b), str(c)) for a, b, c in ramos]
    S_com = _solver(model, None, modo)
    S_sem = _solver(model, ramos, modo)
    alvo = [b for b, kv in model.bus_kv.items() if kv and kv >= kv_min]
    saida = []
    for b in alvo:
        pior = None
        for kind in kinds:
            try:
                a = S_sem.fault(b, kind, modo=modo)
                c = S_com.fault(b, kind, modo=modo)
            except Exception:
                continue
            if not a or not c or a < i_min_kA:
                continue
            d = (c - a) / a * 100.0
            if pior is None or abs(d) > abs(pior[0]):
                pior = (d, kind, a, c)
        if pior and abs(pior[0]) >= limiar:
            saida.append(dict(num=b, nome=model.bus_name.get(b, ''), kv=model.bus_kv[b],
                              antes=pior[2], depois=pior[3], variacao_pct=pior[0],
                              kind=pior[1]))
    saida.sort(key=lambda d: -abs(d['variacao_pct']))
    prem = _premissas_curto(S_com) + [
        'cenário "antes" obtido retirando o equipamento do caso (contrafactual)',
        f"tipos de defeito avaliados: {', '.join(kinds)}; reportado o que governou",
        f"barras de {kv_min:g} kV para cima; ignoradas as com corrente abaixo de "
        f"{i_min_kA:g} kA, onde o percentual não tem significado",
        f"gatilho de revisão: variação de {limiar:g}%",
        'rede completa do ANAFAS, sem despacho de cenário']
    return dict(barras=saida, limiar=limiar, modo=modo, n_avaliadas=len(alvo),
                ramos=ramos, premissas=prem)


def relatorio_curto(model, barra, kinds=_KINDS, modo='completo', solver=None):
    """Relatório de curto-circuito de uma barra: correntes, Thévenin e contribuições.

    Devolve dict com 'correntes' {kind: kA}, 'zth' (Z1, Z2, Z0 em pu), 'contribuicoes'
    {(tipo,bf,bt,nc): kA} e 'modo'. É o bloco básico sobre o qual os relatórios de
    proteção são montados.
    """
    S = solver or _solver(model, None, modo)
    out = dict(barra=barra, nome=model.bus_name.get(barra, ''),
               kv=model.bus_kv.get(barra), modo=modo, correntes={}, avisos=[])
    for kind in kinds:
        try:
            out['correntes'][kind] = S.fault(barra, kind, modo=modo)
        except Exception as e:
            out['avisos'].append(f"{kind}: {type(e).__name__} — {str(e)[:80]}")
    z = S.zth(barra)
    out['zth'] = dict(Z1=z[0], Z2=z[1], Z0=z[2]) if z and z[0] is not None else None
    try:
        out['contribuicoes'] = S.contribution(barra, '3F', modo=modo)
    except Exception:
        out['contribuicoes'] = {}
    out['premissas'] = _premissas_curto(S) + ['rede completa do ANAFAS, sem despacho de cenário']
    return out


def _ramos_incidentes(model, bus):
    """Ramos incidentes na barra como [(bf, bt, nc), ...], independente do formato que
    `branches_at` devolva."""
    out = []
    for x in branches_at(model, bus):
        if isinstance(x, dict):
            out.append((x['bf'], x['bt'], str(x['nc'])))
        else:
            t = tuple(x)
            # aceita (tipo,bf,bt,nc) ou (bf,bt,nc)
            if len(t) >= 4 and isinstance(t[0], str):
                out.append((t[1], t[2], str(t[3])))
            elif len(t) >= 3:
                out.append((t[0], t[1], str(t[2])))
    return out


def _equipamento(model, ramo, barra=None):
    """Ramos que compõem o EQUIPAMENTO do ramo dado: transformador de três enrolamentos é
    representado com nó fictício (tensão nula), e retirá-lo exige todas as pernas.
    Transformador de dois enrolamentos, linha e capacitor série são o próprio ramo."""
    a, b, c = ramo[0], ramo[1], str(ramo[2])
    for no in (a, b):
        if no != barra and not model.bus_kv.get(no):
            return [(x['bf'], x['bt'], str(x['nc'])) for x in model.branches
                    if no in (x['bf'], x['bt'])]
    return [(a, b, c)]


def _k0(br):
    """Fator de compensação de sequência zero: k0 = (Z0L − Z1L) / (3·Z1L)."""
    z1 = zfin(br.get('R1'), br.get('X1'))
    z0 = zfin(br.get('R0'), br.get('X0'))
    if z1 is None or z0 is None or abs(z1) < 1e-12:
        return None
    return (z0 - z1) / (3 * z1)


def relatorio_protecao(model, tipo, elemento, modo='completo', dados=None,
                       kinds=_KINDS, n1=True):
    """Relatório de proteção de um equipamento: linha, transformador, barra, reator ou
    capacitor série.

    `elemento` é (bf, bt, nc) para linha, transformador e capacitor; o número da barra
    para barra; e (barra, nc) ou a barra para reator. `dados` são os valores externos que
    o usuário já tem (relação de TC, placa, carga máxima); o que faltar é listado, não
    estimado.

    Monta, conforme o tipo:

      linha         correntes nos dois terminais, falta com terminal remoto aberto em
                    várias posições, Z1, Z0 e k0, e N-1 na barra local
      transformador passa-através por enrolamento, correntes nas barras dos dois lados —
                    o 50 precisa ser sensível na local e insensível na do outro lado
      barra         envelope por bay com o cenário de cada extremo e ICC_MIN de recomposição
      reator        correntes no ponto de conexão e falta intermediária no reator
      capacitor     correntes nos terminais, para avaliar sub e sobrealcance de distância

    Devolve dict com as grandezas, as funções que o Submódulo 2.11 exige para o tipo, e
    'dados_faltantes' — o que o .ANA não contém e o critério que cada um bloqueia.

    NÃO produz ajuste. Produz os insumos: o ajuste depende de critério, e critério é
    decisão de engenharia, declarada pelo usuário.
    """
    from .sm211 import funcoes_exigidas
    from .dados_externos import faltantes, RELATORIO
    S = _solver(model, None, modo)
    out = dict(tipo=tipo, elemento=elemento, modo=modo, grandezas={}, avisos=[])

    if tipo == 'barra':
        b = int(elemento if not isinstance(elemento, (tuple, list)) else elemento[0])
        out['grandezas']['curto_na_barra'] = relatorio_curto(model, b, kinds, modo, S)
        out['grandezas']['envelope_por_bay'] = envelope_contribuicoes(model, b, kinds,
                                                                      solver=S)
        try:
            tabela, icc_min = recomposicao_87b(model, b, modo=modo)
            out['grandezas']['recomposicao'] = dict(por_elemento=tabela, icc_min=icc_min)
        except Exception as e:
            out['avisos'].append(f"recomposição: {str(e)[:80]}")
        chave_dados = 'barra'

    elif tipo in ('linha', 'transformador', 'capacitor'):
        bf, bt, nc = (list(elemento) + ['1'])[:3]
        bf, bt, nc = int(bf), int(bt), str(nc)
        br = S._find_branch(bf, bt, nc)
        if br is None:
            raise ValueError(f"elemento {bf}-{bt}/{nc} não existe na base")
        out['grandezas']['Z1'] = zfin(br.get('R1'), br.get('X1'))
        out['grandezas']['Z0'] = zfin(br.get('R0'), br.get('X0'))
        out['grandezas']['k0'] = _k0(br)
        out['grandezas']['MVA_nominal'] = br.get('MVA')
        for rot, b in (('terminal_local', bf), ('terminal_remoto', bt)):
            out['grandezas'][f'curto_{rot}'] = relatorio_curto(model, b, kinds, modo, S)
        if tipo == 'linha':
            try:
                out['grandezas']['terminal_remoto_aberto'] = \
                    S.varredura_line_end_open(bf, bt, nc, bf, kinds)
            except Exception as e:
                out['avisos'].append(f"terminal aberto: {str(e)[:80]}")
        if tipo == 'transformador':
            for rot, b in (('local', bf), ('outro_lado', bt)):
                try:
                    out['grandezas'][f'passa_atraves_{rot}'] = \
                        S.contribution(b, '3F', modo=modo).get(
                            (br['tipo'], bf, bt, nc))
                except Exception:
                    pass
        if n1:
            viz = [r for r in _ramos_incidentes(model, bf) if r != (bf, bt, nc)]
            n1_out = {}
            for r in viz:
                try:
                    Sn = _solver(model, [r], modo)
                    n1_out[f"sem {r[0]}-{r[1]}/{r[2]}"] = {
                        k: Sn.fault(bf, k, modo=modo) for k in kinds}
                except Exception:
                    continue
            out['grandezas']['n_1_no_terminal_local'] = n1_out
        chave_dados = {'linha': 'linha', 'transformador': 'transformador',
                       'capacitor': 'linha'}[tipo]

    elif tipo == 'reator':
        b = int(elemento[0] if isinstance(elemento, (tuple, list)) else elemento)
        out['grandezas']['curto_no_ponto_de_conexao'] = relatorio_curto(model, b, kinds,
                                                                        modo, S)
        interm = {}
        for frac in (0.1, 0.25, 0.5, 0.75, 0.9):
            try:
                interm[frac] = S.fault_on_shunt(b, frac, '1FT')
            except Exception:
                continue
        if interm:
            out['grandezas']['falta_intermediaria_no_reator'] = interm
        chave_dados = 'reator'
    else:
        raise ValueError("tipo deve ser linha, transformador, barra, reator ou capacitor")

    out['funcoes_sm211'] = funcoes_exigidas(
        tipo if tipo in ('linha', 'transformador', 'reator', 'barra') else 'linha')
    falta = faltantes(chave_dados, dados,
                      model=model if tipo != 'barra' and tipo != 'reator' else None,
                      elemento=(int(elemento[0]), int(elemento[1]), str(elemento[2]))
                      if tipo in ('linha', 'transformador', 'capacitor') else None)
    out['dados_faltantes'] = falta
    out['dados_faltantes_texto'] = RELATORIO(falta, tipo)
    prem = _premissas_curto(S) + ['rede completa do ANAFAS, sem despacho de cenário']
    if n1 and tipo in ('linha', 'transformador', 'capacitor'):
        prem.append('contingência N-1: retirada de cada elemento incidente no terminal local')
    if tipo == 'barra':
        prem.append('recomposição: barra energizada por um só elemento de cada vez, com as '
                    'demais conexões e o reator de barra desligados')
        prem.append('envelope por vão: quatro tipos de defeito, rede completa e N-1 até uma '
                    'barra vizinha, retirada de equipamento e terminal remoto aberto')
    if tipo == 'linha':
        prem.append('terminal remoto aberto: para posições intermediárias, o efeito dos '
                    'conversores é aplicado pela razão medida no terminal')
    prem.append('funções exigidas conforme o Submódulo 2.11; critérios de ajuste não '
                'aplicados — o relatório traz insumos, não ajustes')
    out['premissas'] = prem
    return out


# ====================================================================== #
#  Sobrecorrente                                                         #
# ====================================================================== #

# Critérios padrão. Todos parametrizáveis: são convenção de filosofia de proteção, e o
# usuário pode ter os seus. Nenhum vem do Submódulo 2.11, que não define ajuste.
CRITERIOS_SOBRECORRENTE = {
    'linha': dict(
        f51_carga=1.20,        # pickup do 51: 120% da carga de EMERGÊNCIA da LT
        t_z2=0.40,             # tempo da zona 2, s — o 51 deve ser igual ou mais lento
        f50_margem=1.20,       # 50 só se o pickup superar a falta na barra remota nisso
        sotf_frac_min=0.80,    # SOTF abaixo de 80% do Icc mínimo remoto
        stub_frac=0.50,        # STUB até 50% do Icc da barra
        f67nt_min_in_tc=0.10,  # 67NT: no mínimo 10% de In do TC
        f67nt_max_1f=0.70,     # 67NT: no máximo 70% da monofásica remota
    ),
    'transformador': dict(
        f51_nominal=None,      # pickup do 51: sem padrão universal — informar o critério
                               # (ex.: {'f51_nominal': 1.5}); sem ele, dados_faltantes
        f50_margem=1.20,       # 50 acima do passa-através e do inrush com essa margem
    ),
    # 51V — comum a linha e transformador
    '51V': dict(
        v_partida=0.80,        # tensão de partida, pu da fase-fase nominal
        margem_k=1.20,         # k·I> ≤ falta remota mínima / margem (guia MiCOM P14x)
    ),
}


def _avaliar_51v(S, bus_rele, pickup51, faltas, crit51v, prem):
    """Verifica a necessidade da 51V e calcula o fator de redução.

    `faltas`: [(corrente_A, barra_em_falta, tipo), ...] para as faltas remotas que o 51
    deve enxergar. A 51V é necessária quando a menor delas fica abaixo do pickup do 51 —
    a impedância do equipamento limita a corrente de falta a níveis de carga, e só a
    tensão distingue as duas situações.

    Ajuste, conforme os guias de aplicação (Siemens 7SR, MiCOM P14x, Relion PHPVOC/
    VRPVOC, SEL): o pickup normal permanece acima da carga; abaixo da tensão de partida
    ele é reduzido pelo fator k, com k·I> abaixo da falta remota mínima com margem. A
    tensão no relé durante essa falta precisa ficar abaixo da tensão de partida — senão a
    51V não se sensibiliza e a proteção fica sem cobertura.
    """
    faltas = [f for f in faltas if f[0]]
    if not pickup51 or not faltas:
        return None
    imin, fbus, fk = min(faltas)
    out = dict(necessaria=imin < pickup51, i_falta_remota_min=imin,
               condicao=f'falta {fk} na barra {fbus}', pickup_51=pickup51)
    if not out['necessaria']:
        out['conclusao'] = '51 enxerga a falta remota mínima; 51V dispensável'
        return out
    k = imin / (crit51v['margem_k'] * pickup51)
    try:
        v = S.bus_voltage(fbus, bus_rele, fk)
        vrele = v['Vff_min'] if v else None
    except Exception:
        vrele = None
    out.update(v_partida=crit51v['v_partida'], k=k, pickup_51V=k * pickup51,
               v_rele_na_falta=vrele, alertas=[])
    if vrele is None:
        out['alertas'].append('tensão no relé durante a falta não calculada')
    elif vrele >= crit51v['v_partida']:
        out['alertas'].append(
            f'tensão no relé na falta remota mínima ({vrele:.3f} pu) não cai abaixo da '
            f'partida ({crit51v["v_partida"]:.2f} pu): a 51V não se sensibiliza')
    if k < 0.1:
        out['alertas'].append(f'fator k = {k:.2f} abaixo da faixa usual dos relés')
    # Os dois princípios são objetos distintos (L09): no CONTROLE, a tensão habilita um
    # pickup reduzido fixo; na RESTRIÇÃO, o pickup varia continuamente com a tensão. Aqui a
    # restrição usa a forma linear genérica pickup(V) = I>·max(k, V/Vs); a curva real de
    # cada IED vem do perfil do fabricante.
    vs = crit51v['v_partida']
    out['controle'] = dict(
        habilita=(vrele is not None and vrele < vs), pickup=k * pickup51,
        margem=(imin / (k * pickup51)) if (vrele is not None and vrele < vs) else None)
    if vrele is not None:
        pk_r = pickup51 * max(k, min(1.0, vrele / vs))
        out['restricao'] = dict(pickup_na_tensao=pk_r, margem=imin / pk_r,
                                opera=imin > pk_r, forma='linear genérica')
        if imin <= pk_r:
            out['alertas'].append(f'na restrição, o pickup na tensão da falta ({pk_r:.0f} A) '
                                  f'fica acima da falta remota mínima ({imin:.0f} A)')
    prem.append(f"51V: necessária quando a falta remota mínima fica abaixo do pickup do 51; "
                f"partida em {crit51v['v_partida']:.2f} pu da tensão fase-fase; pickup "
                f"reduzido por k com k·I> ≤ falta remota mínima / {crit51v['margem_k']:.1f}; "
                f"bloqueio por falha de fusível do TP; tensão no relé verificada no modo do "
                f"estudo")
    return out



CAMPOS_EVIDENCIA = ('fonte', 'secao', 'revisao', 'base', 'unidade', 'resolucao',
                    'classe_evidencia')


def politica_exportacao(resultado, perfil_ied=None):
    """Decide se um resultado de ajuste pode ser exportado como ajuste de IED.

    Exportar exige: perfil do IED com cada regra documentada (fonte, seção, revisão, base,
    unidade, resolução, classe de evidência) e toda função em calculavel_verificada. Um
    exemplo de manual não vira requisito. Sem isso, o resultado serve como INSUMO de
    estudo, não como ajuste a transferir para o relé.
    """
    motivos = []
    if not perfil_ied:
        motivos.append('perfil de IED não informado')
    else:
        for par, regra in (perfil_ied.get('regras') or {}).items():
            falta = [c for c in CAMPOS_EVIDENCIA if not regra.get(c)]
            if falta:
                motivos.append(f'regra {par} sem ' + ', '.join(falta))
            if regra.get('classe_evidencia') == 'exemplo':
                motivos.append(f'regra {par} tem classe "exemplo": não vira requisito')
    for nome, f in (resultado.get('funcoes') or {}).items():
        itens = f.values() if isinstance(f, dict) and 'estado' not in f else [f]
        for x in itens:
            if isinstance(x, dict) and x.get('estado') not in (None, 'calculavel_verificada'):
                motivos.append(f'{nome}: {x.get("estado")}')
    return dict(exportavel=not motivos, motivos=motivos)


ESTADOS = ('calculavel_verificada', 'faixa_inviavel', 'dados_faltantes',
           'modelo_nao_suportado', 'validacao_pendente', 'erro_execucao')


def _estado(f, conferido=True):
    """Estado explícito de um resultado de ajuste. Resultado incompleto nunca aparece
    como faixa aprovada."""
    if f.get('erro'):
        return 'erro_execucao'
    if f.get('viavel') is False or f.get('necessaria') and f.get('alertas') and any(
            'não se sensibiliza' in a for a in f['alertas']):
        return 'faixa_inviavel'
    if f.get('pickup') is None and f.get('min') is None and f.get('max') is None:
        return 'dados_faltantes'
    if f.get('viavel') is None and ('min' in f or 'max' in f) and (
            f.get('min') is None or f.get('max') is None):
        return 'dados_faltantes'
    return 'calculavel_verificada' if conferido else 'validacao_pendente'


def quantizar(valor, faixa, passo, sentido='baixo'):
    """Arredonda um ajuste ao passo do relé sem sair da faixa admissível.

    `sentido`='baixo' arredonda para baixo (ajustes limitados por sensibilidade), 'cima'
    para cima (limitados por segurança). Se o valor arredondado sair da faixa, tenta o
    outro sentido; se nenhum couber, devolve None — a faixa não comporta o passo do relé.
    """
    import math
    if valor is None or not passo:
        return valor
    lo, hi = faixa if faixa else (None, None)
    f = math.floor if sentido == 'baixo' else math.ceil
    g = math.ceil if sentido == 'baixo' else math.floor
    for fn in (f, g):
        q = fn(valor / passo) * passo
        if (lo is None or q >= lo - 1e-9) and (hi is None or q <= hi + 1e-9):
            return q
    return None


def _faixa(minimo, maximo):
    """Faixa admissível. Viável se o limite inferior não exceder o superior."""
    if minimo is None or maximo is None:
        return dict(min=minimo, max=maximo, viavel=None)
    return dict(min=minimo, max=maximo, viavel=minimo <= maximo)


def ajuste_sobrecorrente(model, tipo, elemento, dados=None, criterios=None,
                         modo='completo', curva='MI', norma='IEC', cenarios=None,
                         perfil_ied=None):
    """Faixas admissíveis e viabilidade das funções de sobrecorrente de um equipamento.

    NÃO escolhe o ajuste. Para cada função devolve a faixa que os critérios admitem, se ela
    é viável, qual limite governa, e o que falta para fechá-la. Escolher dentro da faixa é
    decisão de engenharia.

    `tipo`: 'linha' ou 'transformador'. `elemento`: (bf, bt, nc), com `bf` o terminal do
    relé. `dados`: valores externos em A — carga_max_lt, in_tc, inrush, in_nominal. O que
    faltar é reportado, não estimado; a corrente nominal é lida da base quando o campo MVA
    está preenchido.

    `cenarios`: {nome: PwfModel} com as bases do ANAREDE. Quando fornecido, a carga
    máxima da linha sai da capacidade de emergência declarada lá, em vez de ser pedida ao
    usuário — e a origem fica registrada no retorno.

    Linha: 51 (pickup e tempo coordenado com a zona 2), 50 (só se seletivo para falta na
    barra remota), SOTF, STUB e 67NT. Transformador: 51 e 50 (acima do inrush e do
    passa-através para falta na barra do outro lado, abaixo da falta na barra local).

    Toda corrente em A primários.
    """
    from .dados_externos import da_base
    from . import curvas as _curvas
    dados = dict(dados or {})
    crit = dict(CRITERIOS_SOBRECORRENTE.get(tipo, {}))
    crit.update(criterios or {})
    bf, bt, nc = int(elemento[0]), int(elemento[1]), str(elemento[2])
    informados = {k for k, v in dados.items() if v not in (None, '')}
    da_caso = set()
    for k, v in da_base(model, bf, bt, nc).items():
        if k not in dados or dados[k] in (None, ''):
            dados[k] = v
            da_caso.add(k)
    origem_carga = 'informada pelo usuário' if dados.get('carga_max_lt') else None
    if cenarios and tipo == 'linha' and dados.get('carga_max_lt') in (None, ''):
        from .fluxo import carga_maxima
        cm = carga_maxima(cenarios, bf, bt, nc)
        if cm and cm.get('carga_max_A'):
            dados['carga_max_lt'] = cm['carga_max_A']
            origem_carga = 'ANAREDE, ' + cm['origem']
    S = _solver(model, None, modo)
    kA = lambda x: x * 1000.0 if x is not None else None
    out = dict(tipo=tipo, elemento=(bf, bt, nc), modo=modo, curva=_curvas.descreve(curva, norma),
               criterios=crit, funcoes={}, faltantes=[], origem_carga_max=origem_carga)
    prem = _premissas_curto(S)
    prem.append(f"curva de tempo inverso: {_curvas.descreve(curva, norma)}")
    if origem_carga:
        prem.append(f"carga máxima da linha: {origem_carga}")
    if da_caso & {'in_nominal', 'in_lt'}:
        prem.append('corrente nominal obtida do campo MVA do caso .ANA')
    if informados:
        prem.append('dados informados pelo usuário: ' + ', '.join(sorted(informados)))
    out['premissas'] = prem

    def falta(k):
        if dados.get(k) in (None, ''):
            if k not in out['faltantes']:
                out['faltantes'].append(k)
            return True
        return False

    if tipo == 'linha':
        # correntes vistas pelo TC do terminal bf
        def i_ramo(fbus, kind):
            r = S.branch_current(fbus, bf, bt, nc, kind)
            return kA(r['Imax']) if r else None
        i_barra_remota = {k: i_ramo(bt, k) for k in ('3F', '1FT', '2F')}
        r1f = S.branch_current(bt, bf, bt, nc, '1FT')
        i3i0_remota = kA(r1f['I3I0']) if r1f else None      # 3I0 no TC, não a corrente de fase
        i_barra_local = {k: kA(S.fault(bf, k)) for k in ('3F', '1FT')}
        i_leo = {k: kA(S.line_end_open(bf, bt, nc, bf, k, p=1.0)) for k in ('3F', '2F', '1FT')}

        # --- 51: pickup pela carga, tempo pelo defeito mais severo ---
        pk = None if falta('carga_max_lt') else crit['f51_carga'] * float(dados['carga_max_lt'])
        severo = max(v for v in list(i_barra_remota.values()) + list(i_leo.values()) if v)
        f51 = dict(pickup=pk, criterio=f"{crit['f51_carga']:.0%} da carga máxima",
                   i_defeito_mais_severo=severo)
        prem.append(f"51 de linha: pickup em {crit['f51_carga']:.0%} da carga de emergência; "
                    f"tempo de {crit['t_z2']*1000:.0f} ms (zona 2) no defeito mais severo, "
                    f"entre falta na barra remota e terminal remoto aberto")
        prem.append(f"50 de linha: habilitado só se o pickup superar em "
                    f"{crit['f50_margem']-1:.0%} a falta na barra remota")
        prem.append(f"SOTF: acima da carga de emergência e abaixo de "
                    f"{crit['sotf_frac_min']:.0%} do curto mínimo remoto; STUB até "
                    f"{crit['stub_frac']:.0%} do curto da barra; 67NT entre "
                    f"{crit['f67nt_min_in_tc']:.0%} de In do TC e "
                    f"{crit['f67nt_max_1f']:.0%} da 3I0 no TC para monofásica remota")
        if pk:
            try:
                f51['tms_minimo'] = _curvas.tms_para_tempo(severo, pk, crit['t_z2'], curva, norma)
                f51['tempo_no_defeito'] = crit['t_z2']
            except ValueError as e:
                f51['aviso'] = str(e)
        out['funcoes']['51'] = f51
        c51v = dict(CRITERIOS_SOBRECORRENTE['51V']); c51v.update(
            {k[4:]: v for k, v in (criterios or {}).items() if k.startswith('51V_')})
        faltas = [(i_barra_remota.get(k), bt, k) for k in ('3F', '2F')]
        faltas += [(i_leo.get(k), bt, k) for k in ('3F', '2F')]
        r51v = _avaliar_51v(S, bf, pk, faltas, c51v, prem)
        if r51v:
            out['funcoes']['51V'] = r51v

        # --- 50: só se seletivo para falta na barra remota ---
        i_remota_max = max(v for v in i_barra_remota.values() if v)
        # teto do 50: falta close-in na própria linha, com a corrente que o TC realmente vê
        # (a contribuição do terminal remoto não passa por ele)
        try:
            ci = S.fault_on_branch(bf, bt, nc, 1e-3, '3F')
            i_local = kA(ci.get('I_term_%d' % bf)) if ci else None
        except Exception:
            i_local = None
        i_local = i_local or i_barra_local['3F']
        piso = crit['f50_margem'] * i_remota_max
        f50 = _faixa(piso, i_local)
        f50.update(criterio=f"acima de {crit['f50_margem']:.0%} da falta na barra remota",
                   i_barra_remota=i_remota_max, i_barra_local=i_local)
        if f50['viavel'] is False:
            f50['conclusao'] = 'não habilitar: sem seletividade para falta na barra remota'
        out['funcoes']['50'] = f50

        # --- SOTF: acima da carga de emergência, abaixo de 80% do mínimo remoto ---
        # O piso é a carga máxima (emergência): a função não pode atuar com a linha
        # energizada e carregada no limite de emergência. Sem ela, usa-se a nominal e o
        # retorno registra que o piso é provisório.
        i_min_remoto = min(v for v in (i_barra_remota['2F'], i_barra_remota['1FT']) if v)
        teto = crit['sotf_frac_min'] * i_min_remoto
        if dados.get('carga_max_lt') not in (None, ''):
            piso, base_piso = float(dados['carga_max_lt']), 'carga de emergência'
        elif not falta('in_lt'):
            piso, base_piso = float(dados['in_lt']), 'corrente nominal (provisório)'
        else:
            piso, base_piso = None, None
        fs = _faixa(piso, teto)
        fs.update(criterio=f"acima da carga de emergência e abaixo de "
                           f"{crit['sotf_frac_min']:.0%} do mínimo remoto (bifásica ou "
                           f"monofásica)",
                  i_min_remoto=i_min_remoto, base_do_piso=base_piso)
        if fs['viavel'] is False:
            fs['conclusao'] = ('faixa vazia: a carga supera o limite superior — '
                               'avaliar unidade 51V')
        out['funcoes']['SOTF'] = fs

        # --- STUB: até 50% do Icc da barra ---
        out['funcoes']['STUB'] = dict(max=crit['stub_frac'] * i_local,
                                      criterio=f"até {crit['stub_frac']:.0%} do Icc da barra",
                                      i_barra=i_local)

        # --- 67NT: entre 10% de In do TC e 70% da monofásica remota ---
        teto = crit['f67nt_max_1f'] * i3i0_remota if i3i0_remota else None
        piso = None if falta('in_tc') else crit['f67nt_min_in_tc'] * float(dados['in_tc'])
        f67 = _faixa(piso, teto)
        f67.update(criterio=f"entre {crit['f67nt_min_in_tc']:.0%} de In do TC e "
                            f"{crit['f67nt_max_1f']:.0%} da monofásica remota",
                   usual=piso, i_3i0_remota=i3i0_remota, curva='muito inversa')
        out['funcoes']['67NT'] = f67

    elif tipo == 'transformador':
        # --- 51: 150% da nominal ---
        inom = dados.get('in_nominal')
        if inom in (None, ''):
            falta('in_nominal')
        if cenarios and 'in_nominal' in da_caso:
            from .fluxo import carga_maxima
            cm = carga_maxima(cenarios, bf, bt, nc)
            if cm and cm.get('cap_normal_A'):
                inom = cm['cap_normal_A']
                prem.append('corrente nominal do transformador: capacidade normal declarada '
                            'no ANAREDE')
        f51n = crit.get('f51_nominal')
        if not f51n and 'criterio_51_transformador' not in out['faltantes']:
            out['faltantes'].append('criterio_51_transformador')
        out['funcoes']['51'] = dict(
            pickup=f51n * float(inom) if (inom and f51n) else None,
            criterio=(f"{f51n:.0%} da nominal" if f51n else
                      'critério não definido: o múltiplo da nominal depende da filosofia e '
                      'do perfil de carga do transformador'))
        if f51n:
            prem.append(f"51 de transformador: pickup em {f51n:.0%} da corrente NOMINAL, "
                        f"critério informado; não referido à capacidade de emergência")
        prem.append(f"50 de transformador: acima de {crit['f50_margem']:.0%} do maior entre "
                    f"o passa-através para falta na barra do outro lado e o inrush, e "
                    f"abaixo da falta na barra local; banco de três enrolamentos com a "
                    f"barra do outro lado localizada pelo nó-estrela")
        # --- 50: faixa entre passa-através/inrush e falta local ---
        # Em banco de três enrolamentos o `bt` do elemento é o nó-estrela fictício
        # (kV = 0), não uma barra física. A "barra do outro lado" é a do enrolamento de
        # maior tensão entre as demais pernas do mesmo nó — é nela que a falta passante
        # deve ser aplicada, com a corrente medida no ramo do terminal do relé.
        outro = bt
        if not model.bus_kv.get(bt):
            pernas = [(x['bt'] if x['bf'] == bt else x['bf']) for x in model.branches
                      if x['tipo'] == 'T' and bt in (x['bf'], x['bt'])]
            pernas = [b for b in pernas if b != bf and model.bus_kv.get(b)]
            if pernas:
                outro = max(pernas, key=lambda b: model.bus_kv.get(b, 0))
        out['barra_outro_lado'] = outro
        pk51 = out['funcoes']['51']['pickup']
        c51v = dict(CRITERIOS_SOBRECORRENTE['51V']); c51v.update(
            {k[4:]: v for k, v in (criterios or {}).items() if k.startswith('51V_')})
        faltas = []
        for k in ('3F', '2F'):
            try:
                r = S.branch_current(outro, bf, bt, nc, k)
                faltas.append((kA(r['Imax']) if r else None, outro, k))
            except Exception:
                pass
        r51v = _avaliar_51v(S, bf, pk51, faltas, c51v, prem)
        if r51v:
            out['funcoes']['51V'] = r51v
        try:
            r = S.branch_current(outro, bf, bt, nc, '3F')
            passa = r['Imax'] if r else None
        except Exception:
            passa = None
        passa = kA(passa)
        # teto do 50 do transformador: falta nos terminais do próprio transformador, com a
        # corrente vista pelo TC do lado do relé
        try:
            ci = S.fault_on_branch(bf, bt, nc, 1e-3, '3F')
            i_local = kA(ci.get('I_term_%d' % bf)) if ci else None
        except Exception:
            i_local = None
        i_local = i_local or kA(S.fault(bf, '3F'))
        base = [x for x in (passa, None if falta('inrush') else float(dados['inrush'])) if x]
        piso = crit['f50_margem'] * max(base) if base else None
        f50 = _faixa(piso, i_local)
        f50.update(criterio=f"acima de {crit['f50_margem']:.0%} do passa-através e do inrush, "
                            f"abaixo da falta na barra local",
                   i_passante_barra_outro_lado=passa, i_barra_local=i_local)
        if f50['viavel'] is False:
            f50['conclusao'] = 'faixa vazia: 50 não é seletivo'
        out['funcoes']['50'] = f50
    else:
        raise ValueError("tipo deve ser 'linha' ou 'transformador'")
    conferido = bool(S.selo_completo().get('conferido_no_caso')) or not (
        S.modo == 'completo' and S._tem_fc())
    for f in out['funcoes'].values():
        if isinstance(f, dict):
            f['estado'] = _estado(f, conferido)
    out['exportacao'] = politica_exportacao(out, perfil_ied)
    return out


# ====================================================================== #
#  Estudo de proteção de barra: 87B, checkzone, alarme, 50BF e EFP       #
# ====================================================================== #

CRITERIOS_BARRA = dict(
    f_icc=0.67,          # ajuste sugerido: 67% do curto mínimo (relação de sensibilidade 1,5)
    f_checkzone=None,    # checkzone: sem escala fixa — faixa própria; informar se desejado
    f_alarme=None,       # alarme: sem escala fixa — faixa pela menor carga REAL dos vãos
    piso_in_tc=0.05,     # todo pickup acima de 5% de In do TC de referência
    f_icc_max=0.80,      # teto: pickup abaixo de 80% da menor falta (guia REB670)
    faixa_tc=(0.5, 1.5), # faixa típica do pickup: 50% a 150% de In do maior TC (guia REB670)
)

# Slope da diferencial de barra: parâmetro do IED, não do estudo. Cada fabricante define a
# corrente de restrição e a característica de forma própria, e o mesmo percentual produz
# curvas diferentes — por isso o LINCC informa a referência de cada um em vez de calcular.
SLOPE_87B_POR_FABRICANTE = {
    'SEL-487B': 'SLP1 60% (carga e falta interna) e SLP2 80% (modo de alta segurança, '
                'comutado pela detecção de falta externa) — valores padrão do manual',
    'Siemens 7SS85': 'fator de estabilização k ajustável de 0,10 a 0,80; limiar Idiff de '
                     '0,20 a 4,00 × corrente nominal do objeto',
    'ABB/Hitachi REB670': 'slope fixo em 53% no algoritmo; só o nível de operação é ajustado',
    'GE MiCOM P74x': 'não verificado nesta revisão',
}


def estudo_barra(model, barra, dados=None, cenarios=None, criterios=None,
                 modo='completo', kinds=_KINDS, perfil_ied=None):
    """Estudo de proteção de uma barra: 87B, checkzone, alarme diferencial, 50BF e EFP.

    Resolve o estudo inteiro a partir do pedido "proteção da barra X". Tudo em A primários.

    Corrente mínima de curto na barra: o menor valor entre rede completa, N-1 de cada
    equipamento incidente (transformador com todas as pernas) e do reator de barra,
    recomposição por cada alimentação isolada (com o reator de barra desligado) e, com os
    casos do ANAREDE, o menor cenário de despacho — incluindo a recomposição nesse
    cenário. Não se usa a condição com apenas o reator de barra conectado.

    Cargas por vão: capacidade de emergência e nominal do ANAREDE; sem ele, a potência
    nominal do .ANA, declarada como provisória.

    Critérios (padrão em CRITERIOS_BARRA, todos declarados em `premissas`):

      87B        carga de emergência < pickup < curto mínimo; sugerido 67% do curto
                 mínimo. Se a faixa não existir, prevalece o curto.
      checkzone  80% do pickup do 87B.
      alarme     15% do pickup do 87B, abaixo da menor carga nominal dos vãos — para
                 detectar TC aberto sem disparo, que o pickup acima da carga garante.
      50BF       carga nominal do vão < pickup < falta na extremidade oposta da linha com
                 o terminal remoto aberto, com a alimentação local mais fraca.
      EFP        pickup < falta junto ao disjuntor aberto, nas duas posições de TC; sem
                 piso de carga, porque com o disjuntor aberto só circula corrente de falta.
      todas      pickup >= 5% de In do TC de referência (maior relação da zona), quando
                 `dados['in_tc_ref']` é informado, ou o ajuste mínimo do relé, se maior.

    Slope: valores de partida declarados, não calculados — dependem da definição de
    restrição do IED e do estudo de saturação.

    O estudo fatora uma topologia por condição (N-1, recomposição, cada par de linha e
    alimentação fraca) e leva alguns minutos numa base do SIN.
    """
    from .dados_externos import da_base
    from .sm211 import funcoes_exigidas
    crit = dict(CRITERIOS_BARRA); crit.update(criterios or {})
    dados = dict(dados or {})
    kv = model.bus_kv.get(barra)
    Ib = SB / (np.sqrt(3) * kv)
    inc = _ramos_incidentes(model, barra)
    kinds = tuple(kinds)

    def outro(r):
        return r[1] if r[0] == barra else r[0]

    def e_trafo(r):
        return not model.bus_kv.get(outro(r))

    def equipamento(r):
        return _equipamento(model, r, barra)

    def nome(r):
        return f"{'T' if e_trafo(r) else 'L'} {r[0]}-{r[1]}/{r[2]}"

    S0 = _solver(model, None, modo)
    prem = _premissas_curto(S0)
    cand = []          # (corrente_A, condição)

    I_DESENERGIZADA = 1.0     # A — abaixo disso a condição deixa a barra sem alimentação

    def curto_barra(S, rot):
        for k in kinds:
            try:
                v = S.fault(barra, k) * 1000.0
            except Exception:
                continue
            if v > I_DESENERGIZADA:
                cand.append((v, f'{rot}, {k}'))

    # --- corrente mínima na barra ---
    curto_barra(S0, 'rede completa')
    for r in inc:
        try:
            curto_barra(_solver(model, equipamento(r), modo), f'N-1 sem {nome(r)}')
        except Exception:
            pass
    tem_reator = any(h.get('bus') == barra for h in model.shunts)
    if tem_reator:
        curto_barra(_solver(model, None, modo, drop_reatores_barra=[barra]),
                    'N-1 sem o reator de barra')
    tab, _ = recomposicao_87b(model, barra, kinds=kinds, modo=modo)
    for rot, ram, v in tab:
        for k in kinds:
            if v.get(k) and v[k] * 1000.0 > I_DESENERGIZADA:
                cand.append((v[k] * 1000.0, f'recomposição por {nome(ram)}, {k}'))
    recomp = {ram: v for _, ram, v in tab}
    if cenarios:
        from .fluxo import curto_por_cenario, aplicar_despacho
        cc = curto_por_cenario(model, cenarios, [barra], kinds=kinds, modo=modo,
                               caso_conferido=bool(getattr(model, '_leitura_conferida', None)))
        piores = []
        for k in kinds:
            e = cc['extremos'].get((barra, k))
            if e:
                cand.append((e['min'][0], f"cenário {e['min'][1]}, {k}"))
                piores.append(e['min'])
        if piores:
            nome_cen = min(piores)[1]
            Mc, _ = aplicar_despacho(model, cenarios[nome_cen], sem_correspondencia='retirar')
            tabc, _ = recomposicao_87b(Mc, barra, kinds=kinds, modo=modo)
            for rot, ram, v in tabc:
                for k in kinds:
                    if v.get(k) and v[k] * 1000.0 > I_DESENERGIZADA:
                        cand.append((v[k] * 1000.0,
                                     f'recomposição por {nome(ram)} no cenário {nome_cen}, {k}'))
        prem += [p for p in cc['premissas'] if p not in prem]
    icc_min, cond_min = min(cand)
    categorias = {}
    for v, c in cand:
        cat = ('recomposição' if c.startswith('recomposição') else
               'cenário' if c.startswith('cenário') else
               'contingência' if c.startswith('N-1') else 'rede completa')
        if cat not in categorias or v < categorias[cat][0]:
            categorias[cat] = (v, c)

    # --- cargas por vão ---
    cargas = {}
    for r in inc:
        c = dict(emergencia_A=None, nominal_A=None, origem=None)
        if cenarios:
            from .fluxo import carga_maxima
            cm = carga_maxima(cenarios, r[0], r[1], r[2])
            if cm and (cm.get('cap_emergencia_A') or cm.get('cap_normal_A')):
                c.update(emergencia_A=cm.get('cap_emergencia_A') or cm.get('cap_normal_A'),
                         nominal_A=cm.get('cap_normal_A'), origem='ANAREDE')
        if c['origem'] is None:
            b = da_base(model, *r)
            if b.get('in_nominal'):
                c.update(nominal_A=b['in_nominal'], emergencia_A=None,
                         origem='.ANA, potência nominal; capacidade de emergência não '
                                'declarada')
        cargas[nome(r)] = c
    emerg = [c['emergencia_A'] for c in cargas.values() if c['emergencia_A']]
    nomin = [c['nominal_A'] for c in cargas.values() if c['nominal_A']]
    hip_carga = None
    if emerg:
        carga_max = max(emerg)
    elif nomin:
        # HIPÓTESE EXPLÍCITA: sem capacidade de emergência declarada, o piso de carga usa a
        # nominal — que é menor que a emergência e portanto não protege contra atuação em
        # regime de emergência. Registrada nas premissas e nos alertas do 87B.
        carga_max = max(nomin)
        hip_carga = ('capacidade de emergência não declarada: piso de carga do 87B pela '
                     'NOMINAL, abaixo da emergência real')
    else:
        carga_max = None
    carga_min_nom = min(nomin) if nomin else None

    carga_min_real = None
    if cenarios:
        from .fluxo import fluxos
        reais = []
        for pwf in cenarios.values():
            fl = fluxos(pwf)
            for r in inc:
                f = fl.get((r[0], r[1], r[2])) or fl.get((r[1], r[0], r[2]))
                if f and f.get('calculavel'):
                    i = f['I_de_A'] if (f is fl.get((r[0], r[1], r[2])) and r[0] == barra) \
                        else f['I_para_A']
                    if i:
                        reais.append(i)
        carga_min_real = min(reais) if reais else None
    in_ref = dados.get('in_tc_ref')
    piso_tc = (max(crit['piso_in_tc'], dados.get('ajuste_minimo_rele', 0) or 0) * float(in_ref)
               if in_ref else None)

    def aplica_piso(v, alertas):
        if piso_tc and v < piso_tc:
            alertas.append(f'elevado ao piso de medição de {piso_tc:.0f} A '
                           f'({crit["piso_in_tc"]:.0%} de In do TC de referência)')
            return piso_tc
        return v

    funcoes, alertas87 = {}, []
    if hip_carga:
        alertas87.append(hip_carga)
        prem.append(hip_carga)
    sug = crit['f_icc'] * icc_min
    if carga_max is None:
        pk = sug; alertas87.append('carga dos vãos não disponível: piso de carga não verificado')
    elif carga_max < icc_min:
        if sug > carga_max:
            pk = sug
        else:
            pk = carga_max
            alertas87.append(f'67% do curto mínimo fica abaixo da carga de emergência; '
                             f'pickup na carga, com relação de sensibilidade '
                             f'{icc_min / pk:.2f}')
    else:
        pk = sug
        alertas87.append('carga de emergência acima do curto mínimo: prevalece o curto — '
                         'TC aberto no vão mais carregado pode provocar disparo')
    pk = aplica_piso(pk, alertas87)
    if pk > crit['f_icc_max'] * icc_min:
        alertas87.append(f"pickup acima de {crit['f_icc_max']:.0%} do curto mínimo "
                         f"(teto recomendado pelo guia do REB670)")
    if in_ref:
        lo, hi = crit['faixa_tc']
        if not (lo * float(in_ref) <= pk <= hi * float(in_ref)):
            alertas87.append(f"pickup fora da faixa típica de {lo:.0%} a {hi:.0%} de In do "
                             f"maior TC ({lo*float(in_ref):.0f} a {hi*float(in_ref):.0f} A)")
    if pk >= icc_min:
        alertas87.append('pickup não fica abaixo do curto mínimo: sensibilidade não garantida')
    passo = crit.get('passo_ajuste')
    if passo:
        q = quantizar(pk, (carga_max, crit['f_icc_max'] * icc_min), passo, 'baixo')
        if q is None:
            alertas87.append(f'faixa não comporta o passo de ajuste de {passo} A')
        else:
            pk = q
    funcoes['87B'] = dict(pickup=pk, faixa=(carga_max, icc_min), icc_min=icc_min,
                          minimos_por_categoria=categorias,
                          condicao_icc_min=cond_min, relacao=icc_min / pk,
                          carga_emergencia_max=carga_max, alertas=alertas87)
    # checkzone: critério próprio — operar para toda falta interna da barra, com a mesma
    # corrente mínima; sem escala fixa em relação ao 87B
    ac = []
    teto_ck = crit['f_icc_max'] * icc_min
    if crit.get('f_checkzone'):
        ck = aplica_piso(crit['f_checkzone'] * pk, ac)
    else:
        ck = None
        ac.append('ajuste não sugerido: informe o critério da checkzone; a faixa garante '
                  'operação para toda falta interna')
    funcoes['checkzone'] = dict(pickup=ck, min=piso_tc, max=teto_ck,
                                viavel=(piso_tc or 0) <= teto_ck,
                                relacao=(icc_min / ck) if ck else None, alertas=ac)
    # alarme de TC aberto: abaixo da MENOR CORRENTE REAL conduzida pelos vãos — é ela que
    # aparece como diferencial quando um TC abre; a nominal não serve de referência.
    # Limite inferior (diferencial permanente) e temporização dependem dos TCs.
    aa = []
    if carga_min_real is None:
        aa.append('menor corrente real dos vãos indisponível: requer os casos do ANAREDE')
    if crit.get('f_alarme'):
        al = aplica_piso(crit['f_alarme'] * pk, aa)
    else:
        al = None
        aa.append('ajuste não sugerido: informe o critério; o limite superior é a menor '
                  'corrente real dos vãos')
    if al and carga_min_real and al >= carga_min_real:
        aa.append(f'alarme acima da menor corrente real dos vãos ({carga_min_real:.0f} A): '
                  f'TC aberto nesse vão não será detectado')
    funcoes['alarme'] = dict(pickup=al, min=None, max=carga_min_real,
                             viavel=None, temporizacao=None,
                             limite_superior=carga_min_real, alertas=aa)
    funcoes['slope'] = dict(calculado=False, por_fabricante=dict(SLOPE_87B_POR_FABRICANTE),
                            observacao='parâmetro do IED: seguir o manual do fabricante e o '
                                       'estudo de saturação dos TCs')

    # --- 50BF e EFP por vão de linha ---
    bf, efp = {}, {}
    falhas = []
    linhas = [r for r in inc if not e_trafo(r)]
    conf = getattr(model, '_leitura_conferida', None)
    for L in linhas:
        rem = outro(L)
        c50, cef_l = [], []
        for k in kinds:
            # 50BF: falta na extremidade oposta com o terminal remoto aberto (rede normal)
            try:
                v = S0.line_end_open(L[0], L[1], L[2], barra, k, p=1.0)
                if v:
                    c50.append((v * 1000.0,
                                f'falta na extremidade oposta, remoto aberto, rede normal, {k}'))
            except Exception as ex:
                falhas.append(f'50BF {nome(L)} rede normal {k}: {type(ex).__name__}')
            # EFP lado da linha: disjuntor local aberto, falta junto a ele, alimentação remota
            try:
                v = S0.line_end_open(L[0], L[1], L[2], rem, k, p=1.0)
                if v:
                    cef_l.append((v * 1000.0,
                                  f'disjuntor local aberto, alimentação pelo terminal remoto, {k}'))
            except Exception as ex:
                falhas.append(f'EFP {nome(L)} {k}: {type(ex).__name__}')
        for F in inc:
            if F == L:
                continue
            # alimentação local só por F; a linha L fica, e é aberta no terminal remoto
            SF = Solver(model, drop_branches=[x for x in inc if x not in (F, L)],
                        drop_reatores_barra=[barra], modo=modo)
            if modo == 'completo':
                if conf:
                    SF.validado_completo = True
                    SF._selo_completo = dict(conf, conferido_no_caso=True)
                else:
                    SF.liberar_completo_sem_gabarito('cenário de alimentação fraca')
            for k in kinds:
                try:
                    v = SF.line_end_open(L[0], L[1], L[2], barra, k, p=1.0)
                except Exception as ex:
                    falhas.append(f'50BF {nome(L)} só {nome(F)} {k}: {type(ex).__name__}')
                    continue
                if v:
                    c50.append((v * 1000.0,
                                f'extremidade oposta, remoto aberto, só {nome(F)}, {k}'))
        cef_b = [(recomp[F][k] * 1000.0, f'alimentação só por {nome(F)}, {k}')
                 for F in recomp if F != L for k in kinds
                 if recomp[F].get(k) and recomp[F][k] * 1000.0 > I_DESENERGIZADA]
        c50 = [x for x in c50 if x[0] > I_DESENERGIZADA]
        cef_l = [x for x in cef_l if x[0] > I_DESENERGIZADA]
        if not c50 or not cef_l:
            continue
        car = cargas[nome(L)]
        i50, c50m = min(c50)
        a50 = []
        s50 = crit['f_icc'] * i50
        if car['nominal_A'] and s50 <= car['nominal_A']:
            if car['nominal_A'] < i50:
                s50 = car['nominal_A']
                a50.append('67% do curto mínimo fica abaixo da carga nominal; pickup na carga')
            else:
                a50.append('carga nominal acima do curto mínimo: prevalece o curto')
        s50 = aplica_piso(s50, a50)
        bf[nome(L)] = dict(pickup=s50, faixa=(car['nominal_A'], i50), icc_min=i50,
                           condicao=c50m, relacao=i50 / s50, alertas=a50)
        il, cl = min(cef_l)
        ib_, cb = min(cef_b) if cef_b else (None, None)
        el, eb = [], []
        efp[nome(L)] = dict(
            tc_lado_linha=dict(pickup=aplica_piso(crit['f_icc'] * il, el), icc_min=il,
                               condicao=cl, alertas=el),
            tc_lado_barra=(dict(pickup=aplica_piso(crit['f_icc'] * ib_, eb), icc_min=ib_,
                                condicao=cb, alertas=eb) if ib_ else None))
    funcoes['50BF'] = bf
    funcoes['EFP'] = efp
    conferido = bool(getattr(model, '_leitura_conferida', None)) or not S0._tem_fc() \
        or modo != 'completo'
    for nomef in ('87B', 'checkzone', 'alarme'):
        funcoes[nomef]['estado'] = _estado(funcoes[nomef], conferido)
    funcoes['slope']['estado'] = 'modelo_nao_suportado'
    for grupo in (bf, efp):
        for v in grupo.values():
            for f in ([v] if 'pickup' in v else [x for x in v.values() if isinstance(x, dict)]):
                f['estado'] = _estado(f, conferido)

    prem += [
        f'corrente mínima na barra: menor entre rede completa, N-1 de cada equipamento '
        f'(transformador com todas as pernas){", reator de barra" if tem_reator else ""} e '
        f'recomposição por cada alimentação isolada' +
        (', e o menor cenário de despacho do ANAREDE com a sua recomposição' if cenarios else ''),
        'recomposição: demais conexões e reator de barra desligados; não se usa a condição '
        'com apenas o reator de barra conectado',
        'condições que deixam a barra sem alimentação são desconsideradas',
        f"87B: acima da carga de emergência e abaixo do curto mínimo; sugerido "
        f"{crit['f_icc']:.0%} do curto mínimo; se a faixa não existir, prevalece o curto",
        "checkzone: faixa própria — acima do piso de medição e abaixo do teto de "
        "sensibilidade para toda falta interna; sem escala fixa em relação ao 87B",
        "alarme de TC aberto: abaixo da menor corrente REAL conduzida pelos vãos nos "
        "cenários do ANAREDE; limite inferior (diferencial permanente) e temporização "
        "dependem dos TCs e não foram verificados",
        f"50BF: acima da carga nominal do vão e abaixo da falta na extremidade oposta com o "
        f"terminal remoto aberto, na alimentação local mais fraca; sugerido "
        f"{crit['f_icc']:.0%} dessa corrente. Disparos sem corrente de falta (sobretensão, "
        f"transferência) exigem lógica por contato do disjuntor; se a sensibilidade exigir, o "
        f"detector pode ficar abaixo da carga — a iniciação por disparo evita operação indevida",
        f"EFP: abaixo da falta junto ao disjuntor aberto, sugerido {crit['f_icc']:.0%}; lado "
        f"da linha alimentado pelo terminal remoto, lado da barra pela barra; sem piso de "
        f"carga; a posição real do TC define qual vale",
        "slope: parâmetro do IED, não calculado — SEL-487B 60%/80% com comutação por falta "
        "externa, Siemens 7SS85 k de 0,10 a 0,80, REB670 fixo em 53%; os percentuais não são "
        "transferíveis entre fabricantes",
        f"87B: verificado o teto de {crit['f_icc_max']:.0%} do curto mínimo e, com o TC "
        f"informado, a faixa típica de {crit['faixa_tc'][0]:.0%} a {crit['faixa_tc'][1]:.0%} "
        f"de In do maior TC (guia do REB670)",
        'cargas por vão: ' + ('capacidades do ANAREDE (emergência e normal)' if cenarios
                              else 'potência nominal do .ANA; emergência não disponível'),
        'arranjo da subestação não informado: cargas por vão, sem composição por diagonal',
        '50BF e EFP de vãos de transformador não calculados',
    ]
    if piso_tc:
        prem.append(f"piso de medição: {crit['piso_in_tc']:.0%} de In do TC de referência "
                    f"({float(in_ref):.0f} A)")
    faltantes = []
    if not in_ref:
        faltantes.append('in_tc_ref')
    if not cenarios:
        faltantes.append('casos do ANAREDE (carga de emergência por vão)')
    res = dict(barra=barra, nome=model.bus_name.get(barra, ''), kv=kv, modo=modo,
                funcoes=funcoes, cargas=cargas, premissas=prem, faltantes=faltantes,
                falhas=falhas,
                funcoes_sm211=funcoes_exigidas('barra'))
    res['exportacao'] = politica_exportacao(res, perfil_ied)
    return res


# ====================================================================== #
#  Diferencial de linha (87L)                                            #
# ====================================================================== #

def estudo_87L(model, linha, dados=None, criterios=None, modo='completo',
               kinds=_KINDS, posicoes=(0.001, 0.5, 0.999), n1=True, perfil_ied=None):
    """Diferencial de linha de dois terminais: faixa de pickup e referências de estabilidade.

    Limite inferior: corrente capacitiva da linha na tensão máxima de operação — aparece
    como diferencial em regime. Limite superior: a menor corrente diferencial para falta
    INTERNA, varrida ao longo da linha (`posicoes`) em rede completa e N-1 em torno dos
    dois terminais; a diferencial de uma falta interna é a própria corrente de falta, com
    os dois terminais alimentando ou com um deles fraco. Referência de estabilidade: a
    maior corrente passante para falta externa nas duas barras.

    `criterios`: 'v_max' (pu, padrão 1,05), 'margem_capacitiva' e 'relacao_sensibilidade'
    (sem padrão — critério do usuário); `dados`: 'in_tc_ref' para o piso de medição.
    A característica percentual, a compensação de corrente capacitiva e o canal de
    comunicação do IED não estão modelados.
    """
    crit = dict(criterios or {})
    dados = dict(dados or {})
    bf, bt, nc = int(linha[0]), int(linha[1]), str(linha[2])
    S0 = _solver(model, None, modo)
    br = S0._find_branch(bf, bt, nc)
    if br is None or br['tipo'] != 'L':
        raise ValueError(f'linha {bf}-{bt}/{nc} não encontrada')
    kv = model.bus_kv.get(bf)
    Ib = SB / (np.sqrt(3) * kv) * 1000.0                  # A
    vmax = crit.get('v_max', 1.05)
    b_pu = (br.get('S1') or 0.0) / 100.0                  # susceptância total, pu
    i_cap = b_pu * vmax * Ib if b_pu else None
    prem = _premissas_curto(S0)

    cen = [('rede completa', [])]
    if n1:
        vistos = set()
        for b in (bf, bt):
            for r in _ramos_incidentes(model, b):
                eq = tuple(sorted(_equipamento(model, r, b)))
                if (bf, bt, nc) in eq or (bt, bf, nc) in eq or eq in vistos:
                    continue
                vistos.add(eq)
                cen.append((f'N-1 sem {r[0]}-{r[1]}/{r[2]}', list(eq)))
    internas, externas, falhas = [], [], []
    for rot, drop in cen:
        try:
            S = S0 if not drop else _solver(model, drop, modo)
        except Exception as ex:
            falhas.append(f'{rot}: {type(ex).__name__}')
            continue
        for k in kinds:
            for p in posicoes:
                try:
                    r = S.fault_on_branch(bf, bt, nc, p, k)
                except Exception as ex:
                    falhas.append(f'{rot}, p={p}, {k}: {type(ex).__name__}')
                    continue
                if r and r.get('If'):
                    internas.append((r['If'] * 1000.0, f'{rot}, falta interna a {p:.0%}, {k}'))
            for fb in (bf, bt):
                try:
                    r = S.branch_current(fb, bf, bt, nc, k)
                except Exception as ex:
                    falhas.append(f'{rot}, externa em {fb}, {k}: {type(ex).__name__}')
                    continue
                if r:
                    externas.append((r['Imax'] * 1000.0, f'{rot}, falta externa em {fb}, {k}'))
    i_int_min = min(internas) if internas else (None, None)
    i_ext_max = max(externas) if externas else (None, None)
    alertas = []
    piso = i_cap * crit['margem_capacitiva'] if (i_cap and crit.get('margem_capacitiva')) else i_cap
    if dados.get('in_tc_ref'):
        piso_tc = 0.05 * float(dados['in_tc_ref'])
        if piso is None or piso_tc > piso:
            piso = piso_tc
    teto = (i_int_min[0] / crit['relacao_sensibilidade']
            if (i_int_min[0] and crit.get('relacao_sensibilidade')) else i_int_min[0])
    viavel = (piso is None or teto is None) or piso < teto
    if not viavel:
        alertas.append('corrente capacitiva acima da menor falta interna: exige compensação '
                       'de corrente capacitiva no IED')
    if not crit.get('relacao_sensibilidade'):
        alertas.append('relação de sensibilidade não informada: teto na própria falta mínima')
    prem += [
        f'corrente capacitiva da linha a {vmax:.2f} pu, pela susceptância total do cadastro',
        'falta interna varrida em ' + ', '.join(f'{p:.0%}' for p in posicoes) +
        ' da linha, rede completa e N-1 em torno dos dois terminais; diferencial = corrente '
        'de falta',
        'estabilidade referida à maior corrente passante para falta externa nas duas barras',
        'característica percentual, compensação capacitiva e canal do IED não modelados',
    ]
    f = dict(min=piso, max=teto, viavel=viavel, pickup=None,
             i_capacitiva=i_cap, i_interna_min=i_int_min[0], condicao_interna=i_int_min[1],
             i_passante_max=i_ext_max[0], condicao_passante=i_ext_max[1], alertas=alertas)
    conferido = bool(getattr(model, '_leitura_conferida', None)) or not S0._tem_fc() \
        or modo != 'completo'
    f['estado'] = _estado(f, conferido)
    out = dict(linha=(bf, bt, nc), modo=modo, funcoes={'87L': f}, premissas=prem,
               falhas=falhas,
               faltantes=[x for x, ok in (('relacao_sensibilidade', crit.get('relacao_sensibilidade')),
                                         ('in_tc_ref', dados.get('in_tc_ref'))) if not ok])
    out['exportacao'] = politica_exportacao(out, perfil_ied)
    return out
