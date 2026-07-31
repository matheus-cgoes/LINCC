"""Parser do caso de rede em formato .ANA (colunas fixas).

Leitura para fins de interoperabilidade. Ver docs/formato-ana.md."""

from __future__ import annotations

import numpy as np, pickle, re
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from collections import defaultdict

import numpy as np
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components

SB = 100.0   # potência base, MVA

from ._base import num, _numf, _nunop, zfin, zn3


class AnaModel:
    """Modelo elétrico lido do .ANA. Guarda listas de elementos cruas para
    permitir contingências (filtragem) sem reparsear o arquivo."""
    def __init__(self, path):
        raw = open(path,'rb').read().decode('cp1252')
        L = raw.split('\r\n')
        self.bus_kv = {}
        self.bus_off = set()            # nb -> kV base
        self.bus_name = {}          # nb -> nome da barra
        self.branches = []          # dicts: tipo,bf,bt,nc,R1,X1,R0,X0,S1,S0,cd,cp,nome
        self.gens = []              # dicts: bus,R1,X1d,R0,X0,conn
        self.shunts = []            # dicts: bus,R1,X1,R0,X0,conn (tipo H)
        self.svc = []               # tipo E
        self.zig = []               # tipo Z
        self.caps = []              # tipo S
        self.mutuas = []            # dicts: bf1,bt1,n1,bf2,bt2,n2,RM,XM,pi1,pf1,pi2,pf2
        self.shl = []               # shunt de linha: bus,Q,conn,Rn,Xn
        self.eol = set()            # barras com fonte de corrente (eólico/FV/conversor)
        self._parse(L)

    def _conns(self, ln):
        # leitura posicional (layout DCIR): CD[80:82], CP[94:96]
        cd = ln[80:82].strip() if len(ln) > 80 else ''
        cp = ln[94:96].strip() if len(ln) > 94 else ''
        # empirico (validado vs gabarito): no CN do DCIR, 'Y' = estrela ISOLADA; 'YN' = aterrada
        cd = {'Y':'N'}.get(cd, cd) or 'YN'
        cp = {'Y':'N'}.get(cp, cp) or 'YN'
        return cd, cp

    def _aterr(self, ln):
        # impedâncias de aterramento de neutro: RNDE[82:88] XNDE[88:94] RNPA[96:102] XNPA[102:108]
        rnde = num(ln[82:88])  if len(ln) > 82  else None
        xnde = num(ln[88:94])  if len(ln) > 88  else None
        rnpa = num(ln[96:102]) if len(ln) > 96  else None
        xnpa = num(ln[102:108]) if len(ln) > 102 else None
        return rnde, xnde, rnpa, xnpa

    def _lado_equip(self, ln, bff, btt):
        # equipamento shunt registrado no BF (BT=0) usa CD/RNDE/XNDE; no BT usa CP/RNPA/XNPA
        cd, cp = self._conns(ln)
        rnde, xnde, rnpa, xnpa = self._aterr(ln)
        if btt:            # equipamento no BT (formato usual '0 <bus>')
            return cp, rnpa, xnpa
        return cd, rnde, xnde   # equipamento no BF ('<bus> 0')

    def _parse(self, L):
        # localizar blocos
        idx = {}
        for i, ln in enumerate(L):
            s = ln.strip()
            if s in ('DBAR','DCIR','DMUT','DMOV','DSHL','DEOL','DARE'):
                idx[s] = i
        if 'DBAR' not in idx or 'DCIR' not in idx:
            raise ValueError("caso sem bloco DBAR ou DCIR — arquivo .ANA inválido ou truncado")
        # blocos opcionais: o fim de cada bloco é o início do próximo que EXISTIR,
        # ou o fim do arquivo. Um caso sem DMUT/DMOV/DSHL/DEOL é legítimo.
        ordem = ('DBAR','DCIR','DMUT','DMOV','DSHL','DEOL','DARE')
        def fim_de(bloco):
            pos = ordem.index(bloco)
            for prox in ordem[pos+1:]:
                if prox in idx: return idx[prox]
            return len(L)
        # DBAR
        i = idx['DBAR']+1
        while i < fim_de('DBAR'):
            ln = L[i]; i += 1
            if not ln or ln.startswith('('): continue
            try: nb = int(ln[0:5])
            except: continue
            if nb == 99999: break              # sentinela de fim do DBAR, não é barra elétrica
            if ln[6:7].upper()=='D':          # barra DESLIGADA no DBAR
                self.bus_off.add(nb)
                continue                       # nao entra no caso (ANAFAS remove barra e ramos)
            vb = ln[31:36].strip()
            self.bus_kv[nb] = float(vb) if vb else 0.0
            self.bus_name[nb] = ln[9:21].strip()
        # DCIR
        i = idx['DCIR']+1
        end = fim_de('DCIR')
        while i < end:
            ln = L[i]; i += 1
            if not ln or ln.startswith('(') or ln.strip()=='99999': continue
            tipo = ln[16:17]
            if tipo not in ('L','T','G','H','S','Z','E'): continue
            if ln[6:7].upper() == 'D': continue  # CE='D'/'d' = equipamento desligado
            bf = ln[0:5].strip(); bt = ln[7:12].strip()
            R1,X1,R0,X0 = num(ln[17:23]),num(ln[23:29]),num(ln[29:35]),num(ln[35:41])
            S1,S0 = num(ln[47:52]), num(ln[52:57])
            nome = ln[41:47].strip()
            try: bff = int(bf)
            except: bff = None
            try: btt = int(bt)
            except: btt = None
            if tipo == 'G':
                nunop_str = ln[115:121].strip() if len(ln) > 115 else ''
                try: nunop = int(nunop_str.split()[-1]) if nunop_str else 1  # unidades OPERATIVAS
                except: nunop = 1
                _cn,rn,xn = self._lado_equip(ln, bff, btt)
                self.gens.append(dict(bus=btt if btt else bff, R1=R1, X1d=X1, R0=R0, X0=X0,
                                      nome=nome, nunop=nunop, conn=_cn,
                                      rn=rn, xn=xn))
            elif tipo == 'H':
                qstr = ln[176:185].strip() if len(ln) > 176 else ''
                qp = None
                if qstr:
                    try: qp = float(qstr)
                    except: qp = None
                shname = ln[41:47].strip()
                _cn,rn,xn = self._lado_equip(ln, bff, btt)
                nn = ln[115:121].split() if len(ln) > 115 else []
                try: nunop = int(nn[-1]) if nn else 1     # unidades operativas
                except: nunop = 1
                self.shunts.append(dict(bus=btt if btt else bff, X1=X1, X0=X0, R0=R0,
                                        Q=qp, nome=shname, conn=_cn,
                                        rn=rn, xn=xn, nunop=nunop))
            elif tipo == 'E':
                _cn,rn,xn = self._lado_equip(ln, bff, btt)
                self.svc.append(dict(bus=btt if btt else bff, X1=X1, X0=X0,
                                     conn=_cn, rn=rn, xn=xn))
            elif tipo == 'Z':
                _cn,rn,xn = self._lado_equip(ln, bff, btt)
                self.zig.append(dict(bus=btt if btt else bff, X0=X0, R0=R0, rn=rn, xn=xn))
            elif tipo == 'S':
                self.caps.append(dict(bf=bff, bt=btt, X1=X1, X0=X0))
            elif tipo == 'L':
                cd,cp = self._conns(ln)
                self.branches.append(dict(tipo='L', bf=bff, bt=btt, nc=ln[14:16].strip(),
                                          R1=R1,X1=X1,R0=R0,X0=X0,S1=S1,S0=S0))
            elif tipo == 'T':
                cd,cp = self._conns(ln)
                rnde,xnde,rnpa,xnpa = self._aterr(ln)
                nn = ln[115:121].split() if len(ln) > 115 else []
                try: tnun = int(nn[-1]) if nn else 1
                except: tnun = 1
                self.branches.append(dict(tipo='T', bf=bff, bt=btt, nc=ln[14:16].strip(),
                                          R1=R1,X1=X1,R0=R0,X0=X0,cd=cd,cp=cp,
                                          rnde=rnde,xnde=xnde,rnpa=rnpa,xnpa=xnpa,nunop=tnun))
        # DMUT (opcional: caso sem acoplamento mútuo é legítimo)
        i = idx.get('DMUT', -1)+1
        end = fim_de('DMUT') if 'DMUT' in idx else 0
        while i < end:
            ln = L[i]; i += 1
            if not ln or ln.startswith('('): continue
            try:
                bf1=int(ln[0:5]); bt1=int(ln[5:12]); n1=ln[12:16].strip()
                bf2=int(ln[16:21]); bt2=int(ln[21:28]); n2=ln[28:32].strip()
                RM=num(ln[32:38]); XM=num(ln[38:44])
            except: continue
            # régua DMUT: %I1[45:51] %F1[51:57] %I2[57:63] %F2[63:69]
            pi1,pf1,pi2,pf2 = num(ln[45:51]),num(ln[51:57]),num(ln[57:63]),num(ln[63:69])
            # %: parse direto (já em %); converter de volta (num divide por 100)
            def pc(v):
                if v is None: return None
                v = v*100 if v<=1.0001 else v
                return round(v,6)
            self.mutuas.append(dict(bf1=bf1,bt1=bt1,n1=n1 or '1',bf2=bf2,bt2=bt2,n2=n2 or '1',
                                    RM=RM,XM=XM,
                                    pi1=pc(pi1) if pi1 else 0,pf1=pc(pf1) if pf1 else 100,
                                    pi2=pc(pi2) if pi2 else 0,pf2=pc(pf2) if pf2 else 100))
        # DSHL
        if 'DSHL' in idx:
            i = idx['DSHL']+1; end = fim_de('DSHL')
            while i < end:
                ln = L[i]; i += 1
                if not ln or ln.startswith('('): continue
                try: bf=int(ln[0:5]); bt=int(ln[7:12])
                except: continue
                if ln[5:7].strip().upper() == 'D': continue  # CE='D'/'d': reator desligado
                # layout DSHL: NC[12:16] TERM[16] NG[17:19] Qpos[19:26]
                # Rn[28:34] Xn[34:40] NunNop[47:57]
                term = ln[16:17].strip()
                q = _numf(ln[19:26])
                # Rn/Xn são valores percentuais diretos (sem duas casas implícitas).
                rn = _numf(ln[28:34]) if len(ln) > 28 else None
                xn = _numf(ln[34:40]) if len(ln) > 34 else None
                nn = ln[47:57].split() if len(ln) > 47 else []
                try: nunop = int(nn[-1]) if nn else 1  # unidades operativas
                except: nunop = 1
                self.shl.append(dict(bf=bf,bt=bt,term=term,Q=q,conn='YN',
                                     rn=rn,xn=xn,nunop=nunop))
        # DEOL — fontes de corrente (não entram na Ybus)
        self.deol = {}
        if 'DEOL' in idx:
            i = idx['DEOL']+1; end = fim_de('DEOL')
            while i < end:
                ln = L[i]; i += 1
                if not ln or ln.startswith('(') or ln.strip()=='F': continue
                try: nb = int(ln[0:5])
                except: continue
                self.eol.add(nb)
                self.deol[nb]=dict(Imax_A=_numf(ln[23:30]),Vmin=_numf(ln[30:36]),
                                   fpcc=_numf(ln[36:41]),Pinic=_numf(ln[17:23]),
                                   nunop=_nunop(ln[51:54]) or _nunop(ln[47:51]))

