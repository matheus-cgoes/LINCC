"""Proteção de distância (21/21N): laços, impedância aparente e limites de alcance.

Não usa alcance percentual como aprovação. Mede a impedância aparente vista pelo relé,
laço a laço, em cada cenário — rede completa e contingência simples em torno dos dois
terminais — e devolve os LIMITES que qualquer ajuste de zona precisa respeitar:

    zona 1   abaixo da impedância da linha (não sobrealcança a barra remota)
    zona 2   acima da impedância da linha (cobre a linha inteira) e abaixo da menor
             impedância aparente para falta no fim das linhas adjacentes, com infeed
    zona 3   referência de retaguarda: a maior impedância aparente para falta no fim das
             linhas adjacentes
    carga    menor impedância de carga, pela capacidade de emergência e tensão mínima

Com os alcances informados em `criterios`, calcula a margem de cada zona contra esses
limites e o estado. A comparação é feita por módulo na direção da linha; a região real de
operação depende da característica do IED (mho, quadrilateral, polarização), que não está
modelada aqui — por isso o resultado é insumo, não ajuste exportável.

Laços, com a convenção do motor (monofásica na fase A, bifásica nas fases B e C):

    fase-terra   Z = V_A / (I_A + k0·I_N),   I_N = I_A + I_B + I_C
    fase-fase    Z = (V_B − V_C) / (I_B − I_C)

A compensação residual usa k0 = (Z0L − Z1L) / (3·Z1L), complexo. Relés que usam fatores
separados resistivo e reativo (Kr, Kx) recebem os dois à parte — eles NÃO são as partes
real e imaginária de k0.
"""
from __future__ import annotations

import numpy as np

from ._base import SB, zfin
from .solver import Solver


def para_secundario(valor, grandeza, rtc=None, rtp=None):
    """Converte grandeza primária para o secundário dos transformadores de instrumento.

    grandeza: 'corrente' (A → A, divide pela relação do TC), 'tensao' (kV → V, divide pela
    relação do TP) ou 'impedancia' (Ω → Ω, multiplica por RTC/RTP). As relações são
    adimensionais (ex.: TC 3000/1 → 3000; TP 500 kV/115 V → 4347,8). Sem a relação
    necessária devolve None: não se exporta secundário sem o dado.
    """
    if valor is None:
        return None
    if grandeza == 'corrente':
        return valor / rtc if rtc else None
    if grandeza == 'tensao':
        return valor * 1000.0 / rtp if rtp else None
    if grandeza == 'impedancia':
        return valor * rtc / rtp if (rtc and rtp) else None
    raise ValueError("grandeza deve ser 'corrente', 'tensao' ou 'impedancia'")


def _lacos(V, I, k0):
    """Impedâncias aparentes dos laços de interesse, em Ω primários, por tipo de falta."""
    Va, Vb, Vc = V['Va_c'], V['Vb_c'], V['Vc_c']
    Ia, Ib, Ic = I['Ia'], I['Ib'], I['Ic']
    IN = Ia + Ib + Ic

    def z(num, den):
        return num / den if abs(den) > 1e-12 else None
    return {'AG': z(Va, Ia + k0 * IN), 'BG': z(Vb, Ib + k0 * IN), 'CG': z(Vc, Ic + k0 * IN),
            'AB': z(Va - Vb, Ia - Ib), 'BC': z(Vb - Vc, Ib - Ic)}


_LACO_POR_FALTA = {'1FT': ('AG',), '2F': ('BC',), '2FT': ('BC', 'BG', 'CG'), '3F': ('AB',)}


def estudo_distancia(model, linha, terminal=None, criterios=None, dados=None,
                     cenarios=None, modo='completo', kinds=('3F', '1FT', '2F', '2FT'),
                     n1=True):
    """Estudo de distância de um terminal de linha.

    `linha` = (bf, bt, nc); `terminal` é a barra do relé (padrão: bf).
    `criterios`: alcances das zonas em Ω primários ou como múltiplo de Z1L, por exemplo
        {'Z1': 0.85, 'Z2': 1.2, 'Z3': 2.0, 'unidade': 'ZL'} ou {'Z1': 25.0, 'unidade': 'ohm'};
        e 'v_min_carga' (pu, padrão 0,95) e 'fp_carga' para a região de carga.
    `dados`: 'rtc' e 'rtp' (relações) para converter ao secundário.
    `cenarios`: casos do ANAREDE, para a capacidade de emergência da linha.

    Devolve dados da linha (Z1L, Z0L, k0, Kr, Kx), impedâncias aparentes por cenário para
    falta na barra remota e no fim de cada linha adjacente, os limites de alcance, o SIR
    como indicador, os alertas (capacitor série, circuito paralelo), as premissas e o
    estado.
    """
    from .protecao import _solver, _ramos_incidentes, _equipamento, _premissas_curto
    crit = dict(criterios or {})
    dados = dict(dados or {})
    bf, bt, nc = int(linha[0]), int(linha[1]), str(linha[2])
    rele = int(terminal) if terminal is not None else bf
    remoto = bt if rele == bf else bf
    kv = model.bus_kv.get(rele)
    zb = kv * kv / SB                                    # Ω de base
    S0 = _solver(model, None, modo)
    br = S0._find_branch(bf, bt, nc)
    if br is None or br['tipo'] != 'L':
        raise ValueError(f'linha {bf}-{bt}/{nc} não encontrada')
    z1 = zfin(br.get('R1'), br.get('X1')) * zb
    z0 = zfin(br.get('R0'), br.get('X0'))
    z0 = z0 * zb if z0 is not None else None
    k0 = (z0 - z1) / (3 * z1) if z0 is not None else 0j
    kr = ((z0.real - z1.real) / (3 * z1.real)) if (z0 is not None and abs(z1.real) > 1e-9) else None
    kx = ((z0.imag - z1.imag) / (3 * z1.imag)) if (z0 is not None and abs(z1.imag) > 1e-9) else None
    ang_l = np.angle(z1)

    def proj(z):
        """Componente da impedância aparente na direção da linha, em Ω."""
        return None if z is None else abs(z) * np.cos(np.angle(z) - ang_l)

    # --- cenários: rede completa e N-1 em torno dos dois terminais ---
    cen = [('rede completa', [])]
    if n1:
        vistos = set()
        for b in (rele, remoto):
            for r in _ramos_incidentes(model, b):
                eq = tuple(sorted(_equipamento(model, r, b)))
                if (bf, bt, nc) in eq or (bt, bf, nc) in eq or eq in vistos:
                    continue
                vistos.add(eq)
                cen.append((f'N-1 sem {r[0]}-{r[1]}/{r[2]}', list(eq)))

    # --- pontos de falta: barra remota e extremidade das linhas adjacentes ---
    adj, paralelos = [], []
    for r in _ramos_incidentes(model, remoto):
        if {r[0], r[1]} == {bf, bt} and r[2] == nc:
            continue
        outro = r[1] if r[0] == remoto else r[0]
        if outro == rele:
            paralelos.append(r)          # circuito paralelo: volta ao terminal do relé
            continue
        if model.bus_kv.get(outro):                      # só linhas e trafos com barra física
            adj.append((r, outro))

    medidas = {'barra remota': []}
    for r, outro in adj:
        medidas[f'fim de {r[0]}-{r[1]}/{r[2]}'] = []
    falhas = []
    for rot, drop in cen:
        try:
            S = S0 if not drop else _solver(model, drop, modo)
        except Exception as ex:
            falhas.append(f'{rot}: {type(ex).__name__}')
            continue
        pontos = [('barra remota', remoto)] + [(f'fim de {r[0]}-{r[1]}/{r[2]}', o)
                                               for r, o in adj
                                               if (r[0], r[1], r[2]) not in set(drop)]
        for nome, fb in pontos:
            for k in kinds:
                try:
                    V = S.bus_voltage(fb, rele, k)
                    I = S.branch_current(fb, rele, remoto, nc, k)
                except Exception as ex:
                    falhas.append(f'{rot}, {nome}, {k}: {type(ex).__name__}')
                    continue
                if not V or not I:
                    continue
                Vk = {c: V[c] * kv / np.sqrt(3) for c in ('Va_c', 'Vb_c', 'Vc_c')}   # kV
                lac = _lacos(Vk, I['fasores'], k0)                                   # Ω
                for laco in _LACO_POR_FALTA[k]:
                    zap = lac.get(laco)
                    if zap is not None and np.isfinite(zap):
                        medidas[nome].append(dict(cenario=rot, falta=k, laco=laco,
                                                  Z=zap, Zproj=proj(zap)))

    def extremo(lista, fn):
        vals = [m for m in lista if m['Zproj'] is not None and m['Zproj'] > 0]
        return fn(vals, key=lambda m: m['Zproj']) if vals else None

    adj_min = [extremo(v, min) for n, v in medidas.items() if n != 'barra remota']
    adj_max = [extremo(v, max) for n, v in medidas.items() if n != 'barra remota']
    adj_min = [x for x in adj_min if x]
    adj_max = [x for x in adj_max if x]
    lim_z2_teto = min(adj_min, key=lambda m: m['Zproj']) if adj_min else None
    ref_z3 = max(adj_max, key=lambda m: m['Zproj']) if adj_max else None
    remota = medidas['barra remota']

    # --- região de carga: capacidade de emergência e tensão mínima ---
    v_min = crit.get('v_min_carga', 0.95)
    s_emerg = None
    if cenarios:
        from .fluxo import carga_maxima
        cm = carga_maxima(cenarios, bf, bt, nc)
        if cm and cm.get('cap_emergencia_A'):
            s_emerg = np.sqrt(3) * kv * cm['cap_emergencia_A'] / 1000.0      # MVA
    z_carga = ((v_min * kv) ** 2 / s_emerg) if s_emerg else None

    # --- SIR como indicador: fonte atrás do relé, sem a linha protegida ---
    try:
        Ssir = _solver(model, [(bf, bt, nc)], 'sincronas')
        zs = Ssir.zth(rele)[0]
        sir = abs(zs * zb) / abs(z1) if zs is not None else None
    except Exception:
        sir = None

    # --- alertas: capacitor série e circuito paralelo ---
    alertas = []
    barras_viz = {rele, remoto} | {o for _, o in adj}
    caps = [c for c in getattr(model, 'caps', []) if {c['bf'], c['bt']} & barras_viz]
    if caps:
        alertas.append(f'{len(caps)} capacitor(es) série na linha ou nas adjacentes: '
                       f'sub e sobrealcance dependem do estado do banco e do MOV — '
                       f'avaliar com inserção e bypass e com estudo transitório')
    mut = [m for m in model.mutuas
           if {m['bf1'], m['bt1']} == {bf, bt} or {m['bf2'], m['bt2']} == {bf, bt}]
    if mut:
        alertas.append(f'{len(mut)} acoplamento(s) mútuo(s) de sequência zero com a linha: '
                       f'circuito paralelo — avaliar compensação de mútua no laço fase-terra')
    if paralelos:
        alertas.append(f'circuito paralelo entre os mesmos terminais '
                       f'({", ".join(f"{a}-{b}/{c}" for a, b, c in paralelos)}): altera infeed e '
                       f'outfeed e exige avaliar compensação de mútua; a falta no fim do '
                       f'paralelo é a própria barra local e não entra como adjacente')
    if kr is not None and kx is not None and abs(complex(kr, kx) - k0) > 1e-3 * abs(k0 or 1):
        alertas.append('Kr/Kx diferem das partes de k0: use a forma que o IED implementa')

    # --- margens, se os alcances foram informados ---
    zonas = {}
    unid = crit.get('unidade', 'ZL')
    for zn in ('Z1', 'Z2', 'Z3', 'Z4'):
        if zn not in crit:
            continue
        alc = crit[zn] * abs(z1) if unid == 'ZL' else float(crit[zn])
        d = dict(alcance_ohm=alc, alertas=[])
        if zn == 'Z1':
            d['margem_sobrealcance'] = (abs(z1) - alc) / abs(z1)
            if alc >= abs(z1):
                d['alertas'].append('zona 1 alcança a barra remota ou além')
        if zn == 'Z2':
            d['margem_cobertura'] = (alc - abs(z1)) / abs(z1)
            if alc <= abs(z1):
                d['alertas'].append('zona 2 não cobre a linha inteira')
            if lim_z2_teto:
                d['margem_adjacentes'] = (lim_z2_teto['Zproj'] - alc) / lim_z2_teto['Zproj']
                if alc >= lim_z2_teto['Zproj']:
                    d['alertas'].append(
                        f"zona 2 alcança o fim de linha adjacente "
                        f"({lim_z2_teto['cenario']}, {lim_z2_teto['falta']})")
        if zn in ('Z3', 'Z4') and z_carga:
            d['margem_carga'] = (z_carga - alc) / z_carga
            if alc >= z_carga:
                d['alertas'].append('alcance invade a região de carga de emergência')
        d['estado'] = 'faixa_inviavel' if d['alertas'] else 'validacao_pendente'
        rtc, rtp = dados.get('rtc'), dados.get('rtp')
        d['alcance_secundario_ohm'] = para_secundario(alc, 'impedancia', rtc, rtp)
        zonas[zn] = d

    prem = _premissas_curto(S0) + [
        'impedância aparente medida laço a laço sobre o mesmo estado de solução: AG para '
        'monofásica, BC para bifásica, BC/BG/CG para bifásica-terra, AB para trifásica',
        'compensação residual com k0 complexo; Kr e Kx informados à parte',
        'cenários: rede completa e N-1 de cada equipamento em torno dos dois terminais',
        'pontos de falta: barra remota e extremidade das linhas adjacentes',
        'comparação por módulo projetado na direção da linha; a região real depende da '
        'característica do IED e não está modelada',
        'SIR como indicador de desempenho, não como critério de proibição',
    ]
    if z_carga:
        prem.append(f'região de carga: capacidade de emergência do ANAREDE e tensão '
                    f'mínima de {v_min:.2f} pu')
    faltantes = []
    if not crit or not any(z in crit for z in ('Z1', 'Z2', 'Z3', 'Z4')):
        faltantes.append('alcances das zonas (critério do usuário)')
    if not cenarios:
        faltantes.append('casos do ANAREDE (capacidade de emergência para a região de carga)')
    if not (dados.get('rtc') and dados.get('rtp')):
        faltantes.append('rtc e rtp (conversão ao secundário)')
    return dict(
        linha=(bf, bt, nc), terminal=rele, remoto=remoto, kv=kv, modo=modo,
        Z1L_ohm=z1, Z0L_ohm=z0, k0=k0, Kr=kr, Kx=kx, SIR=sir,
        limites=dict(z1_teto_ohm=abs(z1), z2_piso_ohm=abs(z1),
                     z2_teto_ohm=lim_z2_teto['Zproj'] if lim_z2_teto else None,
                     z2_teto_condicao=lim_z2_teto and f"{lim_z2_teto['cenario']}, "
                                                      f"{lim_z2_teto['falta']}",
                     z3_referencia_ohm=ref_z3['Zproj'] if ref_z3 else None,
                     z3_referencia_condicao=ref_z3 and f"{ref_z3['cenario']}, "
                                                       f"{ref_z3['falta']}",
                     z_carga_min_ohm=z_carga),
        medidas=medidas, zonas=zonas, alertas=alertas, falhas=falhas,
        premissas=prem, faltantes=faltantes,
        exportacao=dict(exportavel=False,
                        motivos=['característica do IED não modelada: resultado é insumo']),
    )
