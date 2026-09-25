"""Curvas de tempo inverso para funções de sobrecorrente (51, 51N, 67N, 51E, 51NE).

Duas famílias, com a mesma forma geral e constantes distintas:

    t(I) = TMS · [ A / ((I/Is)^B − 1) + C ]

IEC 60255-151 (padrão deste módulo) e IEEE C37.112. A escolha muda o resultado de forma
material: para I/Is = 5 na curva muito inversa, a IEC dá 3,375·TMS e a IEEE 0,187·TD — a
ordem de grandeza do multiplicador é outra, e comparar TMS com TD sem converter é erro
comum. Por isso a norma é sempre explícita no retorno, nunca implícita.

As duas famílias usam aqui a forma padronizada, sem fator adicional:

    t = TMS · [ A / ((I/Is)^B − 1) + C ]

Cada fabricante normaliza o multiplicador de tempo à sua maneira: há relés que dividem o
multiplicador por uma constante, e famílias com constantes próprias. Nenhuma dessas
normalizações é universal. O ajuste de um IED específico usa a curva documentada no manual
dele, registrada com `curva_do_ied()`, e não estas curvas genéricas.

    from lincc.curvas import tempo, CURVAS
    tempo(I=1200, Is=400, tms=0.2)                       # IEC muito inversa
    tempo(I=1200, Is=400, tms=0.2, curva='MI', norma='IEEE')
"""
from __future__ import annotations

import numpy as np

# (A, B, C) da forma t = TMS·[A/((I/Is)^B − 1) + C]
CURVAS = {
    'IEC': {
        'NI':  (0.14,  0.02, 0.0),      # normalmente inversa
        'MI':  (13.5,  1.0,  0.0),      # muito inversa   <- padrão dos estudos SGBH
        'EI':  (80.0,  2.0,  0.0),      # extremamente inversa
        'LTI': (120.0, 1.0,  0.0),      # tempo longo inversa
    },
    'IEEE': {
        'MODINV': (0.0515, 0.02, 0.114),   # moderadamente inversa
        'MI':     (19.61,  2.0,  0.491),   # muito inversa
        'EI':     (28.2,   2.0,  0.1217),  # extremamente inversa
    },
}

NORMA_PADRAO = 'IEC'
CURVA_PADRAO = 'MI'

_NOMES = {
    'NI': 'normalmente inversa', 'MI': 'muito inversa',
    'EI': 'extremamente inversa', 'LTI': 'tempo longo inversa',
    'MODINV': 'moderadamente inversa',
}


def constantes(curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """Devolve (A, B, C) da curva. Levanta ValueError com as opções válidas."""
    n = (norma or NORMA_PADRAO).upper()
    if n not in CURVAS:
        raise ValueError(f"norma deve ser uma de {sorted(CURVAS)}, recebido {norma!r}")
    c = (curva or CURVA_PADRAO).upper()
    if c not in CURVAS[n]:
        raise ValueError(f"curva {curva!r} não existe em {n}; disponíveis: "
                         f"{sorted(CURVAS[n])}")
    return CURVAS[n][c]


def tempo(I, Is, tms=1.0, curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """Tempo de operação, em segundos, para corrente `I` e pickup `Is` (mesma unidade).

    Devolve `inf` quando I ≤ Is: abaixo do pickup a unidade não opera. Aceita escalar ou
    array de correntes.
    """
    A, B, C = constantes(curva, norma)
    k = _FATOR_IED.get((norma or NORMA_PADRAO).upper(), 1.0)
    m = np.asarray(I, dtype=float) / float(Is)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = k * tms * (A / (m ** B - 1.0) + C)
        t = np.where(m > 1.0, t, np.inf)
    return float(t) if np.ndim(t) == 0 else t


def tms_para_tempo(I, Is, t_alvo, curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """TMS que produz `t_alvo` na corrente `I`. É o inverso de `tempo`.

    Usado para ajustar o 51 de linha ao tempo exigido pela coordenação com a zona 2.
    """
    A, B, C = constantes(curva, norma)
    m = float(I) / float(Is)
    if m <= 1.0:
        raise ValueError(f"I/Is = {m:.3f} não supera o pickup: a unidade não operaria")
    k = _FATOR_IED.get((norma or NORMA_PADRAO).upper(), 1.0)
    base = k * (A / (m ** B - 1.0) + C)
    if base <= 0:
        raise ValueError("curva degenerada para esta relação I/Is")
    return float(t_alvo) / base


def descreve(curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """Rótulo para relatório, com a norma explícita — ela nunca deve ficar implícita."""
    A, B, C = constantes(curva, norma)
    n = (norma or NORMA_PADRAO).upper(); c = (curva or CURVA_PADRAO).upper()
    return f"{n} {_NOMES.get(c, c)} (A={A}, B={B}, C={C})"


_FATOR_IED = {}
_FONTE_IED = {}


def curva_do_ied(fabricante, modelo, nome, A, B, C, fonte, secao, revisao, fator_td=1.0):
    """Registra a curva documentada de um IED: t = fator_td · TD · [A/((I/Is)^B − 1) + C].

    Exige fonte, seção e revisão do manual: curva sem documento não é usada para ajuste.
    Devolve (curva, norma) a passar em `tempo`, com norma = 'IED:<FABRICANTE>:<MODELO>'.
    """
    for campo, v in (('fonte', fonte), ('secao', secao), ('revisao', revisao)):
        if not v:
            raise ValueError(f"curva de IED sem {campo}: registro recusado")
    norma = f"IED:{fabricante}:{modelo}".upper()
    CURVAS.setdefault(norma, {})[nome.upper()] = (A, B, C)
    _FATOR_IED[norma] = float(fator_td)
    _FONTE_IED[(norma, nome.upper())] = dict(fonte=fonte, secao=secao, revisao=revisao)
    return nome.upper(), norma
