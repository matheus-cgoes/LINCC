"""Parser do caso de fluxo de potência em formato .PWF (ANAREDE).

Colunas fixas, como o .ANA, com uma vantagem: cada bloco traz o cabeçalho de colunas na
linha seguinte ao seu nome, entre parênteses. As réguas abaixo foram derivadas desses
cabeçalhos e validadas contra os dados dos casos de referência do ONS — não são inferidas.

O que esta base fornece e a de curto-circuito não:

    * carregamento e capacidade por circuito, em TRÊS níveis (normal, emergência,
      equipamento). O .ANA traz só potência nominal;
    * tensão e ângulo de barra em regime permanente;
    * carga ativa e reativa por barra;
    * despacho de cada cenário — a geração varia entre carga leve/média/pesada e entre
      diurno e noturno, o que muda o nível de curto-circuito.

Leitura apenas: o caso publicado pelo ONS já vem convergido, e recalcular o fluxo seria
refazer o que o ANAREDE fez, com risco de divergir do caso oficial.

    from lincc import PwfModel
    P = PwfModel("cenario.PWF")
    P.barras[6640]['V']            # tensão em pu
    P.circuito(52, 46206, '1')     # com Cn, Ce, Cq
"""
from __future__ import annotations

from ._base import _numf


def _num(txt, escala=1.0):
    """Campo numérico do .PWF. Vazio devolve None; escala aplica divisor quando preciso."""
    s = (txt or '').strip()
    if not s:
        return None
    try:
        return float(s) / escala
    except ValueError:
        return None


class PwfModel:
    """Caso de fluxo de potência do ANAREDE.

    Atributos:
        barras    {num: dict(nome, V, A, Pg, Qg, Pl, Ql, Sh, area, tipo, estado)}
        bus_kv    {num: tensão base em kV}  — do bloco DGBT, via grupo de tensão
        circuitos lista de dict(bf, bt, nc, R, X, Mvar, Tap, Cn, Ce, Cq, estado)
        geradores {num: dict(Pmn, Pmx, Sno, estado)}
        titulo    linha do bloco TITU
    """

    # Réguas derivadas dos cabeçalhos dos próprios blocos (0-based, fim exclusivo).
    # DBAR: (Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)( Sh)Are(Vf)M
    # Conferido contra o .ANA nas mesmas barras: estado em [6:7] ('L'/'D'), tipo em
    # [7:8] ('1' PV, '2' referência, branco PQ) e grupo base de tensão em [8:10] — dois
    # caracteres, como no DGBT. Os grupos principais batem 100% com a tensão do .ANA.
    R_DBAR = dict(num=(0, 5), estado=(6, 7), tipo=(7, 8), grupo_base=(8, 10),
                  nome=(10, 22), V=(24, 28), A=(28, 32), Pg=(32, 37), Qg=(37, 42),
                  Qn=(42, 47), Qm=(47, 52), Bc=(52, 58), Pl=(58, 63), Ql=(63, 68),
                  Sh=(68, 73), area=(73, 76), Vf=(76, 80))
    # DLIN: (De )d O d(Pa )NcEPM( R% )( X% )(Mvar)(Tap)(Tmn)(Tmx)(Phs)(Bc  )(Cn)(Ce)Ns(Cq)
    # O cabeçalho é (De )d O d(Pa )NcEPM: o 'O' em [7] é o código de OPERAÇÃO de edição
    # do ANAREDE (adição, eliminação, modificação), e o ESTADO do circuito é o 'E' em
    # [17] ('D' desligado). Confundir os dois deixa em serviço circuitos desligados —
    # chaves de interligação com X de 0,001% entre barras com ângulos diferentes, que
    # produzem fluxo de milhões de MW. Conferido pelo balanço de potência ativa.
    R_DLIN = dict(bf=(0, 5), estado=(17, 18), bt=(10, 15), nc=(15, 17), R=(20, 26),
                  X=(26, 32), Mvar=(32, 38), Tap=(38, 43), Tmn=(43, 48), Tmx=(48, 53),
                  Phs=(53, 58), Bc=(58, 64), Cn=(64, 68), Ce=(68, 72), Cq=(74, 78))
    # DGER: (No ) O (Pmn ) (Pmx ) ( Fp) (FpR) (FPn) (Fa) (Fr) (Ag) ( Xq) (Sno) (Est)
    R_DGER = dict(num=(0, 5), estado=(6, 7), Pmn=(8, 14), Pmx=(15, 21), Fp=(22, 27),
                  Xq=(55, 60), Sno=(61, 66))

    def __init__(self, path):
        self.path = path
        self.titulo = ''
        self.barras = {}
        self.bus_kv = {}
        self.circuitos = []
        self.geradores = {}
        self._idx_cir = {}
        raw = open(path, 'rb').read().decode('cp1252', errors='replace')
        self._parse(raw.splitlines())

    # ------------------------------------------------------------------ #
    def _blocos(self, L):
        """Localiza os blocos: nome na linha, cabeçalho na seguinte, fim em 99999."""
        import re
        out = {}
        for i, ln in enumerate(L):
            s = ln.strip()
            if re.fullmatch(r'[A-Z]{4}( [A-Z]{4})?', s):
                out.setdefault(s.split()[0], []).append(i)
        return out

    def _registros(self, L, ini):
        """Linhas de dados de um bloco: da linha após o cabeçalho até o 99999."""
        for ln in L[ini + 2:]:
            if ln.strip() == '99999':
                return
            if not ln.strip() or ln.startswith('('):
                continue
            yield ln

    @staticmethod
    def _campo(ln, faixa):
        a, b = faixa
        return ln[a:b] if len(ln) > a else ''

    def _parse(self, L):
        bl = self._blocos(L)
        if 'TITU' in bl and bl['TITU'][0] + 1 < len(L):
            self.titulo = L[bl['TITU'][0] + 1].strip()

        # --- DBAR ---
        for i in bl.get('DBAR', []):
            for ln in self._registros(L, i):
                try:
                    nb = int(self._campo(ln, self.R_DBAR['num']))
                except ValueError:
                    continue
                d = {}
                for k, faixa in self.R_DBAR.items():
                    if k in ('num', 'nome', 'estado', 'tipo', 'grupo_base'):
                        continue
                    d[k] = _num(self._campo(ln, faixa))
                # V vem em pu x 1000 no arquivo
                if d.get('V') is not None:
                    d['V'] = d['V'] / 1000.0
                d['nome'] = self._campo(ln, self.R_DBAR['nome']).strip()
                d['estado'] = self._campo(ln, self.R_DBAR['estado']).strip() or 'L'
                d['tipo'] = self._campo(ln, self.R_DBAR['tipo']).strip()
                d['grupo_base'] = self._campo(ln, self.R_DBAR['grupo_base']).strip()
                self.barras[nb] = d

        # --- DGBT: tensão base por grupo ---
        grupos = {}
        for i in bl.get('DGBT', []):
            for ln in self._registros(L, i):
                g = ln[0:2].strip()            # grupo, dois caracteres
                v = _num(ln[2:8])              # tensão base, kV
                if g and v:
                    grupos[g] = v
        self.grupos_tensao = grupos
        for nb, d in self.barras.items():
            kv = grupos.get(d.get('grupo_base'))
            if kv:
                self.bus_kv[nb] = kv

        # --- DLIN ---
        for i in bl.get('DLIN', []):
            for ln in self._registros(L, i):
                try:
                    bf = int(self._campo(ln, self.R_DLIN['bf']))
                    bt = int(self._campo(ln, self.R_DLIN['bt']))
                except ValueError:
                    continue
                d = dict(bf=bf, bt=bt,
                         nc=self._campo(ln, self.R_DLIN['nc']).strip() or '1',
                         estado=self._campo(ln, self.R_DLIN['estado']).strip() or 'L')
                for k in ('R', 'X', 'Mvar', 'Tap', 'Tmn', 'Tmx', 'Phs', 'Cn', 'Ce', 'Cq'):
                    d[k] = _num(self._campo(ln, self.R_DLIN[k]))
                self.circuitos.append(d)
                self._idx_cir[(bf, bt, d['nc'])] = d

        # --- DGER ---
        for i in bl.get('DGER', []):
            for ln in self._registros(L, i):
                try:
                    nb = int(self._campo(ln, self.R_DGER['num']))
                except ValueError:
                    continue
                self.geradores[nb] = {k: _num(self._campo(ln, self.R_DGER[k]))
                                      for k in ('Pmn', 'Pmx', 'Fp', 'Xq', 'Sno')}
                self.geradores[nb]['estado'] = \
                    self._campo(ln, self.R_DGER['estado']).strip() or 'L'

    # ------------------------------------------------------------------ #
    def circuito(self, bf, bt, nc=None):
        """Circuito pelos terminais. Sem `nc`, devolve o primeiro; aceita ordem invertida."""
        if nc is not None:
            return (self._idx_cir.get((bf, bt, str(nc)))
                    or self._idx_cir.get((bt, bf, str(nc))))
        for d in self.circuitos:
            if (d['bf'], d['bt']) in ((bf, bt), (bt, bf)):
                return d
        return None

    def despachadas(self, limiar=0.0):
        """Barras com geração ativa acima do limiar, em MW.

        É o que distingue os cenários para efeito de curto-circuito: nos casos de
        referência o eixo dominante é diurno contra noturno (~2.200 barras de diferença,
        efeito solar), e não máxima contra mínima carga (~30).
        """
        return {nb: d['Pg'] for nb, d in self.barras.items()
                if d.get('Pg') is not None and abs(d['Pg']) > limiar}

    def carga_total(self):
        """Carga ativa e reativa somadas, em MW e Mvar."""
        p = sum(d['Pl'] for d in self.barras.values() if d.get('Pl'))
        q = sum(d['Ql'] for d in self.barras.values() if d.get('Ql'))
        return p, q

    def __repr__(self):
        return (f"PwfModel({self.titulo[:40]!r}: {len(self.barras)} barras, "
                f"{len(self.circuitos)} circuitos, {len(self.despachadas())} despachadas)")


def conciliar_bases(ana, pwf):
    """Casa as barras das duas bases e relata as diferenças.

    Casamento por NÚMERO, com verificação por NOME — a grafia varia entre as bases sem que
    o elemento seja outro. Nos casos de referência, 85,9% das barras do .PWF têm o mesmo
    número no .ANA, e 97,6% dos nomes coincidem na amostra conferida.

    As exclusivas têm padrão e não são erro: o .ANA detalha nós-estrela fictícios (kV = 0)
    e terminais de gerador em 13,8 kV que o fluxo agrega, e o .PWF traz barras de usina que
    o .ANA representa como registro de gerador, não como barra.

    Nunca case em silêncio: se um bay receber carregamento da barra errada, o pickup sai
    errado sem nada acusar. Chame isto antes de usar as duas bases juntas e registre o
    resultado no estudo.
    """
    a, p = set(ana.bus_kv), set(pwf.barras)
    comuns = a & p
    divergentes = []
    for b in comuns:
        na = (ana.bus_name.get(b) or '').strip()
        np_ = (pwf.barras[b].get('nome') or '').strip()
        if na[:8] != np_[:8] and na.replace('-', '')[:8] != np_.replace('-', '')[:8]:
            divergentes.append((b, na, np_))
    so_ana = sorted(a - p)
    return {
        'n_ana': len(a), 'n_pwf': len(p), 'comuns': len(comuns),
        'pct_pwf_casado': 100.0 * len(comuns) / len(p) if p else 0.0,
        'so_ana': so_ana, 'so_pwf': sorted(p - a),
        'so_ana_no_estrela': sum(1 for b in so_ana if ana.bus_kv.get(b) == 0),
        'nomes_divergentes': sorted(divergentes)[:50],
        'n_nomes_divergentes': len(divergentes),
    }
