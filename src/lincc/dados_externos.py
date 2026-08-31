"""Dados que o caso .ANA não contém e que a parametrização de proteção exige.

O arquivo de rede traz topologia e impedâncias — nada de relação de TC, placa de
equipamento, carga operativa ou ajuste de IED vizinho. Cada um desses bloqueia um
critério específico, e o motor não os estima: sem o dado, o critério fica pendente e é
declarado como tal.

Cálculo de curto-circuito não precisa de nada disto. A lista só é cobrada quando se pede
parametrização.

    from lincc.dados_externos import faltantes, RELATORIO
    print(RELATORIO(faltantes('linha', dados)))
"""
from __future__ import annotations

# chave -> (rótulo, unidade, o que bloqueia se faltar)
CATALOGO = {
    'carga_max_lt':     ('Carga máxima da LT', 'A ou MVA',
                         'pickup do 51 de linha (120% da carga máxima). O .ANA traz a '
                         'potência NOMINAL no campo MVA, que não é a carga máxima '
                         'operativa — confirme se serve ao critério'),
    'in_lt':            ('Corrente nominal da LT', 'A',
                         'limite inferior do SOTF'),
    'rtc':              ('Relação do TC do vão', '-',
                         'conversão para secundário e limite inferior do 67NT'),
    'in_tc':            ('Corrente nominal primária do TC', 'A',
                         'pickup do 67NT (10% de In do TC)'),
    'mva_trafo':        ('Potência nominal do transformador (placa)', 'MVA',
                         'pickup do 51 do trafo (150% da nominal) e estimativa de inrush'),
    'inrush':           ('Corrente de inrush', 'A ou múltiplo de In',
                         'limite inferior do 50 do trafo'),
    'mva_reator':       ('Potência nominal do reator', 'Mvar',
                         'corrente nominal de referência do reator'),
    'icc_disj':         ('Capacidade de interrupção do disjuntor', 'kA',
                         'verificação de suportabilidade'),
    'ajustes_vizinhos': ('Ajustes dos IEDs adjacentes', '-',
                         'verificação de coordenação com os elementos vizinhos'),
    'zf_sotf':          ('Impedância de falta para o critério do SOTF', 'ohm ou pu',
                         'limite superior do SOTF (80% do Icc mínimo remoto)'),
}

# o que cada tipo de estudo exige
EXIGIDOS = {
    'linha':          ('carga_max_lt', 'in_lt', 'rtc', 'in_tc', 'zf_sotf',
                       'icc_disj', 'ajustes_vizinhos'),
    'transformador':  ('mva_trafo', 'inrush', 'rtc', 'in_tc', 'icc_disj',
                       'ajustes_vizinhos'),
    'reator':         ('mva_reator', 'rtc', 'in_tc', 'icc_disj'),
    'barra':          ('rtc', 'in_tc', 'icc_disj'),
}


def da_base(model, bf, bt, nc):
    """Extrai da base o que ela puder fornecer para o elemento (bf,bt,nc).

    O .ANA traz a potência nominal no campo MVA do DCIR — a única grandeza de capacidade
    do arquivo. Onde estiver preenchida, dispensa o usuário de informar a nominal, e a
    corrente nominal sai dela: In = MVA·1000 / (√3 · kV).

    Não há carregamento MÁXIMO no arquivo: o campo é potência nominal, e o critério do 51
    de linha pede a carga máxima operativa, que costuma diferir. Quando só o MVA existe,
    o valor é devolvido com a chave `mva_nominal` e cabe a quem usa decidir se serve.
    """
    achado = {}
    for br in model.branches:
        if (br['bf'], br['bt'], str(br['nc'])) != (bf, bt, str(nc)):
            continue
        mva = br.get('MVA')
        if mva:
            kv = model.bus_kv.get(br['bf'], 0) or model.bus_kv.get(br['bt'], 0)
            achado['mva_nominal'] = mva
            if kv:
                achado['in_nominal'] = mva * 1000.0 / (3 ** 0.5 * kv)
            if br['tipo'] == 'L':
                achado['in_lt'] = achado.get('in_nominal')
            else:
                achado['mva_trafo'] = mva
        break
    return achado


def faltantes(tipo, fornecidos=None, model=None, elemento=None):
    """Lista o que falta para parametrizar `tipo`.

    `fornecidos` é o dict do usuário. Se `model` e `elemento=(bf,bt,nc)` forem dados, o
    que a base puder fornecer é considerado presente — não se pede ao usuário um dado que
    o arquivo já traz.
    """
    if tipo not in EXIGIDOS:
        raise ValueError(f"tipo deve ser um de {sorted(EXIGIDOS)}, recebido {tipo!r}")
    tem = dict(fornecidos or {})
    if model is not None and elemento is not None:
        for k, v in da_base(model, *elemento).items():
            tem.setdefault(k, v)
    return [k for k in EXIGIDOS[tipo] if tem.get(k) in (None, '')]


def RELATORIO(chaves, tipo=None):
    """Texto pedindo os dados que faltam, com o que cada um bloqueia."""
    if not chaves:
        return "Todos os dados externos necessários foram fornecidos."
    cab = (f"Faltam {len(chaves)} dado(s) para parametrizar"
           + (f" {tipo}" if tipo else "") + ". O .ANA não os contém:\n")
    linhas = []
    for k in chaves:
        rot, uni, bloq = CATALOGO[k]
        linhas.append(f"  {rot} [{uni}]\n      necessário para: {bloq}")
    return cab + "\n".join(linhas) + (
        "\n\nO cálculo de curto-circuito não depende destes dados e segue normalmente.")
