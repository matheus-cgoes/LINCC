"""LINCC — Linguagem Natural em Curto-Circuito.

Motor de curto-circuito para sistemas de transmissão: lê casos em formato .ANA, monta as redes
de sequência positiva e zero e calcula equivalentes de Thévenin e correntes de falta por
fatoração LU esparsa.

NÃO substitui ferramenta homologada. Ver README para isenção de responsabilidade e limites.
"""

from ._base import SB, num, zfin, zn3
from .model import AnaModel
from .solver import Solver, branches_at, recomposicao_87b

__version__ = "0.1.0"
__all__ = ["AnaModel", "Solver", "branches_at", "recomposicao_87b", "SB", "num", "zfin", "zn3"]
