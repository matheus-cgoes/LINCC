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
