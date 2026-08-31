"""Requisitos do ONS, Procedimentos de Rede, Submódulo 2.11 (revisão 2024.05).

O submódulo estabelece QUAIS funções de proteção devem existir por tipo de componente e
os tempos máximos de eliminação de falta. Ele **não** define critérios de ajuste — nada de
pickup, curva ou alcance de zona. Esses vêm das filosofias do ONS citadas nas referências
do próprio submódulo (RE 3/109/2011 para LT de alta e extra-alta tensão, RE 3/220/2012
para LT abaixo de 345 kV, RE 3/200/2012 para transformadores) e da especificação técnica
do agente.

Este módulo cobre o que o 2.11 define: escopo funcional e tempos. Os critérios de ajuste
entram como parâmetros do estudo, com os defaults do agente.

    from lincc.sm211 import funcoes_exigidas, tempo_maximo, verificar_escopo
"""
from __future__ import annotations

# item 4.x — funções exigidas por componente. (código, descrição, item do submódulo)
FUNCOES = {
    'linha': [
        ('21/21N', 'distância para faltas entre fases e fase-terra, temporizadores independentes por zona', '4.2.1.2(a)'),
        ('67N/67Q', 'sobrecorrente direcional residual e/ou de sequência negativa, com unidades instantânea e temporizada', '4.2.1.2(b)'),
        ('LPP',     'lógica de detecção de perda de potencial, para bloqueio e alarme', '4.2.1.2(c)'),
        ('SOTF',    'detecção de falta durante a energização da LT (switch onto fault)', '4.2.1.2(d)'),
        ('59',      'sobretensão com elementos instantâneos e temporizados independentes nas três fases', '4.2.1.2(e)'),
        ('68/78',   'bloqueio por oscilação de potência (68 OSB), disparo (68 OST) e perda de sincronismo (78 OST)', '4.2.1.2(f)'),
        ('79/25',   'dois esquemas de religamento automático e verificação de sincronismo, redundantes', '4.2.2.1'),
    ],
    'transformador': [
        ('87',      'diferencial percentual por fase, com restrição ou bloqueio para inrush e sobreexcitação', '4.4.1(a)(1)'),
        ('50/51',   'sobrecorrente instantânea e temporizada de fase, vinculada a CADA enrolamento', '4.4.1(a)(2)'),
        ('50/51R',  'sobrecorrente instantânea e temporizada residual, vinculada a CADA enrolamento', '4.4.1(a)(2)'),
        ('50/51N',  'sobrecorrente de neutro, vinculada a CADA ponto de aterramento', '4.4.1(a)(3)'),
        ('59G',     'sobretensão de sequência zero no terciário em delta, para alarme de falta à terra', '4.4.1(a)(4)'),
        ('87N',     'diferencial de terra restrita, vinculada a CADA ponto de aterramento', '4.4.1(a)(5)'),
        ('63/20',   'detecção de gás ou aumento de pressão interna, inclusive do comutador', '4.4.1(b)(1)'),
        ('26/49',   'sobretemperatura de óleo e de enrolamento, dois níveis cada', '4.4.1(b)(2,3)'),
    ],
    'reator': [
        ('87',      'diferencial por fase, com bloqueio ou restrição para inrush e sobreexcitação', '4.5.1(a)(1)'),
        ('87R',     'diferencial de terra restrita', '4.5.1(a)(2)'),
        ('50/51',   'sobrecorrente instantânea e temporizada de fase, do lado da LT ou da barra onde o reator está conectado', '4.5.1(a)(3)'),
        ('50/51R',  'sobrecorrente instantânea e temporizada residual, do mesmo lado', '4.5.1(a)(3)'),
        ('50/51R-N','sobrecorrente residual do lado do neutro, ou 50/51N', '4.5.1(a)(4)'),
        ('63/20',   'detecção de gás ou pressão interna', '4.5.1(b)(1)'),
        ('26/49',   'sobretemperatura de óleo e de enrolamento, dois níveis cada', '4.5.1(b)(2,3)'),
    ],
    'barra': [
        ('87B',     'princípio diferencial ou comparação de fase, por fase; exceto arranjo em anel', '4.6.1'),
    ],
    'disjuntor': [
        ('50BF',    'detecção de corrente do esquema de falha de disjuntor', '4.7.3(a)'),
        ('62BF',    'temporização do esquema de falha de disjuntor', '4.7.3(b)'),
    ],
}

# item 4.1.2 e 4.7.2 — tempos máximos, em ms
TEMPOS = {
    'eliminacao_acima_230kV': (70, '4.1.2(a)', 'tempo total de eliminação, defeito sólido sem falha de disjuntor'),
    'eliminacao_230kV':       (90, '4.1.2(b)', 'idem, em 230 kV'),
    'falha_disjuntor':        (250, '4.7.2', 'tempo total pelo esquema de falha de disjuntor, incluindo relés auxiliares e abertura'),
}


def tempo_maximo(kv, falha_disjuntor=False):
    """Tempo máximo de eliminação em ms, conforme o item 4.1.2 (ou 4.7.2)."""
    if falha_disjuntor:
        return TEMPOS['falha_disjuntor'][0]
    return TEMPOS['eliminacao_230kV'][0] if kv <= 230 else TEMPOS['eliminacao_acima_230kV'][0]


def funcoes_exigidas(tipo):
    """Funções que o Submódulo 2.11 exige para o componente."""
    if tipo not in FUNCOES:
        raise ValueError(f"tipo deve ser um de {sorted(FUNCOES)}, recebido {tipo!r}")
    return list(FUNCOES[tipo])


def exige_stub(arranjo):
    """Stub Bus Protection é exigida em disjuntor e meio, barra dupla com disjuntor duplo
    e anel — item 4.1.6, para falta no trecho que permanece energizado com a seccionadora
    da função de transmissão aberta e os disjuntores fechados."""
    a = (arranjo or '').lower()
    return any(k in a for k in ('disjuntor e meio', 'disjuntor duplo', 'anel'))


def verificar_escopo(tipo, previstas):
    """Compara as funções previstas no estudo com as exigidas. Devolve as que faltam.

    Verificação documental, não de ajuste: diz o que o Submódulo 2.11 exige e o estudo
    não contempla.
    """
    tem = {p.upper().replace(' ', '') for p in (previstas or [])}
    falta = []
    for cod, desc, item in funcoes_exigidas(tipo):
        alternativas = {c.upper().replace(' ', '') for c in cod.replace('/', ' ').split()}
        alternativas.add(cod.upper().replace(' ', ''))
        if not (alternativas & tem):
            falta.append((cod, desc, item))
    return falta
