"""Compatibilidade: o parser do .ANA passou a se chamar `parser_anafas`.

Mantido para não quebrar `from lincc.model import AnaModel` em código existente. Prefira
`from lincc import AnaModel`.
"""
from .parser_anafas import *          # noqa: F401,F403
from .parser_anafas import AnaModel   # noqa: F401
