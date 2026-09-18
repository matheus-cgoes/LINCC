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
