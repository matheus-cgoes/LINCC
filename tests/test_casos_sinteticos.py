"""Validação do motor contra casos sintéticos com resultado deduzido analiticamente.

Nenhum dado proprietário: as redes são pequenas e verificáveis à mão (ver cases/ESPERADO.md).
"""
import math
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
    """Regressão do bug de identidade de segmento.

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

    Regressão: a implementação anterior usava uma expressão aproximada e errava por ~85%
    contra o relatório de referência.
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
    """Regressão: .ANA normalizado para LF deve ser lido.

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

    Regressão da correção mais cara do projeto. O ANAFAS resolve cada fonte com o ângulo
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

    Regressão: com o campo MVA preenchido, In = MVA/(√3·kV) fica abaixo de Imax e
    escalar a curva por In subestima a injeção em exatamente Imax/In (1,50 no caso de
    referência). Onde MVA está ausente, In = Imax e o erro não aparece — foi por isso
    que passou despercebido em quase toda a base.
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
