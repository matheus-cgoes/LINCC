"""Helpers numéricos de leitura do formato de colunas fixas.

Escala: campo com ponto decimal vale direto; sem ponto, vale valor/100 (percentual com
duas casas implícitas). '999999' e notação científica representam impedância infinita."""

from __future__ import annotations

import numpy as np, pickle, re
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from collections import defaultdict

import re

import numpy as np
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components

SB = 100.0   # potência base, MVA

def num(s):
    s = s.strip()
    if not s: return None
    if '999999' in s: return float('inf')
    try:
        if '.' in s:
            return float(s)
        neg = s.startswith('-'); s2 = s.lstrip('-')
        if not s2: return None
        v = float(s2)/100.0
        return -v if neg else v
    except:
        return None

def _numf(s):
    s = s.strip()
    try: return float(s)
    except: return None

def _nunop(s):
    mm = re.findall(r'\d+', s)
    return int(mm[0]) if mm else 1

# ───────────────────────── PARSER .ANA ─────────────────────────

def zfin(r, x):
    """Retorna complex(r,x) em pu ou None se não finito (ramo aberto, 999999)."""
    if r is None: r = 0.0
    if x is None: x = 0.0
    if not (np.isfinite(r) and np.isfinite(x)):
        return None
    z = complex(r/100.0, x/100.0)
    if abs(z) < 1e-12:
        return None
    return z

def zn3(rn, xn):
    """3·Zn do aterramento de neutro em pu; 0 se não informado; None se infinito
    (neutro efetivamente isolado — sem caminho de terra)."""
    r = rn if rn is not None else 0.0
    x = xn if xn is not None else 0.0
    if not (np.isfinite(r) and np.isfinite(x)):
        return None
    return 3.0*complex(r/100.0, x/100.0)
