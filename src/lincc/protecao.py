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
        S=Solver(model, drop_branches=drop, modo=modo); S.factor(avisar=False)
        if modo=='completo':
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
            cen.append((f'terminal oposto aberto em {e[1]}-{e[2]}/{e[3]}',
                        [(e[1], e[2], e[3])], barra, ('LEO',) + e[1:]))

    saida = {e: {'casos': []} for e in incid}
    cache = {}
    for rot, drop, fb, extra in cen:
        chave = tuple(sorted(drop))
        if chave not in cache:
            try:
                S = S0 if not drop else Solver(model, drop_branches=list(drop),
                                               modo=getattr(S0, 'modo', 'completo'))
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
         'correntes em kA primários (A primários nos ajustes)']
    if S.modo == 'completo' and S._tem_fc():
        p.append('modo completo: inclui a contribuição dos geradores conectados por '
                 'conversor, conforme a curva do Submódulo 2.10')
        p.append('leitura do caso conferida contra o relatório do ANAFAS'
                 if sel.get('conferido_no_caso') else
                 'leitura do caso NÃO conferida contra o relatório do ANAFAS')
    else:
        p.append('modo síncronas: Thévenin sem a contribuição dos geradores de conversor')
    return p


def _solver(model, drop=None, modo='completo'):
    # avisar=False: numa chamada de alto nível o aviso apareceria uma vez por cenário
    # interno — o relatório declara o modo no retorno, que é onde interessa.
    S = Solver(model, drop_branches=list(drop) if drop else None, modo=modo)
    S.factor(avisar=False)
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
        f51_nominal=1.50,      # pickup do 51: 150% da nominal
        f50_margem=1.20,       # 50 acima do passa-através e do inrush com essa margem
    ),
}


def _faixa(minimo, maximo):
    """Faixa admissível. Viável se o limite inferior não exceder o superior."""
    if minimo is None or maximo is None:
        return dict(min=minimo, max=maximo, viavel=None)
    return dict(min=minimo, max=maximo, viavel=minimo <= maximo)


def ajuste_sobrecorrente(model, tipo, elemento, dados=None, criterios=None,
                         modo='completo', curva='MI', norma='IEC', cenarios=None):
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
                    f"{crit['f67nt_max_1f']:.0%} da monofásica remota")
        if pk:
            try:
                f51['tms_minimo'] = _curvas.tms_para_tempo(severo, pk, crit['t_z2'], curva, norma)
                f51['tempo_no_defeito'] = crit['t_z2']
            except ValueError as e:
                f51['aviso'] = str(e)
        out['funcoes']['51'] = f51

        # --- 50: só se seletivo para falta na barra remota ---
        i_remota_max = max(v for v in i_barra_remota.values() if v)
        i_local = i_barra_local['3F']
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
        teto = crit['f67nt_max_1f'] * i_barra_remota['1FT'] if i_barra_remota['1FT'] else None
        piso = None if falta('in_tc') else crit['f67nt_min_in_tc'] * float(dados['in_tc'])
        f67 = _faixa(piso, teto)
        f67.update(criterio=f"entre {crit['f67nt_min_in_tc']:.0%} de In do TC e "
                            f"{crit['f67nt_max_1f']:.0%} da monofásica remota",
                   usual=piso, i_1f_remota=i_barra_remota['1FT'], curva='muito inversa')
        out['funcoes']['67NT'] = f67

    elif tipo == 'transformador':
        # --- 51: 150% da nominal ---
        inom = dados.get('in_nominal')
        if inom in (None, ''):
            falta('in_nominal')
        out['funcoes']['51'] = dict(
            pickup=crit['f51_nominal'] * float(inom) if inom else None,
            criterio=f"{crit['f51_nominal']:.0%} da nominal")
        prem.append(f"51 de transformador: pickup em {crit['f51_nominal']:.0%} da corrente "
                    f"NOMINAL, não referido à capacidade de emergência — se esta superar "
                    f"o pickup, a proteção pode atuar em regime de emergência")
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
        try:
            r = S.branch_current(outro, bf, bt, nc, '3F')
            passa = r['Imax'] if r else None
        except Exception:
            passa = None
        passa = kA(passa)
        i_local = kA(S.fault(bf, '3F'))
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
    return out
