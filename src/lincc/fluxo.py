"""Motor de fluxo de potência — processamento das bases do ANAREDE.

Fornece as grandezas de REGIME PERMANENTE que a base de curto-circuito não contém e que
vários critérios de proteção exigem: carregamento por circuito e por bay, tensão e ângulo
de barra, capacidade normal/emergência/equipamento, e o despacho de cada cenário.

Não resolve fluxo de potência: lê o caso já convergido, publicado pelo ONS, que é o que os
estudos usam. Resolver o fluxo seria refazer o que o ANAREDE já fez, com risco de divergir
do caso oficial.

Estado: em construção. O parser está em `parser_anarede`; este módulo compõe as grandezas
derivadas a partir dele.

    from lincc.fluxo import carregamento, tensao_barra, envelope_cenarios
"""
from __future__ import annotations

import numpy as np

from ._base import SB


def corrente_nominal(mva, kv):
    """Corrente correspondente a uma potência aparente, em A. I = MVA·1000/(√3·kV)."""
    if not mva or not kv:
        return None
    return float(mva) * 1000.0 / (np.sqrt(3) * float(kv))


def carregamento(pwf, bf, bt, nc=None):
    """Carregamento de um circuito no cenário lido, em A, e suas capacidades.

    Devolve dict com a corrente de operação e os três limites do DLIN — normal,
    emergência e equipamento. É o dado que o .ANA não tem e que o critério do 51 de
    linha, do SOTF e do pickup do 87B exigem.
    """
    br = pwf.circuito(bf, bt, nc)
    if br is None:
        return None
    kv = pwf.bus_kv.get(bf) or pwf.bus_kv.get(bt)
    out = {
        'cap_normal_A': br.get('Cn'),
        'cap_emergencia_A': br.get('Ce'),
        'cap_equipamento_A': br.get('Cq'),
        'kv': kv,
    }
    p, q = br.get('P'), br.get('Q')
    if p is not None and q is not None and kv:
        out['corrente_A'] = corrente_nominal((p * p + q * q) ** 0.5, kv)
    return out


def tensao_barra(pwf, bus):
    """Tensão e ângulo da barra no cenário lido: (V em pu, ângulo em grau)."""
    b = pwf.barras.get(bus)
    if b is None:
        return None
    return b.get('V'), b.get('A')


def envelope_cenarios(cenarios, funcao):
    """Aplica `funcao(pwf)` a cada cenário e devolve mínimo e máximo, COM o cenário.

    `cenarios` é {nome: PwfModel}. O mínimo de curto dimensiona sensibilidade e o máximo
    dimensiona suportabilidade, e eles costumam cair em cenários DIFERENTES — por isso o
    retorno nomeia de onde veio cada extremo, em vez de devolver só os números.

    Nos casos de referência a variação dominante é diurno contra noturno (~2.200 barras
    despachadas de diferença, efeito solar), e não máxima contra mínima carga (~30).
    Varrer só níveis de carga perderia quase toda a variação.
    """
    vals = []
    for nome, pwf in (cenarios or {}).items():
        try:
            v = funcao(pwf)
        except Exception:
            continue
        if v is not None:
            vals.append((float(v), nome))
    if not vals:
        return None
    return {'min': min(vals), 'max': max(vals), 'n': len(vals)}


# ====================================================================== #
#  Fluxo por circuito, avaliado sobre o estado convergido do caso        #
# ====================================================================== #

SEM_LIMITE = 9999.0     # marcador do ANAREDE para capacidade não declarada


def _cap(v):
    """Capacidade em MVA, ou None quando ausente ou igual ao marcador de 'sem limite'."""
    if v is None or v <= 0 or v >= SEM_LIMITE:
        return None
    return float(v)


def fluxos(pwf):
    """Corrente e potência em cada circuito, nas duas extremidades, a partir do estado
    convergido do caso.

    Não resolve fluxo de potência: avalia as correntes com as tensões e ângulos que o
    ANAREDE já convergiu. Linha em modelo π com a susceptância total do circuito; trafo
    com tap na barra de origem, como é a convenção do ANAREDE.

    Devolve {(bf, bt, nc): dict} com, para cada extremidade, corrente em A, potência
    aparente em MVA, e o carregamento em relação às três capacidades declaradas.
    """
    V = {}
    for b, d in pwf.barras.items():
        # Barra desligada tira de serviço os circuitos que chegam nela, mesmo que o
        # registro do circuito não traga marca de desligado — é o que o ANAREDE faz.
        if d.get('V') is None or d.get('estado') == 'D':
            continue
        ang = np.deg2rad(d.get('A') or 0.0)
        V[b] = d['V'] * np.exp(1j * ang)
    saida = {}
    for c in pwf.circuitos:
        if c.get('estado') == 'D':
            continue
        bf, bt = c['bf'], c['bt']
        if bf not in V or bt not in V:
            continue
        R = (c.get('R') or 0.0) / 100.0
        X = (c.get('X') or 0.0) / 100.0
        z = complex(R, X)
        if abs(z) < 1e-12:
            continue
        y = 1.0 / z
        bsh = (c.get('Mvar') or 0.0) / 100.0            # susceptância total, pu
        a = c.get('Tap') or 1.0
        phs = np.deg2rad(c.get('Phs') or 0.0)
        t = a * np.exp(1j * phs)
        Vi, Vj = V[bf], V[bt]
        # tap na barra de origem: Ii = y/|t|²·Vi − y/t*·Vj ;  Ij = −y/t·Vi + y·Vj
        Ii = y / (abs(t) ** 2) * Vi - y / np.conj(t) * Vj + 1j * bsh / 2 * Vi
        Ij = -y / t * Vi + y * Vj + 1j * bsh / 2 * Vj
        Si = Vi * np.conj(Ii) * 100.0
        Sj = Vj * np.conj(Ij) * 100.0
        kvf, kvt = pwf.bus_kv.get(bf), pwf.bus_kv.get(bt)
        caps = {k: _cap(c.get(k)) for k in ('Cn', 'Ce', 'Cq')}
        s_max = max(abs(Si), abs(Sj))
        # Incerteza do fluxo pelo arredondamento do arquivo: tensão com 3 casas e ângulo
        # com ~1 casa (pior caso). Mediana de 2,3% nas linhas de 230 kV e acima no caso de
        # referência. Em chave de interligação (impedância quase nula) o fluxo não pode ser
        # obtido das tensões gravadas, e o valor é marcado como não calculável.
        incerteza = (0.0005 + np.deg2rad(0.05)) / abs(z) * 100.0 if abs(z) else None
        chave = abs(z) < 0.0005
        saida[(bf, bt, c['nc'])] = dict(
            S_de_MVA=abs(Si), S_para_MVA=abs(Sj),
            P_de_MW=Si.real, Q_de_Mvar=Si.imag,
            P_para_MW=Sj.real, Q_para_Mvar=Sj.imag,
            I_de_A=abs(Ii) * 100e3 / (np.sqrt(3) * kvf) if kvf else None,
            I_para_A=abs(Ij) * 100e3 / (np.sqrt(3) * kvt) if kvt else None,
            cap_normal_MVA=caps['Cn'], cap_emergencia_MVA=caps['Ce'],
            cap_equipamento_MVA=caps['Cq'],
            carregamento_normal=(s_max / caps['Cn']) if caps['Cn'] else None,
            carregamento_emergencia=(s_max / caps['Ce']) if caps['Ce'] else None,
            incerteza_MVA=incerteza, calculavel=not chave,
        )
    return saida


def balanco(pwf, fl=None):
    """Resíduo do balanço de potência ATIVA em cada barra: Pg − Pl − Σ P saindo, em MW.

    Num caso convergido o resíduo é da ordem da tolerância do ANAREDE. É a verificação de
    que `fluxos` está certo: se a régua de algum campo estivesse errada, o balanço não
    fecharia. Usa-se o ativo porque bancos shunt e compensadores estáticos — blocos que
    este parser não lê — mexem só no reativo.

    Devolve {barra: resíduo_MW}.
    """
    fl = fl if fl is not None else fluxos(pwf)
    sai = {}
    for (bf, bt, nc), d in fl.items():
        sai[bf] = sai.get(bf, 0.0) + d['P_de_MW']
        sai[bt] = sai.get(bt, 0.0) + d['P_para_MW']
    res = {}
    for b, d in pwf.barras.items():
        if d.get('estado') == 'D':
            continue
        res[b] = (d.get('Pg') or 0.0) - (d.get('Pl') or 0.0) - sai.get(b, 0.0)
    return res



# ====================================================================== #
#  Despacho do cenário aplicado ao curto-circuito                        #
# ====================================================================== #

def aplicar_despacho(ana, pwf, saltos=3, sem_correspondencia='manter'):
    """Cópia do caso de curto-circuito com o despacho de um cenário do ANAREDE.

    O ANAFAS representa a rede sempre completa, com todas as unidades em operação. O
    ANAREDE traz, por cenário, quais usinas estão gerando. Esta função tira do caso de
    curto as fontes que o cenário deixa paradas — e só isso: impedâncias, topologia e
    modelo de cálculo ficam intactos. O motor de curto-circuito não é alterado.

    Critério, fonte a fonte:

      * gerador de conversor (bloco DEOL): casado pelo número da barra; sai se a geração
        ativa no cenário é nula.
      * gerador síncrono cuja barra existe no fluxo: idem.
      * gerador síncrono cuja barra não existe no fluxo — terminais de gerador que o
        ANAREDE agrega: sobe pela rede, até `saltos` barras, até a primeira que tenha
        geração declarada no fluxo, e herda o estado dela.
      * sem correspondência: `sem_correspondencia='manter'` (padrão) mantém o gerador,
        que é conservador para SUPORTABILIDADE; 'retirar' o tira, que é conservador para
        SENSIBILIDADE. Os dois juntos dão a faixa de incerteza do mapeamento.

    Devolve (caso_do_cenario, relatorio). O relatório conta o que saiu, o que ficou por
    decisão e o que ficou por falta de correspondência — é o que o estudo deve declarar.
    """
    import copy
    from collections import deque

    def gera(b):
        d = pwf.barras.get(b)
        if d is None or d.get('estado') == 'D':
            return None
        return abs(d.get('Pg') or 0.0) > 1e-6

    adj = {}
    for x in ana.branches:
        adj.setdefault(x['bf'], []).append(x['bt'])
        adj.setdefault(x['bt'], []).append(x['bf'])

    def estado_por_topologia(b):
        vis = {b}
        q = deque([(b, 0)])
        while q:
            u, d = q.popleft()
            if u != b and u in pwf.barras and pwf.barras[u].get('tipo') in ('1', '2'):
                return gera(u)
            if d >= saltos:
                continue
            for v in adj.get(u, []):
                if v not in vis:
                    vis.add(v)
                    q.append((v, d + 1))
        return None

    rel = dict(sincronos_retirados=0, sincronos_mantidos=0, sincronos_sem_correspondencia=0,
               conversores_retirados=0, conversores_mantidos=0,
               conversores_sem_correspondencia=0)
    gens = []
    for g in ana.gens:
        b = g['bus']
        st = gera(b) if b in pwf.barras else estado_por_topologia(b)
        if st is None:
            rel['sincronos_sem_correspondencia'] += 1
            if sem_correspondencia == 'manter':
                gens.append(g)
        elif st:
            rel['sincronos_mantidos'] += 1
            gens.append(g)
        else:
            rel['sincronos_retirados'] += 1
    deol = {}
    for b, regs in ana.deol.items():
        st = gera(b)
        if st is None:
            rel['conversores_sem_correspondencia'] += 1
            if sem_correspondencia == 'manter':
                deol[b] = regs
        elif st:
            rel['conversores_mantidos'] += 1
            deol[b] = regs
        else:
            rel['conversores_retirados'] += 1
    M = copy.copy(ana)
    M.gens = gens
    M.deol = deol
    M.eol = set(deol)
    rel['cenario'] = getattr(pwf, 'titulo', '')
    return M, rel


def curto_por_cenario(ana, cenarios, barras, kinds=('3F', '1FT'), modo='completo',
                      caso_conferido=False):
    """Corrente de curto-circuito em cada cenário de despacho, com os extremos nomeados.

    `cenarios` é {nome: PwfModel}. Devolve, para cada barra e tipo de defeito, o MÁXIMO e o
    MÍNIMO entre os cenários, cada um com o nome do cenário em que ocorreu.

    O envelope é conservador nos dois lados. Parte dos geradores síncronos do caso de
    curto não tem correspondência no fluxo — terminais que o ANAREDE agrega —, e o estado
    deles no cenário é desconhecido. Por isso cada extremo é calculado sob a hipótese que
    o torna seguro para o seu uso:

      máximo  (suportabilidade)  com os geradores sem correspondência LIGADOS
      mínimo  (sensibilidade)    com os geradores sem correspondência DESLIGADOS

    A distância entre as duas hipóteses é a incerteza do mapeamento, e vem no retorno —
    no caso de referência chega a 8% numa barra de 500 kV.

    `caso_conferido`: se a leitura do .ANA já foi conferida contra o relatório do ANAFAS,
    os cenários herdam a conferência — são o mesmo arquivo, com fontes retiradas. Os
    valores por cenário não têm gabarito no ANAFAS, que só calcula a rede completa, e o
    método fica declarado no retorno.
    """
    from .solver import Solver

    def calcular(M):
        S = Solver(M, modo=modo)
        S.factor(avisar=False)
        if modo == 'completo' and S._tem_fc():
            S.liberar_completo_sem_gabarito(
                'cenário derivado de caso conferido' if caso_conferido
                else 'cenário de despacho, leitura não conferida')
        res = {}
        for b in barras:
            for k in kinds:
                try:
                    res[(b, k)] = S.fault(b, k) * 1000.0
                except Exception:
                    res[(b, k)] = None
        return res

    saida = {'despacho': {}, 'por_cenario_max': {}, 'por_cenario_min': {}, 'modo': modo,
             'metodo': ('fontes paradas no cenário do ANAREDE retiradas do caso de '
                        'curto-circuito; impedâncias e topologia inalteradas; geradores '
                        'sem correspondência ligados para o máximo e desligados para o '
                        'mínimo'),
             'conferido_contra_anafas': False}
    for nome, pwf in cenarios.items():
        M_max, rel = aplicar_despacho(ana, pwf, sem_correspondencia='manter')
        M_min, _ = aplicar_despacho(ana, pwf, sem_correspondencia='retirar')
        saida['despacho'][nome] = rel
        saida['por_cenario_max'][nome] = calcular(M_max)
        saida['por_cenario_min'][nome] = calcular(M_min)
    extremos = {}
    for b in barras:
        for k in kinds:
            mx = [(r[(b, k)], n) for n, r in saida['por_cenario_max'].items()
                  if r.get((b, k)) is not None]
            mn = [(r[(b, k)], n) for n, r in saida['por_cenario_min'].items()
                  if r.get((b, k)) is not None]
            if mx and mn:
                vmax, vmin = max(mx), min(mn)
                faixa = [abs(saida['por_cenario_max'][n][(b, k)] -
                              saida['por_cenario_min'][n][(b, k)])
                         / saida['por_cenario_max'][n][(b, k)] * 100
                         for n in saida['por_cenario_max']
                         if saida['por_cenario_max'][n].get((b, k))
                         and saida['por_cenario_min'][n].get((b, k))]
                extremos[(b, k)] = {'max': vmax, 'min': vmin,
                                    'incerteza_mapeamento_pct': max(faixa) if faixa else None}
    saida['extremos'] = extremos
    saida['premissas'] = [
        'tensão pré-falta de 1,0 pu, sem carregamento prévio',
        f'modo {modo}',
        'despacho de cada cenário do ANAREDE aplicado ao caso do ANAFAS: fontes com '
        'geração nula retiradas; impedâncias e topologia inalteradas',
        'geradores síncronos fora do fluxo casados subindo até três barras pela rede',
        'geradores sem correspondência: ligados no máximo, desligados no mínimo',
        'despacho binário por usina (ligada ou parada), sem número de unidades',
        'valores por cenário sem gabarito no ANAFAS, que calcula só a rede completa']
    return saida


def carga_maxima(cenarios, bf, bt, nc=None):
    """Carga máxima de um circuito, a partir das bases do ANAREDE.

    Devolve dict em A com as três capacidades declaradas (exatas — não sofrem
    arredondamento) e o maior fluxo observado entre os cenários, com o nome do cenário.

    `carga_max_A` é o valor que os critérios de proteção usam: a capacidade de
    EMERGÊNCIA, e na falta dela a normal. Em regime de emergência o equipamento não pode
    ser desligado indevidamente pela proteção, então todo pickup que dependa de carga
    precisa ficar acima desse limite. A capacidade normal é sempre menor que a de
    emergência e não serve como referência de pickup.

    O fluxo observado vem ao lado para comparação — é uma fotografia dos cenários, não um
    limite.
    """
    caps = {}
    obs = []
    kv = None
    for nome, pwf in cenarios.items():
        c = pwf.circuito(bf, bt, nc)
        if c is None:
            continue
        kv = kv or pwf.bus_kv.get(bf) or pwf.bus_kv.get(bt)
        for k in ('Cn', 'Ce', 'Cq'):
            v = _cap(c.get(k))
            if v:
                caps[k] = max(caps.get(k, 0), v)
        fl = fluxos(pwf)
        f = fl.get((c['bf'], c['bt'], c['nc']))
        if f and f.get('calculavel'):
            s = max(f['S_de_MVA'], f['S_para_MVA'])
            obs.append((s, nome))
    if not kv:
        return None
    a = lambda mva: corrente_nominal(mva, kv) if mva else None
    if caps.get('Ce'):
        ref, origem = caps['Ce'], 'capacidade de emergência'
    elif caps.get('Cn'):
        ref, origem = caps['Cn'], 'capacidade normal (emergência não declarada)'
    else:
        ref, origem = None, None
    out = dict(kv=kv,
               cap_normal_A=a(caps.get('Cn')), cap_emergencia_A=a(caps.get('Ce')),
               cap_equipamento_A=a(caps.get('Cq')),
               carga_max_A=a(ref), origem=origem)
    if obs:
        s, nome = max(obs)
        out['fluxo_max_observado_A'] = a(s)
        out['cenario_do_fluxo_max'] = nome
    out['premissas'] = [f'carga máxima: {origem}' if origem else 'carga máxima não declarada',
                        'capacidades lidas do ANAREDE (exatas); fluxo observado é estimativa '
                        'sobre tensões gravadas com três casas']
    return out
