"""LINCC — Linguagem Natural em Curto-Circuito (arquivo único, autocontido).

GERADO por ferramentas/gerar_bundle.py a partir de src/lincc/. Não editar à mão: corrija no
pacote e regenere. Requer apenas numpy e scipy.

    from lincc_bundle import AnaModel, Solver
    M = AnaModel("caso.ANA"); S = Solver(M); S.factor()
    S.fault(BARRA, "3F")

NÃO substitui ferramenta homologada. Ver README para isenção de responsabilidade e limites.
"""

from __future__ import annotations

import numpy as np, pickle, re
import json as _json
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from collections import defaultdict

SB = 100.0   # potência base, MVA


# ===================== helpers de leitura =====================

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


# ===================== parser do .ANA =====================

class AnaModel:
    """Modelo elétrico lido do .ANA. Guarda listas de elementos cruas para
    permitir contingências (filtragem) sem reparsear o arquivo."""
    def __init__(self, path):
        raw = open(path,'rb').read().decode('cp1252')
        # Arquivos .ANA nativos são CRLF, mas basta passarem por um sistema de controle de
        # versão com normalização de fim de linha para virarem LF — e aí um split por
        # '\r\n' devolve o arquivo inteiro numa única "linha", sem erro visível: o parser
        # simplesmente não acha bloco nenhum. splitlines() aceita as duas formas.
        L = raw.splitlines()
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
        # DEOL — geradores síncronos com conversor pleno: fontes de corrente de sequência
        # positiva, NÃO entram na Ybus. Régua conforme manual do ANAFAS, apêndice A33-A34.
        # Uma barra pode ter VÁRIOS registros (grupos NG distintos, modelos diferentes de
        # aerogerador): a estrutura é lista por barra, e as injeções se somam.
        self.deol = {}
        if 'DEOL' in idx:
            i = idx['DEOL']+1; end = fim_de('DEOL')
            while i < end:
                ln = L[i]; i += 1
                if not ln or ln.startswith('(') or ln.strip() in ('F','99999'): continue
                try: nb = int(ln[0:5])
                except: continue
                if len(ln) > 6 and ln[6:7].upper() == 'D':
                    continue                    # gerador desligado: desconsiderado
                def _f(a, b, dflt=None):
                    v = _numf(ln[a:b]) if len(ln) > a else None
                    return dflt if v is None else v
                reg = dict(
                    K      = int(ln[9:10]) if len(ln) > 9 and ln[9:10].strip().isdigit() else 0,
                    NG     = _nunop(ln[14:16]) or 1,
                    Pinic  = _f(17, 23),
                    Imax_A = _f(23, 29),         # A rms, POR UNIDADE (manual: 3600 A x 25 = 90 kA)
                    Vmin   = _f(29, 35, 0.0),    # pu; abaixo disso o gerador se desconecta
                    fpcc   = _f(35, 41, 1.0),    # cos(phi_cc); SINAL é convenção: + indutivo
                    nome   = ln[41:47].strip() if len(ln) > 41 else '',
                    NUN    = _nunop(ln[48:51]) or 1,
                    nunop  = _nunop(ln[51:54]) or _nunop(ln[48:51]) or 1,   # NOP em operação
                    fppre  = _f(55, 61, 1.0),
                    Vmax   = _f(62, 68, 9999.0),
                    MVA    = _f(87, 92),
                    VP1    = _f(133, 137, 0.50), # curva ΔIq×V+ (usada quando K=1)
                    VP2    = _f(138, 142, 0.85),
                )
                self.eol.add(nb)
                self.deol.setdefault(nb, []).append(reg)


# ===================== Ybus, LU e faltas =====================

class Solver:
    def __init__(self, model, drop_branches=None, drop_gens=None, block_btb=True,
                 dispatch_file=None):   # despacho inferido OBSOLETO: estados do DBAR ('d') cobrem o caso
        self.M = model
        self.dropB = set(drop_branches) if drop_branches else set()   # {(bf,bt,nc)}
        self.dropG = set(drop_gens) if drop_gens else set()   # {bus}
        # Despacho inferido: usinas fora de operação na configuração-base do caso
        # (inferido barra a barra contra o relatório de dados de curto do ANAFAS).
        if dispatch_file:
            import os, json as _json
            if os.path.exists(dispatch_file):
                try:
                    self.dropG |= {x['bus'] for x in _json.load(open(dispatch_file))}
                except Exception:
                    pass
        # Estações back-to-back HVDC desacoplam os dois lados AC para curto: o trafo conversor
        # que liga a barra "BTB" ao restante não conduz corrente de falta AC. Bloquear.
        if block_btb:
            btb_buses = {b for b,nm in getattr(model,'bus_name',{}).items() if 'BTB' in nm}
            if not btb_buses:  # fallback: usar nomes do .ANA se bus_name não existir
                btb_buses = self._btb_from_names()
            for br in model.branches:
                if br['tipo']=='T' and (br['bf'] in btb_buses or br['bt'] in btb_buses):
                    self.dropB.add((br['bf'],br['bt'],br['nc']))
        self._index()
        self._build()

    def _btb_from_names(self):
        # identifica barras BTB pelo nome no modelo, se disponível
        names = getattr(self.M,'bus_name',None) or {}
        return {b for b,nm in names.items() if 'BTB' in str(nm)}

    def _index(self):
        buses = sorted(self.M.bus_kv.keys())
        self.BUS = buses
        self.IDX = {b:i for i,b in enumerate(buses)}
        self.N = len(buses)

    def conn_type(self, c): return c if c in ('YN','D','N') else 'YN'

    def _regularize_floating_components(self, Y, eps=1e-8, tol=1e-11):
        """Adiciona a fuga numérica apenas em componentes sem caminho físico
        para a referência. Componentes já aterrados/fontes não são perturbados.

        A identificação usa a conectividade da matriz e as somas de linha: carimbos
        série têm soma nula; qualquer shunt/fonte física produz soma não nula.
        Retorna (Y_regularizada, metadados).
        """
        Yc = csc_matrix(Y)
        pat = Yc.copy()
        pat.data = np.ones(pat.nnz, dtype=np.int8)
        ncomp, labels = connected_components(pat, directed=False, connection='weak')
        rowsum = np.asarray(Yc.sum(axis=1)).ravel()
        floating = []
        for comp in range(ncomp):
            ids = np.flatnonzero(labels == comp)
            if ids.size and np.max(np.abs(rowsum[ids])) < tol:
                floating.append(comp)
        mask = np.isin(labels, np.asarray(floating, dtype=int))
        if np.any(mask):
            Ym = Yc.tolil(copy=True)
            for i in np.flatnonzero(mask):
                Ym[i, i] += eps
            Yc = csc_matrix(Ym)
        meta = dict(components=int(ncomp), floating_components=len(floating),
                    regularized_nodes=int(mask.sum()), eps=float(eps), tol=float(tol))
        return Yc, meta

    def _build(self):
        N = self.N; IDX = self.IDX
        YP = lil_matrix((N,N), dtype=complex)
        # ----- componentes seq+ -----
        for br in self.M.branches:
            bf,bt = br['bf'],br['bt']
            if bf not in IDX or bt not in IDX: continue
            if (bf,bt,br['nc']) in self.dropB: continue
            z = zfin(br['R1'], br['X1'])
            if z is None: continue
            nun = (br.get('nunop',1) or 1) if br['tipo']=='T' else 1   # bancos de trafo
            i,j = IDX[bf],IDX[bt]; ys=nun/z
            YP[i,j]-=ys; YP[j,i]-=ys; YP[i,i]+=ys; YP[j,j]+=ys
            # Modelagem PECO (sem tensão pré-falta): line charging NÃO é representado
            # na seq+ (manual ANAFAS seç. 2.2/2.5 — capacitância de linha só é modelada
            # no formato com tensão pré-falta).
        for g in self.M.gens:
            b=g['bus']
            if b not in IDX or b in self.dropG: continue
            z=zfin(g['R1'], g['X1d'])
            if z is None: continue
            nun=g.get('nunop',1) or 1     # N unidades idênticas em paralelo -> admitância x N
            YP[IDX[b],IDX[b]] += nun/z
        for c in self.M.caps:
            bf,bt=c['bf'],c['bt']
            if bf not in IDX or bt not in IDX: continue
            x=(c['X1'] or 0)/100
            if abs(x)<1e-12 or not np.isfinite(x): continue
            i,j=IDX[bf],IDX[bt]; ys=1/(1j*x)
            YP[i,j]-=ys; YP[j,i]-=ys; YP[i,i]+=ys; YP[j,j]+=ys
        # Modelagem PECO (sem tensão pré-falta): equipamentos shunt (H), SVC e shunts
        # de linha (DSHL) NÃO são representados na sequência positiva (manual ANAFAS
        # seç. 2.2/2.5). Eles participam apenas da sequência zero via X0 ("caminhos
        # para a terra"). O campo Q é potência nominal (informativo).
        YPf = csc_matrix(YP)
        # Mantém TODAS as barras. A fuga numérica é aplicada somente às ilhas
        # efetivamente flutuantes; a rede física aterrada não é perturbada.
        self.BLP = list(self.BUS)
        self.IDXP = dict(self.IDX)
        self.YP, self._regP = self._regularize_floating_components(YPf)

        # ----- seq zero (com barras auxiliares p/ mútuas parciais) -----
        self._build_zero()

    def lt_key(self,a,b,nc): return (min(a,b),max(a,b),nc)

    def _build_zero(self):
        IDX=self.IDX; M=self.M
        # cortes para mútuas parciais
        cortes=defaultdict(set); direc={}
        for br in M.branches:
            if br['tipo']!='L': continue
            if br['bf'] is None or br['bt'] is None: continue
            k=self.lt_key(br['bf'],br['bt'],br['nc'])
            if k not in direc: direc[k]=(br['bf'],br['bt'])
        for mu in M.mutuas:
            for (a,b,n,pi,pf) in [(mu['bf1'],mu['bt1'],mu['n1'],mu['pi1'],mu['pf1']),
                                  (mu['bf2'],mu['bt2'],mu['n2'],mu['pi2'],mu['pf2'])]:
                if pi>pf: pi,pf = pf,pi              # dado com %I>%F: ANAFAS aceita; normaliza
                if not (pi==0 and pf==100):
                    k=self.lt_key(a,b,n)
                    if k not in direc: continue
                    a0,b0=direc[k]
                    # normalizar porcentagens para a direção armazenada do ramo
                    if (a,b)==(a0,b0): pts={round(pi,6),round(pf,6)}
                    else: pts={round(100-pf,6),round(100-pi,6)}
                    cortes[k]|={0,100}|pts
        aux={}; nxt=max(self.BUS)+100000
        for k,ps in cortes.items():
            if k not in direc: continue
            a0,b0=direc[k]
            for p in sorted(ps):
                aux[(a0,b0,k[2],p)] = a0 if p==0 else (b0 if p==100 else nxt)
                if 0<p<100: nxt+=1
        auxb=sorted({v for kk,v in aux.items() if kk[3] not in (0,100)})
        BUS0=self.BUS+auxb; N0=len(BUS0); IDX0={b:i for i,b in enumerate(BUS0)}
        self.direc=direc; self.cortes=cortes; self.aux=aux; self.IDX0=IDX0; self.BUS0=BUS0
        Y=lil_matrix((N0,N0),dtype=complex); Zseg={}
        # LTs (segmentadas)
        for br in M.branches:
            if br['tipo']!='L': continue
            bf,bt=br['bf'],br['bt']
            if bf not in IDX0 or bt not in IDX0: continue
            if (bf,bt,br['nc']) in self.dropB: continue
            z=zfin(br['R0'], br['X0'])
            if z is None: continue
            # PECO: line charging (S0) não representado (manual seç. 2.2/2.5)
            bsh=0.0
            k=self.lt_key(bf,bt,br['nc'])
            if k in cortes and k in direc:
                a0,b0=direc[k]; ps=sorted(cortes[k])
                for s in range(len(ps)-1):
                    fr=(ps[s+1]-ps[s])/100
                    if fr < 1e-9: continue
                    ba,bb=aux.get((a0,b0,br['nc'],ps[s])),aux.get((a0,b0,br['nc'],ps[s+1]))
                    if ba not in IDX0 or bb not in IDX0: continue
                    zs=z*fr; ys=1/zs; yh=1j*bsh*fr/2; i,j=IDX0[ba],IDX0[bb]
                    Y[i,j]-=ys; Y[j,i]-=ys; Y[i,i]+=ys+yh; Y[j,j]+=ys+yh
                    Zseg[(ba,bb,k,ps[s],ps[s+1])]=zs
            else:
                i,j=IDX0[bf],IDX0[bt]; ys=1/z; yh=1j*bsh/2
                Y[i,j]-=ys; Y[j,i]-=ys; Y[i,i]+=ys+yh; Y[j,j]+=ys+yh
                Zseg[(bf,bt,k,0,100)]=z
        # Trafos
        for br in M.branches:
            if br['tipo']!='T': continue
            bf,bt=br['bf'],br['bt']
            if bf not in IDX0 or bt not in IDX0: continue
            if (bf,bt,br['nc']) in self.dropB: continue
            z=zfin(br['R0'], br['X0'])
            if z is None: continue
            cd,cp=self.conn_type(br.get('cd','YN')),self.conn_type(br.get('cp','YN'))
            znd=zn3(br.get('rnde'), br.get('xnde'))   # 3·Zn lado De
            znp=zn3(br.get('rnpa'), br.get('xnpa'))   # 3·Zn lado Para
            tnun=br.get('nunop',1) or 1               # N unidades em paralelo (banco)
            i,j=IDX0[bf],IDX0[bt]
            if cd=='D' and cp=='D': continue
            elif cd=='D' and cp=='YN':
                if znp is None: continue              # neutro isolado
                Y[j,j]+=tnun/(z+znp)
            elif cp=='D' and cd=='YN':
                if znd is None: continue
                Y[i,i]+=tnun/(z+znd)
            elif cd=='YN' and cp=='YN':
                if znd is None or znp is None: continue
                ys=tnun/(z+znd+znp); Y[i,j]-=ys; Y[j,i]-=ys; Y[i,i]+=ys; Y[j,j]+=ys
            else: continue
        # Geradores
        for g in M.gens:
            b=g['bus']
            if b not in IDX0 or b in self.dropG: continue
            if self.conn_type(g['conn'])!='YN': continue
            z=zfin(g['R0'], g['X0'])
            if z is None: continue
            zn=zn3(g.get('rn'), g.get('xn'))
            if zn is None: continue                   # neutro isolado
            nun=g.get('nunop',1) or 1
            Y[IDX0[b],IDX0[b]]+=nun/(z+zn)
        # Zigzag
        for zg in M.zig:
            b=zg['bus']
            if b not in IDX0: continue
            x=(zg['X0'] or 0)/100
            r=(zg.get('R0') or 0)/100
            if not np.isfinite(r): r=0.0
            if (abs(x)<1e-12 and abs(r)<1e-12) or not np.isfinite(x): continue
            zn=zn3(zg.get('rn'), zg.get('xn'))
            if zn is None: continue
            Y[IDX0[b],IDX0[b]]+=1/(r+1j*x+zn)
        # Caps série
        for c in M.caps:
            bf,bt=c['bf'],c['bt']
            if bf not in IDX0 or bt not in IDX0: continue
            x=(c['X0'] or 0)/100
            if abs(x)<1e-12 or not np.isfinite(x): continue
            i,j=IDX0[bf],IDX0[bt]; ys=1/(1j*x)
            Y[i,j]-=ys; Y[j,i]-=ys; Y[i,i]+=ys; Y[j,j]+=ys
        # Shunt de barra H: o registro já fornece a impedância homopolar R0+jX0.
        # RN/XN do lado do equipamento não é somado novamente (validado A/B vs ANAFAS).
        for h in M.shunts:
            b=h['bus']
            if b not in IDX0: continue
            if self.conn_type(h['conn'])!='YN': continue
            x=(h['X0'] or 0)/100
            r=(h.get('R0') or 0)/100
            if not np.isfinite(r): r=0.0
            if (abs(x)<1e-6 and abs(r)<1e-6) or not np.isfinite(x): continue
            nun=h.get('nunop',1) or 1                 # N unidades em paralelo
            Y[IDX0[b],IDX0[b]]+=nun/(r+1j*x)
        # SVC/E: preserva a conexão e eventual aterramento do lado cadastrado.
        for h in M.svc:
            b=h['bus']
            if b not in IDX0: continue
            if self.conn_type(h['conn'])!='YN': continue
            x=(h['X0'] or 0)/100
            if abs(x)<1e-6 or not np.isfinite(x): continue
            zn=zn3(h.get('rn'), h.get('xn'))
            if zn is None: continue
            Y[IDX0[b],IDX0[b]]+=1/(1j*x+zn)
        # Shunt de linha seq0: reator de linha com eventual reator de neutro (Rn,Xn).
        # Z_fase = -j·Sb/Q (Q<0 indutivo) ; Z0_ef = Z_fase + 3·Zn
        for s in M.shl:
            b=s['bf'] if s['term']=='D' else s['bt']
            if b not in IDX0 or not s['Q']: continue
            if self.conn_type(s['conn'])!='YN': continue
            zn=zn3(s.get('rn'), s.get('xn'))
            if zn is None: continue                   # neutro isolado
            zf=-1j*SB/s['Q']/SB*100/100               # = -j*(Sb/Q)/Sb… simplificar abaixo
            zf=1/(1j*(s['Q']/SB))                     # Z_fase em pu (inverso da admitância)
            nun=s.get('nunop',1) or 1                 # unidades operativas em paralelo
            Y[IDX0[b],IDX0[b]]+=nun/(zf+zn)
        # ---- acoplamentos mutuos por GRUPO (matriz primitiva) ----
        def seg(a,b,k,pi,pf):
            if pi>pf: pi,pf = pf,pi                  # normaliza dado %I>%F
            # Lista [(na,nb,Zs,frac)] dos segmentos elementares do trecho,
            # nos na ordem DO REGISTRO (a->b); frac = fracao do comprimento do trecho.
            if k in cortes:
                if k not in direc: return None
                a0,b0=direc[k]
                if (a,b)==(a0,b0): pp=(round(pi,6),round(pf,6)); inv=False
                elif (a,b)==(b0,a0): pp=(round(100-pf,6),round(100-pi,6)); inv=True
                else: return None
                ps=sorted(cortes[k]); segs=[]; Ltre=pp[1]-pp[0]
                if Ltre<=0: return None
                for s in range(len(ps)-1):
                    if ps[s]>=pp[0] and ps[s+1]<=pp[1] and (ps[s+1]-ps[s])>1e-9:
                        n1_,n2_=aux.get((a0,b0,k[2],ps[s])),aux.get((a0,b0,k[2],ps[s+1]))
                        if n1_ is None or n2_ is None: continue
                        zs=None
                        for kk in [(n1_,n2_,k,ps[s],ps[s+1]),(n2_,n1_,k,ps[s],ps[s+1])]:
                            if kk in Zseg: zs=Zseg[kk]; break
                        if zs is None: continue
                        segs.append((n1_,n2_,zs,(ps[s+1]-ps[s])/Ltre,k))
                if not segs: return None
                if inv:
                    segs=[(nb,na,zs,fr,kk_) for (na,nb,zs,fr,kk_) in reversed(segs)]
                return segs
            else:
                if not(pi==0 and pf==100): return None
                for kk in [(a,b,k,0,100),(b,a,k,0,100)]:
                    if kk in Zseg: return [(a,b,Zseg[kk],1.0,k)]
                return None
        seg_nodes={}; seg_z={}; Mprim={}
        def skey(na,nb,kk_):
            # identidade unica do segmento: nos canonicos + ramo (inclui nc)
            return ((na,nb) if na<nb else (nb,na)) + (kk_,)
        for mu in M.mutuas:
            k1=self.lt_key(mu['bf1'],mu['bt1'],mu['n1'])
            k2=self.lt_key(mu['bf2'],mu['bt2'],mu['n2'])
            s1=seg(mu['bf1'],mu['bt1'],k1,mu['pi1'],mu['pf1'])
            s2=seg(mu['bf2'],mu['bt2'],k2,mu['pi2'],mu['pf2'])
            if s1 is None or s2 is None:
                self._mut_drop = getattr(self,'_mut_drop',0)+1
                continue
            self._mut_ok = getattr(self,'_mut_ok',0)+1
            Zm=complex((mu['RM'] or 0)/100,(mu['XM'] or 0)/100)
            if abs(Zm)<1e-12: continue
            for (na,nb,za,fa,k1_) in s1:
                ka=skey(na,nb,k1_); sga=+1 if (na,nb)==ka[:2] else -1
                seg_nodes[ka]=ka[:2]; seg_z[ka]=za
                for (nc_,nd,zb,fb,k2_) in s2:
                    kb=skey(nc_,nd,k2_); sgb=+1 if (nc_,nd)==kb[:2] else -1
                    seg_nodes[kb]=kb[:2]; seg_z[kb]=zb
                    if ka==kb: continue
                    kk=(ka,kb) if ka<kb else (kb,ka)
                    Mprim[kk]=Mprim.get(kk,0)+sga*sgb*Zm*fa*fb
        par={}
        def find(x):
            r=x
            while par.get(r,r)!=r: r=par[r]
            while par.get(x,x)!=x: par[x],x=r,par[x]
            return r
        def uni(x,y):
            par.setdefault(x,x); par.setdefault(y,y)
            rx,ry=find(x),find(y)
            if rx!=ry: par[rx]=ry
        for (ka,kb) in Mprim: uni(ka,kb)
        grupos={}
        for kseg in par: grupos.setdefault(find(kseg),[]).append(kseg)
        gmax=0
        for segs in grupos.values():
            n=len(segs); gmax=max(gmax,n)
            idx={s:i for i,s in enumerate(segs)}
            Zp=np.zeros((n,n),dtype=complex)
            for s in segs: Zp[idx[s],idx[s]]=seg_z[s]
            for (ka,kb),zm in Mprim.items():
                if ka in idx and kb in idx:
                    Zp[idx[ka],idx[kb]]=zm; Zp[idx[kb],idx[ka]]=zm
            try:
                Yp=np.linalg.inv(Zp)
            except np.linalg.LinAlgError:
                continue
            dY=Yp.copy()
            for s in segs: dY[idx[s],idx[s]]-=1/seg_z[s]
            nod=[(IDX0[seg_nodes[s][0]],IDX0[seg_nodes[s][1]]) for s in segs]
            for u in range(n):
                iu,ju=nod[u]
                for v in range(n):
                    y=dY[u,v]
                    if abs(y)<1e-14: continue
                    iv,jv=nod[v]
                    Y[iu,iv]+=y; Y[iu,jv]-=y; Y[ju,iv]-=y; Y[ju,jv]+=y
        self._mut_gmax=gmax
        # Mantém TODAS as barras (inclui ilhas HVDC e auxiliares de mútua).
        self.BL0=list(BUS0)
        self.I0P={b:i for i,b in enumerate(self.BL0)}
        # Em sequência zero há muitas ilhas flutuantes. Somente elas recebem a
        # condutância de fuga usada para permitir a fatoração; componentes com
        # aterramento físico permanecem inalterados.
        self.Y0, self._reg0 = self._regularize_floating_components(csc_matrix(Y))

    # ---------- solução de faltas ----------
    def factor(self, avisar=True):
        """Fatora as duas redes de sequência. Obrigatório antes de qualquer consulta.

        Com `avisar=True` (padrão), emite na saída padrão uma orientação curta quando o
        caso tem geradores de conversor pleno — porque nesse caso a escolha de modo muda
        o resultado em dezenas de por cento e quem não acompanhou o desenvolvimento não
        tem como saber disso.
        """
        self.luP=splu(self.YP); self.lu0=splu(self.Y0)
        if avisar and getattr(self.M, 'deol', None):
            n = sum(len(v) if isinstance(v, list) else 1 for v in self.M.deol.values())
            print(
                f"\n[LINCC] Este caso tem {n} geradores de conversor pleno (bloco DEOL) em "
                f"{len(self.M.deol)} barras.\n"
                "        Perto deles, incluir ou não essa contribuição muda a corrente em "
                "mais de 40%.\n"
                "        fault(bus, kind)                    -> Thévenin puro, SEM conversores\n"
                "        fault(bus, kind, modo='completo')   -> COM conversores (exige validar)\n"
                "        Chame lincc.orientacao() para o guia de modos, tolerância e limitações."
            )

    def zth(self, bus):
        if bus not in self.IDXP:
            return None, None, None
        k=self.IDXP[bus]; e=np.zeros(len(self.BLP),dtype=complex); e[k]=1
        Z1=self.luP.solve(e)[k]; Z2=Z1
        if bus in self.I0P:
            k0=self.I0P[bus]; e0=np.zeros(len(self.BL0),dtype=complex); e0[k0]=1
            Z0=self.lu0.solve(e0)[k0]
        else: Z0=None
        return Z1,Z2,Z0

    def fault(self, bus, kind='3F', Zf=0.0, Vf=1.0, modo='sincronas'):
        """kind: '3F','1FT','2F','2FT'. Zf em pu. Retorna corrente em kA primários.

        modo='sincronas' (padrão): Thévenin puro da Ybus, SEM as fontes de conversor
            pleno. Âncora de validação: 'RELATORIO DE DADOS DE CURTO-CIRCUITO' (MVA).
        modo='completo': inclui as injeções do bloco DEOL. Âncora de validação:
            'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO' (kA). Zf não é suportado neste modo.

        Não misture modos dentro de um mesmo critério: combinar ICC_MAX de um com
        ICC_MIN do outro produz margem fictícia.

        Convenções, todas reconciliadas com o relatório da ferramenta de referência:
          3F   I = Vf / (Z1 + Zf)
          1FT  I = 3·Vf / (Z1 + Z2 + Z0 + 3·Zf)
          2F   I = √3·Vf / (Z1 + Z2 + 2·Zf)
          2FT  I = √3 · max(|Ib|, |Ic|), com Ib,c = Vf·(Z0 − a^{1,2}·Z2) / (Z1Z2 + Z1Z0 + Z2Z0)
               O fator √3 e o uso da MAIOR das duas fases em falta foram determinados por
               reconciliação barra a barra: reproduzem exatamente as colunas de kA e de MVA
               do relatório (escolher a outra fase erra até 0,5%).

        Não inclui geradores full-converter (fontes de corrente): este é o Thévenin puro da
        Ybus. Para incluí-los, use `fault_fc`.
        """
        if modo not in self.MODOS:
            raise ValueError(f"modo deve ser um de {self.MODOS}, recebido {modo!r}")
        if modo == 'completo':
            if Zf:
                raise NotImplementedError("impedância de falta ainda não suportada no modo completo")
            self._exigir_validacao_completo()
            return self.fault_fc(bus, kind)
        kv=self.M.bus_kv.get(bus,0)
        if not kv: return None
        Ib=SB/(np.sqrt(3)*kv)
        Z1,Z2,Z0=self.zth(bus)
        if Z1 is None: return None
        zf=complex(Zf)
        if kind=='3F':
            I=abs(Vf/(Z1+zf))
        elif kind=='1FT':
            if Z0 is None: return None
            I=abs(3*Vf/(Z1+Z2+Z0+3*zf))
        elif kind=='2F':
            I=abs(np.sqrt(3)*Vf/(Z1+Z2+2*zf))
        elif kind=='2FT':
            if Z0 is None: return None
            z1f, z2f, z0f = Z1+zf, Z2+zf, Z0+zf
            den=z1f*z2f + z1f*z0f + z2f*z0f
            if abs(den)<1e-18: return None
            a=np.exp(2j*np.pi/3)
            ib=Vf*(z0f - a*z2f)/den
            ic=Vf*(z0f - a.conjugate()*z2f)/den
            I=np.sqrt(3)*max(abs(ib),abs(ic))
        else:
            return None
        return I*Ib

    # ------------------------------------------------------------------ #
    #  Geradores com conversor pleno (bloco DEOL)                         #
    # ------------------------------------------------------------------ #
    MODOS = ('sincronas', 'completo')

    def _fc_sources(self):
        """Fontes de corrente de conversor pleno, a partir do bloco DEOL — e SÓ dele.

        Retorna {bus: [reg, ...]} com as injeções-limite em pu na base da barra.

        Não há inferência por reatância. O bloco DEOL é a única marcação de conversor
        pleno no arquivo; classificar por X0 infinito e X1d alto captura as máquinas
        tipo-G dos próprios parques, que o ANAFAS já representa como impedância na Ybus —
        elas entrariam duas vezes.

        `Imax` do registro é POR UNIDADE. O manual é explícito no exemplo: "3600 A x 25
        unidades = 90 kA". Multiplica-se por NOP (em operação), não por NUN (instaladas).
        """
        if hasattr(self, '_fcsrc'):
            return self._fcsrc
        fc = {}
        for b, regs in getattr(self.M, 'deol', {}).items():
            if b not in self.IDXP:
                continue
            kv = self.M.bus_kv.get(b, 0)
            if not kv:
                continue
            Ib_A = SB * 1e3 / (np.sqrt(3) * kv)      # corrente base em A (SB em MVA)
            lista = regs if isinstance(regs, list) else [regs]
            saida = []
            for r in lista:
                imax_A = r.get('Imax_A')
                if not imax_A:
                    continue
                nop = r.get('nunop', 1) or 1
                Imax = imax_A * nop / Ib_A            # pu
                fpcc = r.get('fpcc')
                fpcc = 1.0 if fpcc is None else fpcc
                # O SINAL de FP_CC é convenção do formato: positivo = indutivo,
                # negativo = capacitivo, "mesmo para ângulos do primeiro quadrante".
                phi = np.arccos(min(abs(fpcc), 1.0))
                if fpcc < 0:
                    phi = -phi
                mva = r.get('MVA')
                # In para a curva ΔIq×V+: do campo MVA; na ausência dele o manual manda
                # usar o próprio Imax.
                In = (mva * 1e3 / (np.sqrt(3) * kv) * nop / Ib_A) if mva else Imax
                saida.append(dict(Imax=Imax, phi=phi, In=In,
                                  K=r.get('K', 0) or 0,
                                  Vmin=r.get('Vmin', 0.0) or 0.0,
                                  Vmax=r.get('Vmax', 9999.0) or 9999.0,
                                  VP1=r.get('VP1', 0.50) or 0.50,
                                  VP2=r.get('VP2', 0.85) or 0.85))
            if saida:
                fc[b] = saida
        self._fcsrc = fc
        return fc

    @staticmethod
    def _inj_fc(reg, Vp, ang_ref=None):
        """Injeção de um registro DEOL para tensão terminal de sequência positiva Vp.

        Devolve o fasor de corrente em pu, ou 0 se o gerador está fora.

        Dois modelos, selecionados pelo campo K do registro:
          K=0  fator de potência de curto fixo: |I| = Imax, defasada de phi_cc em relação
               à tensão terminal.
          K=1  curva de corrente reativa em função da tensão de sequência positiva:
               ΔIq/In = 1 abaixo de VP1, zero acima de VP2, rampa linear entre os dois.
               A injeção é reativa (em quadratura com a tensão), limitada a Imax.

        A curva de K=1 tem respaldo NORMATIVO, não é inferência: ONS, Procedimentos de
        Rede, Submódulo 2.10 (Revisão 2025.02), item 5.8 e Figura 14 — "Requisito para
        injeção de corrente reativa sob defeito". O item 5.8.1(a) exige injeção de
        corrente reativa adicional para tensões de sequência positiva abaixo de 85%, e o
        5.8.3 fixa o ajuste padrão em V1 = 0,5 pu. A Figura 14 plota ΔIq/In de +1 em V1
        até a banda morta em 0,85 pu. Isso é exatamente VP1 = 0,50 e VP2 = 0,85, os
        defaults do registro DEOL — as duas fontes coincidem.

        Abaixo de V1 a injeção satura em ΔIq/In = 1 e o gerador PERMANECE conectado. O
        bloqueio por subtensão foi testado contra o gabarito em cinco limiares (0,15 a
        0,25 pu, incluindo o 0,2 pu da envoltória LVRT da Figura 13) e todos degradam o
        resultado global de 100% para 2% das barras dentro de 1%: o ANAFAS não bloqueia.

        O teto de corrente é o do item 5.8.4: o incremento de reativo tem precedência até
        o limite de corrente nominal do equipamento, reduzindo-se a parcela ativa.
        """
        Vm = abs(Vp)
        # Desconexão por tensão: qualquer fase fora da faixa zera a injeção. Aqui o
        # critério é aplicado sobre a sequência positiva (o motor não monta as fases do
        # terminal do gerador). Com Vmin=0 — o default, e o que esta base traz — o
        # gerador nunca se desconecta por subtensão, nem em curto franco no terminal.
        if Vm < reg['Vmin'] or Vm > reg['Vmax']:
            return 0j
        # Referência de ângulo. Normalmente é a tensão CONVERGIDA do terminal. Quando o
        # ângulo não é determinável — curto que isola o radial do parque, tensão
        # terminal colapsada — o manual do ANAFAS manda referir à tensão PRÉ-FALTA, e é
        # esse `ang_ref` que entra. Sem isso o ângulo gira a cada iteração e o processo
        # não converge, embora exista solução.
        ang_v = ang_ref if ang_ref is not None else (np.angle(Vp) if Vm > 1e-9 else 0.0)
        if reg['K'] == 1:
            # Módulo pela mesma regra de _mod_fc: a curva é normalizada em ΔIq/In, mas o
            # teto é Imax. Com MVA declarado, In < Imax (razão típica 1,5) e saturar em
            # In subestima a injeção em exatamente Imax/In.
            mod, _ = Solver._mod_fc(reg, Vm)
            if mod <= 0:
                return 0j
            return mod * np.exp(1j * (ang_v - np.pi / 2))     # reativa, atrasada de 90°
        mod = reg['Imax']
        return mod * np.exp(1j * (ang_v - reg['phi']))

    # Janela de suavização dos joelhos da característica, em pu de tensão. A curva do
    # SM 2.10 é definida por trechos e tem derivada descontínua em VP1, VP2 e no limite
    # de corrente. Newton alterna entre os dois lados de um joelho e não converge, mesmo
    # com o Jacobiano exato. Suavizar numa janela estreita torna a função C¹ sem alterar
    # resultado de engenharia: 5 mpu de tensão é menor que a resolução do próprio dado.
    _EPS_JOELHO = 0.005

    @staticmethod
    def _rampa_suave(u):
        """Satura u em [0,1] com transição C¹ nos extremos. Devolve (valor, derivada)."""
        e = Solver._EPS_JOELHO
        if u <= -e:
            return 0.0, 0.0
        if u >= 1 + e:
            return 1.0, 0.0
        if u < e:                              # joelho inferior: polinômio de Hermite
            s = (u + e) / (2 * e)
            return e * s * s, s
        if u > 1 - e:                          # joelho superior
            s = (1 + e - u) / (2 * e)
            return 1.0 - e * s * s, s
        return u, 1.0

    @staticmethod
    def _mod_fc(reg, Vm):
        """Módulo da injeção e sua derivada em relação a |V|: devolve (m, dm/dr)."""
        if Vm < reg['Vmin'] or Vm > reg['Vmax']:
            return 0.0, 0.0
        if reg['K'] != 1:
            return reg['Imax'], 0.0            # fator de potência fixo: |I| constante
        vp1, vp2 = reg['VP1'], reg['VP2']
        if vp2 <= vp1:
            return 0.0, 0.0
        # A curva do SM 2.10 é normalizada em ΔIq/In e vai a 1,0 no ajuste V1. Mas o teto
        # físico da injeção é Imax, o limite de corrente do conversor, que o registro traz
        # separado de MVA. Quando MVA está preenchido, In = MVA/(√3·kV) é MENOR que Imax
        # (razão típica 1,5), e saturar em In subestima a contribuição em exatamente
        # Imax/In. Quando MVA está ausente, o manual manda usar o próprio Imax como In,
        # e os dois limites coincidem — por isso o erro só aparecia nas poucas barras com
        # MVA declarado.
        u = (vp2 - Vm) / (vp2 - vp1)           # 0 em VP2, 1 em VP1
        s, ds = Solver._rampa_suave(u)
        # A curva do SM 2.10 é normalizada (ΔIq/In vai de 0 a 1 entre VP2 e VP1); o valor
        # ABSOLUTO da injeção escala com Imax, o limite de corrente do conversor, e não
        # com In. Determinado por reconciliação: nas barras com MVA declarado, In < Imax
        # (razão 1,50) e usar In subestimava a contribuição em exatamente Imax/In. Onde
        # MVA está ausente o manual manda tomar In = Imax e as duas leituras coincidem —
        # por isso o desvio só aparecia nas poucas barras com MVA preenchido.
        m = reg['Imax'] * s
        dm = -reg['Imax'] * ds / (vp2 - vp1)
        return m, dm

    @staticmethod
    def _jac_fc(reg, Vp, ang_ref=None):
        """Jacobiano REAL 2x2 da característica do conversor: d(Ire,Iim)/d(Vre,Vim).

        A característica NÃO é holomorfa — depende de |V|, não de V — então tratá-la
        como derivada complexa escalar (o que a linearização Norton usual faz) é uma
        aproximação. Ela basta quando |Z_transferência| < |Z_Thévenin|, mas falha onde
        um banco com reatância negativa inverte essa relação: o Newton entra em ciclo
        limite e o resíduo estaciona.

        Escrevendo a injeção como I = c(r)·V, com r = |V| e c(r) = m(r)·e^(−jφ)/r:

            Ire = cr·x − ci·y            Iim = ci·x + cr·y
            ∂Ire/∂x = cr + (x/r)(c'r·x − c'i·y)
            ∂Ire/∂y = −ci + (y/r)(c'r·x − c'i·y)
            ∂Iim/∂x = ci + (x/r)(c'i·x + c'r·y)
            ∂Iim/∂y = cr + (y/r)(c'i·x + c'r·y)

        com c'(r) = [m'(r)·r − m(r)]/r² · e^(−jφ).
        """
        Vm = abs(Vp)
        if Vm < 1e-12:
            return np.zeros((2, 2))
        m, dm = Solver._mod_fc(reg, Vm)
        if m == 0.0 and dm == 0.0:
            return np.zeros((2, 2))
        phi = (np.pi / 2) if reg['K'] == 1 else reg['phi']
        rot = np.exp(-1j * phi)
        if ang_ref is not None:
            # Ângulo travado: a injeção não gira com V, só o módulo responde.
            u = np.exp(1j * (ang_ref - phi))
            d = dm / Vm                      # dI/d|V| projetado na direção de V
            x, y = Vp.real, Vp.imag
            g = np.array([[x, y]]) / Vm      # d|V|/d(x,y)
            return np.array([[ (d * u).real ], [ (d * u).imag ]]) @ g
        c = m * rot / Vm
        dc = (dm * Vm - m) / (Vm * Vm) * rot
        x, y = Vp.real, Vp.imag
        cr, ci = c.real, c.imag
        dcr, dci = dc.real, dc.imag
        a = (dcr * x - dci * y) / Vm
        b = (dci * x + dcr * y) / Vm
        return np.array([[cr + x * a, -ci + y * a],
                         [ci + x * b,  cr + y * b]])

    def _norton(self):
        """Correntes nodais de Norton dos geradores síncronos (YP·Vflat = injeções que
        sustentam V=1 pu em vazio). Cacheado."""
        if hasattr(self,'_inorton'): return self._inorton
        N=len(self.BLP)
        self._inorton = self.YP.dot(np.ones(N,dtype=complex))
        return self._inorton

    def _estado_fc(self, bus, niter=400, damp=1.0, tol=1e-8, strict=True,
                   ang_prefalta=False, tol_saida=1e-5):
        """Resolve o estado da rede com as fontes DEOL ativas, para falta franca em `bus`.

        Devolve (V, Ifault, info): V o vetor de tensões nodais convergido, Ifault a
        corrente de falta em pu, info o diagnóstico da iteração.

        Ponto único de solução do modo 'completo': corrente de falta, contribuição por
        elemento, corrente de ramo e tensão de barra saem TODAS deste mesmo V.

        MÉTODO — Newton sobre as injeções, com o conversor linearizado como equivalente
        Norton. A iteração de ponto fixo ingênua (atualizar I = f(V) e reinjetar) é
        numericamente instável com fonte de corrente ideal: cai em ciclo limite de
        período 2, em que a tensão terminal oscila entre um valor baixo e um alto e o
        resíduo estaciona num patamar, sem melhorar com mais iterações nem com passo
        menor. O problema e a correção estão em Haddadi, Farantatos & Kocar, "A Robust
        Solver for Phasor-Domain Short-Circuit Analysis with Inverter-Based Resources"
        (arXiv:2411.12006): a instabilidade vem da fonte de corrente ideal, e se resolve
        linearizando a característica como Norton (I = In − Yn·V) e iterando por Newton.

        Formulação, com I o vetor de injeções nas n barras com DEOL:

            V(I) = V_th + Z·I          (rede, linear; V_th é a tensão com a falta e I=0)
            g(I) = f(V(I)) − I         (resíduo; f é a característica do conversor)
            J    = diag(f'(V))·Z − E   (Jacobiano)

        Z é a submatriz de impedâncias entre as barras com DEOL, obtida uma vez por
        falta. Como n é da ordem de centenas, o sistema denso n×n por iteração é barato
        perto do solve esparso da rede completa.

        Corte de vizinhança conforme o manual do ANAFAS: geradores cuja tensão não
        afunde mais que 0,01 pu em relação à pré-falta ficam fora do processo e mantêm a
        injeção pré-falta. A avaliação é feita na PRIMEIRA iteração e o conjunto fica
        fixo — não é um corte reaplicado a cada passo, o que realimentaria a oscilação.
        """
        k = self.IDXP[bus]
        N = len(self.BLP)
        ek = np.zeros(N, dtype=complex); ek[k] = 1
        zk = self.luP.solve(ek); Zkk = zk[k]
        Inorton = self._norton()
        fc = self._fc_sources()

        def resolver(Ieol):
            V0 = self.luP.solve(Inorton + Ieol)
            If = V0[k] / Zkk
            return V0 - If * zk, If

        Ieol = np.zeros(N, dtype=complex)
        V, If = resolver(Ieol)
        Vpre = self.luP.solve(Inorton)
        ativos = [(b, self.IDXP[b], regs) for b, regs in fc.items()
                  if abs(Vpre[self.IDXP[b]]) - abs(V[self.IDXP[b]]) > 0.01]
        info = dict(fontes=len(fc), ativas=len(ativos), iteracoes=0, residuo=None,
                    convergiu=False, metodo='newton-norton')
        if not ativos:
            info['convergiu'] = True
            return V, If, info

        idxs = [j for _, j, _ in ativos]
        n = len(idxs)
        # Submatriz de impedâncias COM a falta aplicada: Z_f = Z − z_k z_k^T / Z_kk,
        # restrita às barras com DEOL. É o acoplamento que o Newton precisa.
        E = np.zeros((N, n), dtype=complex)
        for c, j in enumerate(idxs):
            E[j, c] = 1
        Zcols = self.luP.solve(E)                       # N x n
        Zsub = Zcols[idxs, :]                           # n x n
        zk_sub = zk[idxs].reshape(-1, 1)
        Zf = Zsub - (zk_sub @ zk_sub.T) / Zkk           # com a falta em k
        Vth = V[idxs].copy()                            # tensão com falta e sem injeção

        # ---- Referência de ângulo, decidida POR FONTE ----------------------------
        # O ANAFAS não escolhe a referência para o conjunto: cada gerador resolve com o
        # ângulo da PRÓPRIA tensão convergida quando essa equação tem solução, e cai na
        # tensão PRÉ-FALTA quando não tem. O relatório declara qual foi usada, no rótulo
        # da fonte: 'FON.CORRENTE' contra 'FON.COR.Vpre'.
        #
        # A condição é local. Para a fonte j, com Vth_j a tensão da barra com a falta
        # aplicada e sem injeção, e Zjj o elemento diagonal da submatriz com a falta:
        #
        #     V_j = Vth_j + Zjj·I_j        e       I_j = |I|·e^{j(ang V_j − 90°)}
        #
        # Quando Vth_j ≈ 0 — a fonte fica eletricamente colada ao ponto de falta — resta
        # ang(V_j) = ang(Zjj) + ang(I_j), e a equação exige ang(Zjj) = 90°. Fora disso
        # não há solução com ângulo próprio e a referência passa a ser a pré-falta.
        #
        # Aplicar esse fallback ao CONJUNTO, e não à fonte que precisa dele, é o que
        # produzia erro de +29% no caso de aceitação: a fonte remota, que tem solução
        # própria, saía com o ângulo errado.
        angs = []
        for c, (b, j, _) in enumerate(ativos):
            if ang_prefalta:
                angs.append(float(np.angle(Vpre[j])))
                continue
            colada = abs(Vth[c]) < 1e-6 * max(1.0, abs(Vpre[j]))
            desvio = abs(abs(np.degrees(np.angle(Zf[c, c]))) - 90.0) if abs(Zf[c, c]) > 1e-12 else 180.0
            if colada and desvio > 0.5:
                angs.append(float(np.angle(Vpre[j])))     # sem solução própria
            else:
                angs.append(None)                          # resolve com a própria tensão
        info['fontes_prefalta'] = sum(1 for a in angs if a is not None)
        info['ang_prefalta'] = bool(ang_prefalta) or info['fontes_prefalta'] > 0

        Ivec = np.zeros(n, dtype=complex)
        hist = []

        # Newton em coordenadas REAIS (2n x 2n). A característica do conversor depende de
        # |V|, não de V: não é holomorfa, e o Jacobiano complexo escalar é aproximação.
        # Ela basta enquanto |Z_transferência| < |Z_Thévenin|; um banco com reatância
        # negativa inverte essa relação e o Newton complexo entra em ciclo limite, com o
        # resíduo estacionando num patamar. Em coordenadas reais o Jacobiano é exato.
        Zr, Zi = Zf.real, Zf.imag
        B = np.block([[Zr, -Zi], [Zi, Zr]])          # d(Vre,Vim)/d(Ire,Iim)
        Id2 = np.eye(2 * n)
        for it in range(1, niter + 1):
            Vloc = Vth + Zf @ Ivec
            alvo = np.array([sum(self._inj_fc(r, Vloc[c], angs[c]) for r in ativos[c][2])
                             for c in range(n)], dtype=complex)
            g = alvo - Ivec
            res = float(np.max(np.abs(g)))
            info.update(iteracoes=it, residuo=res)
            if res < tol:
                info['convergiu'] = True
                info['criterio'] = 'residuo'
                break
            # Critério alternativo: a GRANDEZA DE SAÍDA estabilizou. A característica é
            # definida por trechos e, mesmo suavizada, um subconjunto de fontes pode
            # oscilar entre estados sem que isso mova a corrente de falta — o resíduo de
            # injeção estaciona num patamar e a corrente já está na solução. Exigir só o
            # resíduo rejeitaria resultado correto; aceitar sem medir mascararia erro.
            # Mede-se a corrente de falta nas últimas iterações e aceita-se quando a
            # variação relativa fica abaixo de `tol_saida`, guardando o resíduo no `info`.
            Ifit = (Vth[0] * 0 + (V0k := (self.luP.solve(Inorton + self._espalhar(Ivec, idxs, N)))[k])) / Zkk
            hist.append(abs(Ifit))
            if len(hist) > 8:
                hist.pop(0)
                faixa = (max(hist) - min(hist)) / max(abs(np.mean(hist)), 1e-12)
                if faixa < tol_saida:
                    info['convergiu'] = True
                    info['criterio'] = 'saida-estavel'
                    break
            A = np.zeros((2 * n, 2 * n))
            for c in range(n):
                jac = np.zeros((2, 2))
                for r in ativos[c][2]:
                    jac = jac + self._jac_fc(r, Vloc[c], angs[c])
                A[c, c] = jac[0, 0]; A[c, n + c] = jac[0, 1]
                A[n + c, c] = jac[1, 0]; A[n + c, n + c] = jac[1, 1]
            J = A @ B - Id2
            gr = np.concatenate([g.real, g.imag])
            try:
                d = np.linalg.solve(J, -gr)
            except np.linalg.LinAlgError:
                d = gr                                  # singular: passo de Picard
            dI = d[:n] + 1j * d[n:]
            Ivec = Ivec + damp * dI
        Ieol = np.zeros(N, dtype=complex)
        Ieol[idxs] = Ivec
        V, If = resolver(Ieol)
        if not info['convergiu'] and strict:
            raise RuntimeError(
                f"fault_fc em {bus}: injeções não convergiram em {niter} iterações "
                f"(‖g‖∞ = {info['residuo']:.3e} pu > tol = {tol:.1e}). "
                "Aumente niter, reduza damp, ou investigue — não use o último valor.")
        return V, If, info

    @staticmethod
    def _espalhar(Ivec, idxs, N):
        v = np.zeros(N, dtype=complex)
        v[idxs] = Ivec
        return v

    def _estado_fc_robusto(self, bus, **kw):
        """Resolve o estado, com o fallback de ângulo do manual quando necessário.

        Tenta primeiro com o ângulo da tensão convergida. Se não convergir, repete com o
        ângulo travado na tensão pré-falta — que é o que o ANAFAS faz quando não há
        solução atendendo ao fator de potência de curto, tipicamente num curto que isola
        o radial de conexão do parque. É fallback do modelo, não artifício numérico.
        """
        kw.pop('strict', None)
        kw.pop('ang_prefalta', None)
        try:
            return self._estado_fc(bus, strict=True, ang_prefalta=False, **kw)
        except RuntimeError:
            # Último recurso: travar TODAS as fontes na pré-falta. Não é o modelo do
            # ANAFAS (que decide por fonte) e distorce as que teriam solução própria;
            # fica como degradação controlada, sinalizada em info['ang_prefalta'].
            return self._estado_fc(bus, strict=True, ang_prefalta=True, **kw)

    def fault_fc(self, bus, kind='3F', niter=60, damp=1.0, tol=1e-8, strict=True):
        """Corrente de falta em kA COM as fontes de conversor pleno (bloco DEOL).

        É a grandeza comparável ao 'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO' do ANAFAS,
        que inclui essas contribuições. Já `fault` é Thévenin puro e as exclui — é a
        grandeza comparável à seção de dados de curto (MVA).

        kind: '3F', '1FT' ou '2FT'. Nas faltas desequilibradas o conversor contribui
        APENAS com sequência positiva (manual, item 2.8.3): a injeção altera a rede de
        sequência positiva e as demais permanecem passivas.
        """
        if bus not in self.IDXP:
            return None
        kv = self.M.bus_kv.get(bus, 0)
        if not kv:
            return None
        Ib = SB / (np.sqrt(3) * kv)
        if kind == '3F':
            _, If, _ = self._estado_fc_robusto(bus, niter=niter, damp=damp, tol=tol)
            return abs(If) * Ib
        # Faltas desequilibradas: a injeção de sequência positiva desloca a tensão
        # equivalente de pré-falta vista pela rede de sequência. Resolve-se o estado com
        # a rede positiva carregada pelas fontes e aplica-se a mesma composição de
        # sequências de `fault`, com Vf igual à tensão da barra antes da falta nesse
        # estado — que é o efeito de primeira ordem das fontes numa falta assimétrica.
        Z1, Z2, Z0 = self.zth(bus)
        if Z1 is None or Z0 is None:
            return None
        V, If3, _ = self._estado_fc_robusto(bus, niter=niter, damp=damp, tol=tol)
        Vf = abs(If3 * Z1)          # tensão pré-falta equivalente com as fontes ativas
        if kind == '1FT':
            return abs(3 * Vf / (Z1 + Z2 + Z0)) * Ib
        if kind == '2FT':
            a = np.exp(2j * np.pi / 3)
            den = Z1 * Z2 + Z1 * Z0 + Z2 * Z0
            ib = Vf * (Z0 - a * Z2) / den
            ic = Vf * (Z0 - a.conjugate() * Z2) / den
            return np.sqrt(3) * max(abs(ib), abs(ic)) * Ib
        if kind == '2F':
            return abs(np.sqrt(3) * Vf / (Z1 + Z2)) * Ib
        return None

    def contribution(self, bus, kind='3F', modo='sincronas'):
        """Contribuicao de corrente de cada elemento incidente na barra para uma falta
        solida na propria barra. kind='3F' (modulo da corrente de fase, seq. positiva)
        ou '0' (modulo de I0 por ramo, seq. zero). Retorna dict {(tipo,bf,bt,nc): I_kA}.
        So considera ramos EM SERVICO (fora de dropB). Base: KCL fecha na corrente total."""
        if modo not in self.MODOS:
            raise ValueError(f"modo deve ser um de {self.MODOS}, recebido {modo!r}")
        kvb=self.M.bus_kv.get(bus,0)
        if not kvb: return {}
        Ib=SB/(np.sqrt(3)*kvb)
        if modo=='completo':
            if kind!='3F':
                raise NotImplementedError("modo completo em contribution: apenas 3F")
            self._exigir_validacao_completo()
            return self._contribuicao_fc(bus, Ib)
        if kind=='3F':
            if bus not in self.IDXP: return {}
            e=np.zeros(len(self.BLP),dtype=complex); e[self.IDXP[bus]]=1
            Zcol=self.luP.solve(e); Zff=Zcol[self.IDXP[bus]]; IDX=self.IDXP
            getz=lambda br:(br['R1'],br['X1'])
        else:
            if bus not in self.I0P: return {}
            e=np.zeros(len(self.BL0),dtype=complex); e[self.I0P[bus]]=1
            Zcol=self.lu0.solve(e); Zff=Zcol[self.I0P[bus]]; IDX=self.I0P
            getz=lambda br:(br['R0'],br['X0'])
        out={}
        for br in self.M.branches:
            if bus not in (br['bf'],br['bt']): continue
            if (br['bf'],br['bt'],br['nc']) in self.dropB: continue
            o=br['bt'] if br['bf']==bus else br['bf']
            if o not in IDX: continue
            R,X=getz(br)
            if R is None or X is None: continue
            z=complex(R,X)/100
            if abs(z)<1e-9: continue
            Vn=1-Zcol[IDX[o]]/Zff          # tensao no vizinho durante a falta (pref=1 pu)
            out[(br['tipo'],br['bf'],br['bt'],br['nc'])]=abs((1/z)*Vn)*Ib
        return out

    def _seq_profile(self, fault_bus, kind='3F', Zf=0.0):
        """Perfis de tensao de sequencia (vetores completos) e correntes de falta de sequencia
        para uma falta em fault_bus. Retorna dict(V1,V2 em espaco IDXP; V0 em espaco I0P;
        Ia1,Ia2,Ia0; Z1ff,Z0ff). Pref=1 pu (PECO)."""
        if fault_bus not in self.IDXP: return None
        e1=np.zeros(len(self.BLP),dtype=complex); e1[self.IDXP[fault_bus]]=1
        Z1col=self.luP.solve(e1); Z1ff=Z1col[self.IDXP[fault_bus]]; Z2ff=Z1ff
        Z0col=None; Z0ff=None
        if fault_bus in self.I0P:
            e0=np.zeros(len(self.BL0),dtype=complex); e0[self.I0P[fault_bus]]=1
            Z0col=self.lu0.solve(e0); Z0ff=Z0col[self.I0P[fault_bus]]
        zf=complex(Zf)
        if kind=='3F':
            Ia1=1/(Z1ff+zf); Ia2=0j; Ia0=0j
        elif kind=='1FT':
            if Z0ff is None: return None
            It=1/(Z1ff+Z2ff+Z0ff+3*zf); Ia1=Ia2=Ia0=It
        elif kind=='2F':
            Ia1=1/(Z1ff+Z2ff+2*zf); Ia2=-Ia1; Ia0=0j
        else: return None
        V1=np.ones(len(self.BLP),dtype=complex)-Z1col*Ia1
        V2=-Z1col*Ia2
        V0=(-Z0col*Ia0) if (Z0col is not None and Ia0!=0) else None
        return dict(V1=V1,V2=V2,V0=V0,Ia1=Ia1,Ia2=Ia2,Ia0=Ia0,Z1ff=Z1ff,Z0ff=Z0ff)

    def _find_branch(self, bf, bt, nc):
        for b in self.M.branches:
            if b['nc']==nc and {b['bf'],b['bt']}=={bf,bt}: return b
        return None

    def branch_current(self, fault_bus, bf, bt, nc, kind='3F', Zf=0.0):
        """Corrente de fase (kA primarios) num ramo QUALQUER para uma falta em fault_bus.
        Funciona para ramo incidente, a N barras de distancia, ou uma linha qualquer.
        Para LINHAS calcula as tres sequencias; para TRAFOS retorna so seq positiva
        (o I0 de enrolamento nao e serie simples entre as mesmas barras)."""
        prof=self._seq_profile(fault_bus, kind, Zf)
        if prof is None: return None
        br=self._find_branch(bf,bt,nc)
        if br is None: return None
        if (br['bf'],br['bt'],br['nc']) in self.dropB: return None
        i,j=br['bf'],br['bt']
        kvb=self.M.bus_kv.get(i,0) or self.M.bus_kv.get(j,0)
        if not kvb: return None
        Ib=SB/(np.sqrt(3)*kvb)
        z1=complex(br['R1'],br['X1'])/100 if br['R1'] is not None else None
        z0=complex(br['R0'],br['X0'])/100 if (br.get('R0') is not None and br.get('X0') is not None) else None
        def dI(V,IDX,z):
            if V is None or z is None or abs(z)<1e-12: return 0j
            if i not in IDX or j not in IDX: return 0j
            return (V[IDX[i]]-V[IDX[j]])/z
        I1=dI(prof['V1'],self.IDXP,z1); I2=dI(prof['V2'],self.IDXP,z1)
        I0=dI(prof['V0'],self.I0P,z0) if br['tipo']=='L' else 0j
        a=np.exp(2j*np.pi/3)
        Ia=I0+I1+I2; Ib2=I0+a*a*I1+a*I2; Ic=I0+a*I1+a*a*I2
        return dict(Ia=abs(Ia)*Ib,Ib=abs(Ib2)*Ib,Ic=abs(Ic)*Ib,
                    Imax=max(abs(Ia),abs(Ib2),abs(Ic))*Ib,
                    I1=abs(I1)*Ib,I2=abs(I2)*Ib,I0=abs(I0)*Ib,kV=kvb,
                    seqonly=(br['tipo']!='L'))

    def bus_voltage(self, fault_bus, obs_bus, kind='3F', Zf=0.0):
        """Tensoes de fase (pu) numa barra observada durante uma falta em fault_bus.
        Base para impedancia aparente de rele de distancia (Z_vista = V_rele/I_rele)."""
        prof=self._seq_profile(fault_bus, kind, Zf)
        if prof is None or obs_bus not in self.IDXP: return None
        V1=prof['V1'][self.IDXP[obs_bus]]; V2=prof['V2'][self.IDXP[obs_bus]]
        V0=prof['V0'][self.I0P[obs_bus]] if (prof['V0'] is not None and obs_bus in self.I0P) else 0j
        a=np.exp(2j*np.pi/3)
        Va=V0+V1+V2; Vb=V0+a*a*V1+a*V2; Vc=V0+a*V1+a*a*V2
        return dict(Va=abs(Va),Vb=abs(Vb),Vc=abs(Vc),V1=abs(V1),V2=abs(V2),V0=abs(V0),
                    Va_c=Va,V1_c=V1,V0_c=V0)

    def line_end_open(self, bf, bt, nc, closed, kind='3F', Zf=0.0):
        """Corrente no terminal FECHADO (closed) para falta na extremidade ABERTA da linha
        (bf,bt,nc). Modela o terminal remoto aberto (disjuntor abriu primeiro): Zth no terminal
        fechado com a linha removida, em serie com a impedancia total da linha, falta na ponta.
        Retorna kA primarios no terminal fechado."""
        br=self._find_branch(bf,bt,nc)
        if br is None or br['tipo']!='L': return None
        drop=list(self.dropB)+[(br['bf'],br['bt'],br['nc'])]
        S2=Solver(self.M, drop_branches=drop, block_btb=False); S2.factor()
        Z1,_,Z0=S2.zth(closed)
        if Z1 is None: return None
        z1L=complex(br['R1'],br['X1'])/100
        z0L=complex(br['R0'],br['X0'])/100 if (br.get('R0') is not None and br.get('X0') is not None) else None
        kvb=self.M.bus_kv.get(closed,0); Ib=SB/(np.sqrt(3)*kvb); zf=complex(Zf)
        Z1t=Z1+z1L; Z2t=Z1t
        if kind=='3F':
            I=1/(Z1t+zf)
        elif kind=='1FT':
            if Z0 is None or z0L is None: return None
            I=3/(Z1t+Z2t+(Z0+z0L)+3*zf)
        elif kind=='2F':
            I=np.sqrt(3)/(Z1t+Z2t+2*zf)
        else: return None
        return abs(I)*Ib

    def _clone_model(self):
        import copy as _c
        Mm=_c.copy(self.M)
        Mm.branches=list(self.M.branches)
        Mm.bus_kv=dict(self.M.bus_kv); Mm.bus_name=dict(self.M.bus_name)
        Mm.shunts=list(self.M.shunts)
        return Mm

    def fault_on_branch(self, bf, bt, nc, p, kind='3F', Zf=0.0):
        """Falta a fracao p (0..1, medida a partir de bf) ao longo de um RAMO SERIE
        (linha, perna de trafo, reator serie). Insere no de falta F que divide a impedancia
        em p*Z (bf->F) e (1-p)*Z (F->bt). Retorna dict com Icc em F e correntes que cada
        terminal (CT) enxerga — base para 87L, 87T e alcance de distancia a ponto intermediario.
        Para trafos, p e a fracao da IMPEDANCIA DE DISPERSAO (proxy de posicao de enrolamento sob
        hipotese de enrolamento uniforme); falta interna rigorosa exige o modelo de enrolamento."""
        br=self._find_branch(bf,bt,nc)
        if br is None: return None
        # orientar p a partir de bf conforme armazenado
        sbf,sbt=br['bf'],br['bt']
        if (bf,bt)==(sbt,sbf): p=1-p
        p=min(max(p,1e-4),1-1e-4)
        Mm=self._clone_model()
        F=max(Mm.bus_kv)+1
        kvL=self.M.bus_kv.get(sbf,0) or self.M.bus_kv.get(sbt,0)
        Mm.bus_kv[F]=kvL; Mm.bus_name[F]=("FLT%02d"%int(p*100))
        def seg(frac,a,b):
            d=dict(br); d['bf']=a; d['bt']=b
            for k in ('R1','X1','R0','X0'):
                d[k]=(br[k]*frac) if br.get(k) is not None else None
            d['S1']=None; d['S0']=None
            return d
        Mm.branches=[x for x in Mm.branches
                     if not (x['bf']==sbf and x['bt']==sbt and x['nc']==br['nc'])]
        Mm.branches += [seg(p,sbf,F), seg(1-p,F,sbt)]
        has_mut=any({m['bf1'],m['bt1']}=={sbf,sbt} or {m['bf2'],m['bt2']}=={sbf,sbt}
                    for m in self.M.mutuas)
        S2=Solver(Mm, block_btb=False); S2.factor()
        out={'kV':kvL,'p':p,'mutua_aprox':has_mut}
        out['If']=S2.fault(F,kind)
        ci=S2.branch_current(F, sbf,F,br['nc'],kind)
        cj=S2.branch_current(F, F,sbt,br['nc'],kind)
        out['I_term_%d'%sbf]=ci['Imax'] if ci else None
        out['I_term_%d'%sbt]=cj['Imax'] if cj else None
        if kind=='1FT' and br['tipo']=='L':
            out['3I0_term_%d'%sbf]=3*ci['I0'] if ci else None
            out['3I0_term_%d'%sbt]=3*cj['I0'] if cj else None
        return out

    def fault_on_shunt(self, bus, p, kind='1FT', Zf=0.0):
        """Falta a fracao p (0..1, a partir da BARRA em direcao ao neutro/terra) ao longo de um
        REATOR SHUNT ligado a 'bus'. Insere no F: bus --p*X-- F, F --(1-p)*X-- terra; falta em F.
        Para p->1 (perto do neutro) a corrente cai — curva de sensibilidade do 87/REF do reator."""
        H=None
        for h in self.M.shunts:
            if h['bus']==bus and h.get('X0') is not None and np.isfinite(h['X0']):
                H=h; break
        if H is None: return None
        p=min(max(p,1e-4),1-1e-4)
        Mm=self._clone_model()
        F=max(Mm.bus_kv)+1
        kvb=self.M.bus_kv.get(bus,0)
        Mm.bus_kv[F]=kvb; Mm.bus_name[F]=("RTFLT%02d"%int(p*100))
        # remove shunt original; adiciona serie bus->F (p*X) e shunt residual em F ((1-p)*X)
        Mm.shunts=[x for x in Mm.shunts if x is not H]
        x1=H.get('X1'); x0=H.get('X0')
        serie=dict(tipo='L',bf=bus,bt=F,nc='RT',
                   R1=(H.get('R0') or 0)*p, X1=(x1 if x1 and np.isfinite(x1) else x0)*p,
                   R0=(H.get('R0') or 0)*p, X0=x0*p, S1=None, S0=None,
                   cd='YN',cp='YN',rnde=None,xnde=None,rnpa=None,xnpa=None,nunop=1)
        Mm.branches=list(Mm.branches)+[serie]
        resid=dict(H); resid['bus']=F
        for k in ('X1','X0'):
            if resid.get(k) is not None and np.isfinite(resid[k]): resid[k]=resid[k]*(1-p)
        Mm.shunts=list(Mm.shunts)+[resid]
        S2=Solver(Mm, block_btb=False); S2.factor()
        return {'kV':kvb,'p':p,'If':S2.fault(F,kind),
                'I_terminal':(lambda c: c['Imax'] if c else None)(S2.branch_current(F,bus,F,'RT',kind))}

    def winding_ground_fault(self, term_bus, Zw_pct, npts=11, side_seq='0'):
        """Curva simplificada de falta a terra no enrolamento (estrela aterrada) para
        sensibilidade de 87REF. Modelo de enrolamento UNIFORME: para falta a fracao x das
        espiras a partir do neutro, FEM de acionamento = x*E e impedancia da secao = x^2*Zw.
        Usa Zth de sequencia zero da rede no terminal (base ANAFAS) + secao do enrolamento.
        Retorna lista (x, I_neutro_kA). REQUER hipotese de enrolamento uniforme; falta interna
        rigorosa exige distribuicao de espiras/dispersao do fabricante."""
        Z1,_,Z0=self.zth(term_bus)
        if Z0 is None: return None
        kvb=self.M.bus_kv.get(term_bus,0); Ib=SB/(np.sqrt(3)*kvb)
        Zw=complex(0,Zw_pct)/100.0
        out=[]
        for i in range(1,npts+1):
            x=i/npts
            # corrente de terra na secao faltosa: x*E / (x^2*Zw + Zsys0_ref)
            den=x*x*Zw + Z0
            I=abs(x*1.0/den)
            out.append((round(x,3), I*Ib))
        return out


    def _contribuicao_fc(self, bus, Ib):
        """Contribuição por elemento no modo completo, a partir do MESMO V convergido.

        A soma fecha com `fault_fc(bus,'3F')` por KCL, incluindo a parcela injetada por
        um conversor conectado na própria barra em falta, que aparece com a chave
        ('DEOL', bus, 0, '').
        """
        V, If, _ = self._estado_fc_robusto(bus)
        out = {}
        for br in self.M.branches:
            if bus not in (br['bf'], br['bt']):
                continue
            if (br['bf'], br['bt'], br['nc']) in self.dropB:
                continue
            o = br['bt'] if br['bf'] == bus else br['bf']
            if o not in self.IDXP:
                continue
            R, X = br['R1'], br['X1']
            if R is None or X is None:
                continue
            z = complex(R, X) / 100
            if abs(z) < 1e-9:
                continue
            out[(br['tipo'], br['bf'], br['bt'], br['nc'])] = abs(V[self.IDXP[o]] / z) * Ib
        fc = self._fc_sources()
        if bus in fc:
            j = self.IDXP[bus]
            inj = sum(self._inj_fc(r, V[j]) for r in fc[bus])
            if abs(inj) > 0:
                out[('DEOL', bus, 0, '')] = abs(inj) * Ib
        return out

    def _exigir_validacao_completo(self):
        """Bloqueia o modo completo enquanto o modelo de injeção não for validado.

        O modo completo só é liberado depois de `validar_completo()` conferir as
        correntes contra a seção de níveis do caso EM USO. Emitir número não validado
        num estudo de proteção é pior do que não emitir.
        """
        if not getattr(self, 'validado_completo', False):
            raise RuntimeError(
                "modo 'completo' bloqueado: o modelo de injeção DEOL ainda não foi "
                "validado neste caso. Rode Solver.validar_completo(niveis_kA) com a "
                "seção 'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO' do próprio caso, ou "
                "libere explicitamente com Solver.validar_completo(None, forcar=True) "
                "assumindo o risco.")

    def validar_completo(self, niveis_kA, kind='3F', limite=1.0, forcar=False):
        """Confere `fault_fc` contra a seção de níveis do ANAFAS e libera o modo completo.

        `niveis_kA`: {barra: corrente_kA} lida da seção de níveis do MESMO caso.
        Devolve dict com estatística do erro. Só libera o modo se o erro máximo ficar
        dentro de `limite` (%). `forcar=True` libera sem conferir, sob responsabilidade
        de quem chama.
        """
        if forcar:
            self.validado_completo = True
            self._selo_completo = dict(validado=False, forcado=True)
            return self._selo_completo
        erros = []
        for b, ref in (niveis_kA or {}).items():
            if b not in self.IDXP or not ref or ref <= 0:
                continue
            try:
                calc = self.fault_fc(b, kind)
            except RuntimeError:
                continue
            if calc:
                erros.append((b, (calc - ref) / ref * 100))
        if not erros:
            raise ValueError("nenhuma barra comparável entre o caso e os níveis fornecidos")
        v = np.array([e for _, e in erros])
        pior = max(erros, key=lambda t: abs(t[1]))
        selo = dict(n=len(v), erro_max=float(np.max(np.abs(v))),
                    mediana=float(np.median(np.abs(v))),
                    pct_dentro=float((np.abs(v) < limite).mean() * 100),
                    pior_barra=pior[0], pior_erro=float(pior[1]), limite=limite)
        self.validado_completo = selo['erro_max'] < limite
        selo['liberado'] = self.validado_completo
        self._selo_completo = selo
        return selo

    def conciliar(self, z1_ref, z0_ref=None, limite=1.0):
        """Confere Z1 e Z0 barra a barra contra a seção de impedâncias de barra.

        Pré-requisito para liberar um caso, não ferramenta de diagnóstico: é esta
        rotina que expõe, numa passada, divergência de leitura do arquivo.
        `z1_ref`/`z0_ref`: {barra: |Z| em pu}. Devolve dict com a estatística e a lista
        das barras fora do critério.
        """
        saida = {}
        for rot, ref, lu, idx, n in (('Z1', z1_ref, self.luP, self.IDXP, len(self.BLP)),
                                     ('Z0', z0_ref, self.lu0, self.I0P, len(self.BL0))):
            if not ref:
                continue
            fora, err = [], []
            alvos = [(b, idx[b]) for b in ref if b in idx and ref[b] and ref[b] > 0]
            for ini in range(0, len(alvos), 300):
                lote = alvos[ini:ini + 300]
                e = np.zeros((n, len(lote)), dtype=complex)
                for c, (_, kk) in enumerate(lote):
                    e[kk, c] = 1
                sol = lu.solve(e)
                for c, (b, kk) in enumerate(lote):
                    d = (abs(sol[kk, c]) - ref[b]) / ref[b] * 100
                    err.append(d)
                    if abs(d) >= limite:
                        fora.append((b, float(d)))
            if err:
                a = np.abs(np.array(err))
                saida[rot] = dict(n=len(a), erro_max=float(a.max()),
                                  mediana=float(np.median(a)),
                                  pct_dentro=float((a < limite).mean() * 100),
                                  fora=sorted(fora, key=lambda t: -abs(t[1])))
        saida['aprovado'] = all(v['erro_max'] < limite for k, v in saida.items()
                                if isinstance(v, dict))
        self.conciliado = saida['aprovado']
        return saida


def branches_at(model, bus, tipos=('L','T')):
    """Ramos incidentes na barra (lista de (bf,bt,nc)) — util para montar contingencias."""
    return [(br['bf'],br['bt'],br['nc']) for br in model.branches
            if bus in (br['bf'],br['bt']) and br['tipo'] in tipos]


def recomposicao_87b(model, bus, kinds=('3F','1FT')):
    """ICC_MIN de recomposicao para 87B: falta na barra energizada por UM elemento de cada vez.
    Para cada ramo (L ou perna 138 de banco de trafo) incidente na barra, isola a barra a esse
    unico elemento (dropa todos os demais incidentes) e calcula a falta. Retorna
    (tabela: [(rotulo,(bf,bt,nc),{kind:I_kA})], icc_min:{kind:I_kA}). Elementos que nao
    energizam a barra (Icc~0) aparecem na tabela e devem ser excluidos do ICC_MIN pelo analista."""
    inc=branches_at(model, bus)
    tab=[]; mins={k:float('inf') for k in kinds}
    for keep in inc:
        drop=[b for b in inc if b!=keep]
        S=Solver(model, drop_branches=drop); S.factor()
        vals={}
        for k in kinds:
            I=S.fault(bus, kind=k)
            vals[k]=I
            if I is not None and I>1e-3: mins[k]=min(mins[k], I)
        br=next(b for b in model.branches if (b['bf'],b['bt'],b['nc'])==keep)
        o=br['bt'] if br['bf']==bus else br['bf']
        rot=f"{br['tipo']} p/ {model.bus_name.get(o,'')[:12]}"
        tab.append((rot, keep, vals))
    return tab, mins


__all__ = ["AnaModel", "Solver", "branches_at", "recomposicao_87b", "SB", "num", "zfin", "zn3"]
