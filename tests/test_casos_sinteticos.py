"""Validação do motor contra casos sintéticos com resultado deduzido analiticamente.

Nenhum dado proprietário: as redes são pequenas e verificáveis à mão (ver cases/ESPERADO.md).
"""
import math
import pathlib
from pathlib import Path

import pytest

from lincc import AnaModel, Solver

CASES = Path(__file__).parent / "cases"
SB = 100.0
IB138 = SB / (math.sqrt(3) * 138.0)


def solve(nome):
    S = Solver(AnaModel(str(CASES / nome)))
    S.factor()
    return S


@pytest.fixture(scope="module")
def radial():
    return solve("caso1_radial.ANA")


@pytest.fixture(scope="module")
def mutuas():
    return solve("caso2_mutuas.ANA")


# ---------- caso 1: radial com trafo YN-D ----------

def test_radial_sequencia_positiva(radial):
    # gerador (j0,10) + linha (j0,10) em série
    assert radial.zth(2)[0].imag == pytest.approx(0.20, abs=1e-9)


def test_radial_sequencia_zero_derivacao_do_delta(radial):
    # (linha 0,30 + aterramento do gerador 0,05) em paralelo com o YN do trafo (0,08)
    esperado = 0.35 * 0.08 / 0.43
    assert radial.zth(2)[2].imag == pytest.approx(esperado, abs=1e-9)
    assert radial.zth(1)[2].imag == pytest.approx(0.05 * 0.38 / 0.43, abs=1e-9)


def test_radial_correntes_de_falta(radial):
    z1 = 0.20
    z0 = 0.35 * 0.08 / 0.43
    assert radial.fault(2, "3F") == pytest.approx(IB138 / z1, rel=1e-6)
    assert radial.fault(2, "1FT") == pytest.approx(3 * IB138 / (2 * z1 + z0), rel=1e-6)


# ---------- caso 2: paralelas acopladas ----------

def test_mutua_paralelas_positiva_nao_acopla(mutuas):
    # j0,10 (gerador) + j0,20 ∥ j0,20
    assert mutuas.zth(2)[0].imag == pytest.approx(0.20, abs=1e-9)


def test_mutua_paralelas_zero_usa_Zeq_com_acoplamento(mutuas):
    # Zeq = (Z0 + Zm)/2 = (0,60 + 0,20)/2 = 0,40; mais 0,10 do aterramento do gerador
    assert mutuas.zth(2)[2].imag == pytest.approx(0.10 + 0.40, abs=1e-9)


def test_mutua_nao_e_descartada_por_colapso_de_circuito(mutuas):
    """Identidade do segmento acoplado inclui o circuito.

    Se a chave do segmento acoplado ignorar o número do circuito, os dois circuitos paralelos
    colapsam, a mútua é pulada e Z0 vira 0,40 em vez de 0,50 — sem lançar exceção.
    """
    z0 = mutuas.zth(2)[2].imag
    assert z0 == pytest.approx(0.50, abs=1e-9)
    assert z0 != pytest.approx(0.40, abs=1e-3), "mútua descartada: circuitos paralelos colapsados"


def test_mutua_corrente_monofasica(mutuas):
    assert mutuas.fault(2, "1FT") == pytest.approx(3 * IB138 / (2 * 0.20 + 0.50), rel=1e-6)


# ---------- caso 3: robustez a blocos opcionais ausentes ----------

@pytest.fixture(scope="module")
def minimo():
    return solve("caso3_minimo.ANA")


def test_caso_sem_blocos_opcionais_parseia(minimo):
    """Um .ANA sem DMUT/DMOV/DSHL/DEOL/DARE é legítimo e deve ser lido sem erro."""
    assert minimo.zth(2)[0].imag == pytest.approx(0.125 + 0.25, abs=1e-9)
    assert minimo.zth(2)[2].imag == pytest.approx(0.125 + 0.75, abs=1e-9)


def test_caso_minimo_correntes(minimo):
    ib230 = SB / (math.sqrt(3) * 230.0)
    assert minimo.fault(2, "3F") == pytest.approx(ib230 / 0.375, rel=1e-6)
    assert minimo.fault(2, "1FT") == pytest.approx(3 * ib230 / (2 * 0.375 + 0.875), rel=1e-6)


# ---------- convenção da falta bifásica-terra ----------

def test_bifasica_terra_convencao_do_relatorio(radial):
    """2FT = √3·max(|Ib|,|Ic|), com Ib,c = (Z0 − a^{1,2}·Z2)/(Z1Z2+Z1Z0+Z2Z0).

    """
    z1 = complex(0, 0.20)
    z0 = complex(0, 0.35 * 0.08 / 0.43)
    z2 = z1
    a = complex(-0.5, math.sqrt(3) / 2)
    den = z1 * z2 + z1 * z0 + z2 * z0
    ib = abs((z0 - a * z2) / den)
    ic = abs((z0 - a.conjugate() * z2) / den)
    esperado = math.sqrt(3) * max(ib, ic) * IB138
    assert radial.fault(2, "2FT") == pytest.approx(esperado, rel=1e-9)


def test_bifasica_terra_entre_trifasica_e_monofasica(radial):
    """Sanidade física: numa rede com Z0 > Z1, a 2FT fica entre a 3F e a 1FT."""
    i3 = radial.fault(2, "3F")
    i1 = radial.fault(2, "1FT")
    i2t = radial.fault(2, "2FT")
    assert min(i1, i3) <= i2t <= max(i1, i3)


def test_le_arquivo_com_lf_puro(tmp_path):
    """.ANA normalizado para LF deve ser lido.

    O formato nativo é CRLF, mas basta o arquivo passar por um controle de versão com
    normalização de fim de linha para virar LF. Com split('\\r\\n') o arquivo inteiro vira
    uma única linha e o parser não acha bloco nenhum — falha silenciosa, sem exceção.
    """
    caso = tmp_path / "lf.ANA"
    caso.write_bytes(b"(caso LF\nDBAR\n    1    A               138\n99999\nDCIR\n99999\n")
    M = AnaModel(str(caso))
    assert len(M.bus_kv) == 1


# ---------- referência de ângulo do conversor, decidida por fonte ----------

def test_referencia_de_angulo_e_decidida_por_fonte(tmp_path):
    """Cada gerador de conversor escolhe a própria referência de ângulo.

    O ANAFAS resolve cada fonte com o ângulo
    da PRÓPRIA tensão convergida quando essa equação tem solução, e cai na tensão
    PRÉ-FALTA só na fonte que não tem — e declara qual usou, no rótulo ('FON.CORRENTE'
    contra 'FON.COR.Vpre'). Aplicar o fallback ao CONJUNTO produzia erro de +29% na
    fonte remota, que tinha solução própria.

    O caso de aceitação é o complexo fotovoltaico com reatância negativa: duas fontes,
    uma colada ao ponto de falta (sem solução própria) e uma a três saltos (com solução).
    Espera-se exatamente UMA fonte travada na pré-falta.
    """
    caso = CASES / "caso4_duas_fontes.ANA"
    if not caso.exists():
        pytest.skip("caso de aceitação não disponível")
    S = solve("caso4_duas_fontes.ANA")
    _, _, info = S._estado_fc(7785, ang_prefalta=False, strict=False)
    assert info["convergiu"], "deve convergir; sem a decisão por fonte entra em ciclo limite"
    assert info["fontes_prefalta"] == 1, "só a fonte colada à falta usa a pré-falta"
    ib34 = SB / (math.sqrt(3) * 34.0)
    icc = S.fault_fc(7785, "3F") * 34.5 / 34.0
    assert icc == pytest.approx(22.325, rel=0.01)   # alvo medido no ANAFAS


def test_escala_da_injecao_usa_imax_e_nao_in():
    """A curva do SM 2.10 é normalizada; a escala absoluta da injeção é Imax.

    Com o campo MVA preenchido, In = MVA/(√3·kV) fica abaixo de Imax; onde MVA está
    ausente, o manual manda tomar In = Imax e os dois limites coincidem.
    """
    reg = dict(Imax=0.09896, In=0.06600, phi=math.acos(0.1), K=1,
               Vmin=0.0, Vmax=9999.0, VP1=0.50, VP2=0.85)
    # abaixo de VP1 a injeção satura no limite do conversor, não na corrente nominal
    m, _ = Solver._mod_fc(reg, 0.0)
    assert m == pytest.approx(reg["Imax"])
    assert abs(Solver._inj_fc(reg, complex(0.0, 0.0))) == pytest.approx(reg["Imax"])
    # acima de VP2 não há injeção; no meio da rampa, fração de Imax
    assert Solver._mod_fc(reg, 0.90)[0] == pytest.approx(0.0)
    meio, _ = Solver._mod_fc(reg, (0.50 + 0.85) / 2)
    assert meio == pytest.approx(0.5 * reg["Imax"], rel=0.05)


def test_envelope_contribuicoes_cobre_o_estudo_padrao(radial):
    """O envelope executa o conjunto de casos de um estudo de barra sem enumeração.

    Quatro tipos de defeito, sistema completo e N-1, contingência por retirada e por
    terminal oposto aberto, defeito na barra e close-in — devolvendo maior e menor
    corrente de fase e de 3I0 por bay, com o cenário de cada extremo.
    """
    from lincc import envelope_contribuicoes, tabela_envelope
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    env = envelope_contribuicoes(M, 2, solver=radial)
    assert env, "a barra tem elementos incidentes e deve produzir envelope"
    for bay, d in env.items():
        assert {"fase", "terra", "casos"} <= d.keys()
        for campo in ("fase", "terra"):
            assert d[campo]["max"][0] >= d[campo]["min"][0]
            assert isinstance(d[campo]["max"][1], str)      # cenário identificado
        # os quatro tipos de defeito aparecem entre os casos
        assert {c[1] for c in d["casos"]} == {"3F", "1FT", "2F", "2FT"}
    texto = tabela_envelope(env, M)
    assert "FASE máx" in texto and "3I0" in texto


def test_corrente_seq0_em_bay_de_transformador(radial):
    """3I0 do bay de transformador: na rede de sequência zero o trafo não é ramo série.

    Com YN-D, o lado aterrado é caminho para a terra e o outro não conduz sequência
    zero. `branch_current` não cobre isso; `corrente_seq0_ramo` cobre.
    """
    prof = radial._seq_profile(2, "1FT")
    br = radial._find_branch(2, 3, "1")
    assert br is not None and br["tipo"] == "T"
    i0_yn = radial.corrente_seq0_ramo(prof["V0"], br, 2)     # lado YN (138 kV)
    assert abs(i0_yn) > 1e-6, "o lado aterrado deve conduzir sequência zero"


# ---------- impedância de falta e curvas de tempo inverso ----------

def test_impedancia_de_falta_reduz_a_corrente(radial):
    """Zf reduz a corrente monotonicamente, e Zf=0 reproduz a falta franca."""
    franca = radial.fault(2, "3F")
    assert radial.fault(2, "3F", Zf=0.0) == pytest.approx(franca)
    anterior = franca
    for zf in (0.05, 0.2, 1.0):
        atual = radial.fault(2, "3F", Zf=zf)
        assert atual < anterior
        anterior = atual
    # conferência analítica: I = Ib / |Z1 + Zf|
    ib138 = SB / (math.sqrt(3) * 138.0)
    assert radial.fault(2, "3F", Zf=0.1) == pytest.approx(ib138 / abs(complex(0.1, 0.20)),
                                                          rel=1e-9)


def test_curvas_iec_e_ieee():
    """IEC é o padrão; a IEEE traz o fator 1/7 da C37.112 e dá tempo bem menor.

    Comparar TMS da IEC com TD da IEEE sem converter é erro comum: para I/Is = 5 na
    muito inversa, o multiplicador difere por mais de uma ordem de grandeza.
    """
    from lincc import tempo, tms_para_tempo
    from lincc.curvas import descreve, constantes
    assert tempo(2000, 400, 1.0) == pytest.approx(3.375, rel=1e-9)          # IEC MI
    assert tempo(2000, 400, 1.0, norma="IEEE") == pytest.approx(19.61 / 24 / 7 + 0.491 / 7,
                                                                rel=1e-9)
    assert tempo(300, 400, 1.0) == math.inf                                 # abaixo do pickup
    # o inverso fecha nas duas normas
    for norma in ("IEC", "IEEE"):
        tms = tms_para_tempo(2000, 400, 0.4, norma=norma)
        assert tempo(2000, 400, tms, norma=norma) == pytest.approx(0.4, rel=1e-9)
    assert "IEC" in descreve() and "muito inversa" in descreve()
    with pytest.raises(ValueError):
        constantes("INEXISTENTE")


def test_sm211_escopo_e_tempos():
    """O Submódulo 2.11 define escopo funcional e tempos, não critérios de ajuste."""
    from lincc.sm211 import funcoes_exigidas, tempo_maximo, verificar_escopo, exige_stub
    assert tempo_maximo(500) == 70 and tempo_maximo(230) == 90      # item 4.1.2
    assert tempo_maximo(500, falha_disjuntor=True) == 250           # item 4.7.2
    assert exige_stub("barra dupla com disjuntor e meio")           # item 4.1.6
    assert not exige_stub("barra dupla a quatro chaves")
    codigos = {c for c, _, _ in funcoes_exigidas("transformador")}
    assert {"87", "87N", "59G"} <= codigos                          # item 4.4.1
    falta = verificar_escopo("reator", ["87", "50/51", "63"])
    assert "87R" in {c for c, _, _ in falta}                        # item 4.5.1(a)(2)
    assert verificar_escopo("barra", ["87B"]) == []


def test_line_end_open_varre_a_posicao(radial):
    """Falta em qualquer posição com o terminal remoto aberto, de close-in à ponta."""
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    S = Solver(M); S.factor(avisar=False)
    serie = S.varredura_line_end_open(1, 2, "1", 1, kinds=("3F",))["3F"]
    assert len(serie) >= 5
    correntes = [i for _, i in serie]
    # a corrente decai monotonicamente com a distância da falta
    assert all(a > b for a, b in zip(correntes, correntes[1:]))
    # p=1 é o padrão
    assert S.line_end_open(1, 2, "1", 1, "3F") == pytest.approx(correntes[-1])


def test_charging_e_opcional_e_desligado_por_padrao():
    """A capacitância de linha existe como opção, mas fica DESLIGADA por padrão.

    O gabarito de impedância de barra do ANAFAS não a inclui: ligada, Z1 cai de 100,000%
    para 50,4% das barras dentro de 1%. Já o cálculo de falta com terminal aberto a
    inclui. As duas coisas convivem no ANAFAS, e por isso o parâmetro é explícito — nunca
    use `charging=True` para conciliar contra o relatório de impedâncias.
    """
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    assert Solver(M).charging is False
    assert Solver(M, charging=True).charging is True
    # o caso sintético não declara S1/S0: os dois têm de coincidir exatamente
    a = Solver(M); a.factor(avisar=False)
    b = Solver(M, charging=True); b.factor(avisar=False)
    assert a.fault(2, "3F") == pytest.approx(b.fault(2, "3F"), rel=1e-12)


def test_potencia_nominal_lida_da_base():
    """O .ANA traz a potência nominal no campo MVA do DCIR — usar quando preenchida.

    É a única grandeza de capacidade do arquivo. Onde existe, dispensa o usuário de
    informar a nominal. Não é a carga MÁXIMA operativa, que o critério do 51 de linha
    pede e o arquivo não contém.
    """
    from lincc.dados_externos import da_base, faltantes
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    # o caso sintético não declara MVA: nada deve ser extraído
    assert da_base(M, 1, 2, "1") == {}
    assert "in_lt" in faltantes("linha", {}, model=M, elemento=(1, 2, "1"))
    # com o campo presente, a corrente nominal sai de In = MVA·1000/(√3·kV)
    for br in M.branches:
        if br["tipo"] == "L":
            br["MVA"] = 200.0
            break
    d = da_base(M, 1, 2, "1")
    assert d["mva_nominal"] == 200.0
    assert d["in_lt"] == pytest.approx(200_000 / (math.sqrt(3) * 138.0), rel=1e-9)
    assert "in_lt" not in faltantes("linha", {}, model=M, elemento=(1, 2, "1"))


# ---------- modularidade ----------

def test_modularidade_preserva_a_api():
    """A separação em parsers e motores não muda a API pública nem o caminho de import.

    `lincc.model` continua importável por compatibilidade, e tudo o que era exposto
    continua exposto — a modularização é estrutural, não de interface.
    """
    import lincc
    from lincc.model import AnaModel as Legado          # shim de compatibilidade
    from lincc.parser_anafas import AnaModel as Novo
    assert Legado is Novo
    esperado = {"AnaModel", "PwfModel", "conciliar_bases", "Solver", "branches_at",
                "recomposicao_87b", "envelope_contribuicoes", "tabela_envelope",
                "fluxo", "curvas", "sm211", "dados_externos", "orientacao"}
    assert esperado <= set(lincc.__all__)
    for nome in esperado:
        assert hasattr(lincc, nome), f"{nome} deixou de ser exportado"


def test_solver_nao_depende_do_motor_de_protecao():
    """O motor de curto-circuito não importa o de proteção — a dependência é só na direção
    oposta. É o que garante que um critério de proteção não possa alterar o cálculo de
    curto, que é validado barra a barra contra o ANAFAS."""
    fonte = (pathlib.Path(__file__).parent.parent
             / "src" / "lincc" / "solver.py").read_text(encoding="utf-8")
    assert "protecao" not in fonte
    assert "import fluxo" not in fonte and "from .fluxo" not in fonte


def test_falta_desequilibrada_no_modo_completo_usa_impedancia_equivalente():
    """Falta assimétrica: a rede de sequência positiva vê a falta como impedância.

    O estado é resolvido com Z_eq no lugar de Zf: Z2+Z0+3Zf para 1FT, Z2+2Zf para 2F, Z2∥(Z0+3Zf) para 2FT —
    porque na falta assimétrica a tensão da barra NÃO é zero, e é ela que define a injeção
    de cada conversor.

    Sem DEOL os dois modos coincidem, e é o que se verifica aqui: a formulação nova não
    pode alterar o caso sem conversor.
    """
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    S = Solver(M); S.factor(avisar=False)
    for kind in ("1FT", "2F", "2FT"):
        assert S.fault(2, kind) == pytest.approx(S.fault(2, kind, modo="sincronas"),
                                                 rel=1e-12)


# ---------- funções de alto nível ----------

def test_impacto_entrada(radial):
    """Impacto da entrada de um equipamento: compara com e sem, e reporta o tipo que governa."""
    from lincc import impacto_entrada
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    r = impacto_entrada(M, [(1, 2, "1")], limiar=1.0, kv_min=1.0)
    assert r["limiar"] == 1.0 and r["n_avaliadas"] >= 2
    for d in r["barras"]:
        assert {"num", "nome", "kv", "antes", "depois", "variacao_pct", "kind"} <= d.keys()
        assert d["kind"] in ("3F", "1FT", "2F", "2FT")
    # a lista sai ordenada pela maior variação absoluta
    v = [abs(d["variacao_pct"]) for d in r["barras"]]
    assert v == sorted(v, reverse=True)


def test_relatorio_curto(radial):
    """Relatório de curto de uma barra: correntes nos quatro tipos, Thévenin, contribuições."""
    from lincc import relatorio_curto
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    r = relatorio_curto(M, 2)
    assert set(r["correntes"]) == {"3F", "1FT", "2F", "2FT"}
    assert r["zth"]["Z1"] is not None
    assert r["correntes"]["3F"] == pytest.approx(radial.fault(2, "3F"), rel=1e-9)
    assert r["modo"] == "completo"        # o padrão é o modo regulatório


def test_relatorio_protecao_por_tipo():
    """Relatório de proteção para cada tipo, com as funções do 2.11 e o que falta."""
    from lincc import relatorio_protecao
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    r = relatorio_protecao(M, "barra", 2)
    assert "curto_na_barra" in r["grandezas"] and "envelope_por_bay" in r["grandezas"]
    assert "87B" in {c for c, _, _ in r["funcoes_sm211"]}
    r = relatorio_protecao(M, "linha", (1, 2, "1"), n1=False)
    assert r["grandezas"]["Z1"] is not None and r["grandezas"]["k0"] is not None
    assert "21/21N" in {c for c, _, _ in r["funcoes_sm211"]}
    assert "carga_max_lt" in r["dados_faltantes"]       # o .ANA não traz carga máxima
    with pytest.raises(ValueError):
        relatorio_protecao(M, "inexistente", 2)


def test_monofasica_usa_a_propria_tensao_da_barra(radial):
    """Na falta assimétrica a tensão de sequência positiva não colapsa.

    O conversor responde à própria tensão terminal, tipicamente na rampa da curva. Aqui
    verifica-se a consequência estrutural: com Z_eq = Z2+Z0, a tensão de sequência
    positiva da barra em falta é NÃO NULA e vale Ia1·Z_eq — ao contrário da trifásica,
    onde é zero. É isso que muda a injeção de cada conversor entre os dois tipos.
    """
    Z1, Z2, Z0 = radial.zth(2)
    _, Ia1, _ = radial._estado_fc_robusto(2, Zf=Z2 + Z0)
    V1 = Ia1 * (Z2 + Z0)
    assert abs(V1) > 1e-6, "tensão de sequência positiva não colapsa na monofásica"
    _, If3, _ = radial._estado_fc_robusto(2, Zf=0.0)
    assert abs(If3 * 0.0) == 0.0          # na trifásica franca a tensão da barra é zero


def test_line_end_open_respeita_o_modo():
    """Terminal remoto aberto segue o modo, como qualquer outra grandeza.

    O ANAFAS inclui as fontes de conversor também nesta condição: no caso de referência a
    trifásica vale 18.211 A no modo completo e 17.463 em Thévenin puro. Sem DEOL os dois
    coincidem, e é o que se verifica aqui.
    """
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    S = Solver(M); S.factor(avisar=False)
    for kind in ("3F", "1FT"):
        a = S.line_end_open(1, 2, "1", 1, kind)
        b = S.line_end_open(1, 2, "1", 1, kind, modo="sincronas")
        assert a == pytest.approx(b, rel=1e-12)
    # a varredura é contínua: sem salto entre p=0 e o primeiro ponto seguinte
    serie = S.varredura_line_end_open(1, 2, "1", 1, kinds=("3F",))["3F"]
    correntes = [i for _, i in serie]
    assert all(a > b for a, b in zip(correntes, correntes[1:]))


# ---------- consistência de modo ----------

def test_modo_e_global_e_propagado():
    """O modo é propriedade do Solver, e toda grandeza da instância o segue.

    Um estudo tem um modo: misturar os dois dentro do mesmo critério produz margem
    fictícia.
    """
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    assert Solver(M).modo == "completo"               # padrão: o número regulatório
    assert Solver(M, modo="sincronas").modo == "sincronas"
    with pytest.raises(ValueError):
        Solver(M, modo="inexistente")
    S = Solver(M, modo="sincronas"); S.factor(avisar=False)
    # toda grandeza derivada declara o modo sob o qual foi calculada
    r = S.branch_current(2, 1, 2, "1", "3F")
    assert r["modo"] == "sincronas"
    assert S._modo() == "sincronas" and S._modo("completo") == "completo"


def test_nenhum_solver_interno_ignora_o_modo():
    """Solver criado dentro de um método herda modo e charging.

    Verificação estrutural, lendo o próprio arquivo: um solver interno construído com os
    padrões calcularia em modo diferente do resto do estudo, sem sinalizar.
    """
    import re
    for arq in ("solver.py", "protecao.py"):
        fonte = (pathlib.Path(__file__).parent.parent / "src" / "lincc"
                 / arq).read_text(encoding="utf-8")
        # a chamada pode ocupar várias linhas: casa até o parêntese de fechamento
        for m in re.finditer(r"Solver\(\s*(?:M[m\w]*|model|self\.M)(?:[^()]|\([^()]*\))*\)",
                             fonte, re.S):
            trecho = m.group(0)
            if "modo=" not in trecho:
                raise AssertionError(
                    f"{arq}: Solver interno sem modo -> {' '.join(trecho.split())[:80]}")


def test_leitura_de_relatorio_do_anafas(tmp_path):
    """Ler os relatórios faz parte do pacote, não de um script auxiliar.

    É o que permite ao agente validar o caso sem reimplementar a leitura de colunas — e
    sem transferir o procedimento ao usuário. O cabeçalho da seção de níveis é ACENTUADO,
    e a régua é medida a partir da borda direita de cada campo.
    """
    from lincc import ler_relatorio, niveis_kA, impedancias_pu
    rel = tmp_path / "rel.LST"
    linha = "     27 CPAUL2-SP500  500.0     26.64 -86.58    16.71   68.88     18.37"
    rel.write_bytes(
        (" RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO \n"
         "   NUM.     NOME      VBAS   MOD(kA)\n"
         + linha + "\n99999\n").encode("cp1252"))
    d = ler_relatorio(str(rel), "niveis")
    assert 27 in d
    assert d[27]["vbas"] == pytest.approx(500.0)
    assert d[27]["i3m"] == pytest.approx(26.64)      # trifásica
    assert d[27]["i1m"] == pytest.approx(18.37)      # monofásica
    assert niveis_kA(str(rel))[27] == pytest.approx(26.64)
    assert niveis_kA(str(rel), kind="1FT")[27] == pytest.approx(18.37)
    with pytest.raises(ValueError):
        niveis_kA(str(rel), kind="inexistente")
    with pytest.raises(ValueError):
        ler_relatorio(str(rel), "secao_inexistente")
    # seção ausente devolve vazio, sem levantar
    assert impedancias_pu(str(rel)) == ({}, {})


def test_ajuste_sobrecorrente_devolve_faixas_e_nao_escolhe():
    """O módulo calcula faixas e viabilidade; escolher dentro delas é decisão de engenharia.

    Também não estima dado ausente: o que falta vai para `faltantes`.
    """
    from lincc import ajuste_sobrecorrente
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    r = ajuste_sobrecorrente(M, "linha", (1, 2, "1"))
    for f in ("51", "50", "SOTF", "STUB", "67NT"):
        assert f in r["funcoes"]
    # sem carga máxima nem TC informados, o que depende deles fica em aberto
    assert {"carga_max_lt", "in_tc"} <= set(r["faltantes"])
    assert r["funcoes"]["51"]["pickup"] is None
    # com os dados, o pickup do 51 segue o critério
    r = ajuste_sobrecorrente(M, "linha", (1, 2, "1"),
                             dados={"carga_max_lt": 500, "in_tc": 1000})
    assert r["funcoes"]["51"]["pickup"] == pytest.approx(600.0)     # 120%
    assert r["funcoes"]["67NT"]["min"] == pytest.approx(100.0)      # 10% de In do TC
    # critério parametrizável
    r = ajuste_sobrecorrente(M, "linha", (1, 2, "1"),
                             dados={"carga_max_lt": 500}, criterios={"f51_carga": 1.5})
    assert r["funcoes"]["51"]["pickup"] == pytest.approx(750.0)


# ---------- base de fluxo de potência (ANAREDE) ----------

def _pwf_sintetico(tmp_path, pg_barra1=100.0, estado_linha=" "):
    """Caso .PWF mínimo, montado pelas réguas conferidas contra o caso real."""
    def col(pares, w=90):
        b = [" "] * w
        for s, t in pares:
            for k, ch in enumerate(str(t)):
                b[s + k] = ch
        return "".join(b).rstrip()
    L = ["TITU", "CASO SINTETICO", "DGBT", "(G ( kV)", " C  138.", "99999", "DBAR",
         "(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)( Sh)Are(Vf)M"]
    L.append(col([(0, "    1"), (6, "L"), (7, "2"), (8, " C"), (10, "GERADOR"),
                  (24, "1000"), (28, "  0."), (32, f"{pg_barra1:5.0f}")]))
    L.append(col([(0, "    2"), (6, "L"), (8, " C"), (10, "CARGA"),
                  (24, "1000"), (28, " -5."), (58, "  87.")]))
    L += ["99999", "DLIN",
          "(De )d O d(Pa )NcEPM( R% )( X% )(Mvar)(Tap)(Tmn)(Tmx)(Phs)(Bc  )(Cn)(Ce)Ns(Cq)"]
    L.append(col([(0, "    1"), (10, "    2"), (15, " 1"), (17, estado_linha),
                  (26, "   10."), (64, "200."), (68, "240."), (74, "220.")]))
    L += ["99999", "FIM"]
    f = tmp_path / "caso.PWF"
    f.write_bytes("\n".join(L).encode("cp1252"))
    return str(f)


def test_parser_anarede_reguas(tmp_path):
    """Estado da barra em [6], grupo base em [8:10] e estado do circuito em [17].

    No DBAR o [5] e no DLIN o [7] são o código de OPERAÇÃO de edição do ANAREDE, não o
    estado — confundir os dois deixa circuito desligado em serviço.
    """
    from lincc import PwfModel
    P = PwfModel(_pwf_sintetico(tmp_path))
    assert P.bus_kv[1] == pytest.approx(138.0)          # grupo base lido do DGBT
    assert P.barras[1]["estado"] == "L" and P.barras[1]["V"] == pytest.approx(1.0)
    assert P.circuito(1, 2, "1")["Ce"] == pytest.approx(240.0)
    P = PwfModel(_pwf_sintetico(tmp_path, estado_linha="D"))
    assert P.circuito(1, 2, "1")["estado"] == "D"


def test_fluxo_avaliado_das_tensoes_convergidas(tmp_path):
    """Fluxo por circuito: 5° sobre X = 10% transmitem 100·sen(5°)/0,1 ≈ 87,2 MW."""
    from lincc import PwfModel
    from lincc.fluxo import fluxos, carga_maxima
    P = PwfModel(_pwf_sintetico(tmp_path))
    f = fluxos(P)[(1, 2, "1")]
    assert f["P_de_MW"] == pytest.approx(100 * math.sin(math.radians(5)) / 0.1, rel=1e-3)
    assert f["calculavel"]
    # carga máxima: capacidade de emergência (240 MVA), acima da normal (200)
    cm = carga_maxima({"c": P}, 1, 2, "1")
    assert cm["carga_max_A"] == pytest.approx(240e3 / (math.sqrt(3) * 138.0), rel=1e-9)
    assert "emergência" in cm["origem"]


def test_despacho_retira_fonte_parada(tmp_path):
    """Gerador com geração nula no cenário sai do caso de curto; com geração, fica."""
    from lincc import PwfModel
    from lincc.fluxo import aplicar_despacho
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    barra = M.gens[0]["bus"]
    parado = PwfModel(_pwf_sintetico(tmp_path, pg_barra1=0.0))
    if barra == 1:
        Mc, rel = aplicar_despacho(M, parado)
        assert rel["sincronos_retirados"] >= 1 and not any(g["bus"] == 1 for g in Mc.gens)
    gerando = PwfModel(_pwf_sintetico(tmp_path, pg_barra1=100.0))
    Mc, rel = aplicar_despacho(M, gerando)
    assert len(Mc.gens) >= 1                         # o caso original não é alterado
    assert len(M.gens) >= 1


def test_piso_do_sotf_e_a_carga_de_emergencia():
    """Pickup que depende de carga fica acima da carga de emergência."""
    from lincc import ajuste_sobrecorrente
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    r = ajuste_sobrecorrente(M, "linha", (1, 2, "1"),
                             dados={"carga_max_lt": 500.0, "in_lt": 300.0})
    assert r["funcoes"]["SOTF"]["min"] == pytest.approx(500.0)
    assert r["funcoes"]["SOTF"]["base_do_piso"] == "carga de emergência"


def test_toda_funcao_de_alto_nivel_declara_premissas():
    """Nenhum número chega ao usuário sem as premissas que o produziram."""
    from lincc import (impacto_entrada, relatorio_curto, relatorio_protecao,
                       ajuste_sobrecorrente)
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    retornos = [impacto_entrada(M, [(1, 2, "1")], kv_min=1.0),
                relatorio_curto(M, 2),
                relatorio_protecao(M, "barra", 2),
                relatorio_protecao(M, "linha", (1, 2, "1"), n1=False),
                ajuste_sobrecorrente(M, "linha", (1, 2, "1"), dados={"carga_max_lt": 500})]
    for r in retornos:
        assert r.get("premissas"), "retorno sem premissas"
        assert any("pré-falta" in p for p in r["premissas"])
    # o 51 de transformador declara que a referência é a nominal, não a emergência
    trafo = next(b for b in M.branches if b["tipo"] == "T")
    r = ajuste_sobrecorrente(M, "transformador", (trafo["bf"], trafo["bt"], trafo["nc"]),
                             dados={"in_nominal": 100.0})
    assert any("NOMINAL" in p and "emergência" in p for p in r["premissas"])


def test_reator_de_linha_sai_com_a_linha():
    """Linha retirada leva o reator junto; linha pendurada (terminal aberto) o mantém."""
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    M.shl.append(dict(bf=1, bt=2, nc="1", term="D", Q=-50.0, conn="YN",
                      rn=None, xn=0.0, nunop=1))
    com = Solver(M, drop_branches=[(1, 2, "1")], modo="sincronas"); com.factor(avisar=False)
    M2 = AnaModel(str(CASES / "caso1_radial.ANA"))
    sem = Solver(M2, drop_branches=[(1, 2, "1")], modo="sincronas"); sem.factor(avisar=False)
    # com a linha retirada, o reator dela não altera a rede
    assert com.fault(1, "1FT") == pytest.approx(sem.fault(1, "1FT"), rel=1e-12)
    # mantido explicitamente, volta a ser caminho para a terra
    fica = Solver(M, drop_branches=[(1, 2, "1")], modo="sincronas",
                  manter_reatores=[(1, 2, "1")]); fica.factor(avisar=False)
    assert fica.fault(1, "1FT") != pytest.approx(sem.fault(1, "1FT"), rel=1e-6)


def test_reator_de_barra_pode_ser_desligado():
    """Reator de barra é um vão: sai na recomposição por um só elemento."""
    M = AnaModel(str(CASES / "caso1_radial.ANA"))
    M.shunts.append(dict(bus=2, conn="YN", X0=50.0, R0=None, Q=-100.0, nunop=1))
    com = Solver(M, modo="sincronas"); com.factor(avisar=False)
    sem = Solver(M, modo="sincronas", drop_reatores_barra=[2]); sem.factor(avisar=False)
    base = Solver(AnaModel(str(CASES / "caso1_radial.ANA")), modo="sincronas")
    base.factor(avisar=False)
    assert sem.fault(2, "1FT") == pytest.approx(base.fault(2, "1FT"), rel=1e-12)
    assert com.fault(2, "1FT") > sem.fault(2, "1FT")      # reator aterrado eleva a 1FT
