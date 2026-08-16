"""Montagem das redes de sequência, fatoração LU esparsa e cálculo de faltas.

Thévenin por coluna da Zbus sob demanda (método de vetores esparsos), evitando a inversa densa."""

from __future__ import annotations

import numpy as np, pickle, re
import json as _json
from scipy.sparse import lil_matrix, csc_matrix
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from collections import defaultdict

SB = 100.0   # potência base, MVA

from ._base import num, zfin, zn3

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
    def factor(self):
        self.luP=splu(self.YP); self.lu0=splu(self.Y0)

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

    def fault(self, bus, kind='3F', Zf=0.0, Vf=1.0):
        """kind: '3F','1FT','2F','2FT'. Zf em pu. Retorna corrente em kA primários.

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

    def _fc_sources(self):
        """Identifica fontes de corrente full-converter (tipo-G eólica) e suas injeções-limite.
        Retorna {bus: (Imax_pu, phi_cc_rad)}. Cacheado."""
        if hasattr(self,'_fcsrc'): return self._fcsrc
        fc={}
        for g in self.M.gens:
            b=g['bus']
            x0=g.get('X0'); x0inf = x0 is None or not np.isfinite(x0)
            x1d=g.get('X1d'); nun=g.get('nunop',1) or 1
            if x0inf and nun>1 and x1d and x1d>50:
                # corrente-limite por unidade ~ Vf/X1d_pu (saturação natural do conversor);
                # nunop unidades em paralelo
                Imax = nun/(x1d/100.0)
                fc[b]=(Imax, np.deg2rad(90.0))   # ~puramente reativa (FP_CC baixo)
        # bloco DEOL: I_max em Ampères -> pu na base da barra
        for b,dd in self.M.deol.items():
            kv=self.M.bus_kv.get(b,0)
            if not kv or not dd.get('Imax_A'): continue
            Ib_A = SB*1e3/(np.sqrt(3)*kv)   # corrente base em A (SB em MVA, kv em kV)
            Imax = dd['Imax_A']*dd.get('nunop',1)/Ib_A
            fpcc = dd.get('fpcc') or 0.1
            phi = np.arccos(min(max(fpcc,0.0),1.0))
            fc[b]=(Imax, phi)
        self._fcsrc=fc
        return fc

    def _norton(self):
        """Correntes nodais de Norton dos geradores síncronos (YP·Vflat = injeções que
        sustentam V=1 pu em vazio). Cacheado."""
        if hasattr(self,'_inorton'): return self._inorton
        N=len(self.BLP)
        self._inorton = self.YP.dot(np.ones(N,dtype=complex))
        return self._inorton

    def fault_fc(self, bus, niter=50, damp=0.3, tol=1e-5):
        """Curto 3F com fontes de corrente full-converter via solver NODAL completo.
        Mantém Ybus pura (Thévenin intacto). A injeção de cada eólica/solar usa a tensão
        CONVERGIDA da sua própria barra durante a falta (processo iterativo), defasada de
        phi_cc. Falta franca em k imposta por compensação de Thévenin (V_k=0).
        Retorna corrente de curto em kA.
        """
        if bus not in self.IDXP: return None
        kv=self.M.bus_kv.get(bus,0)
        if not kv: return None
        Ib=SB/(np.sqrt(3)*kv); k=self.IDXP[bus]; N=len(self.BLP)
        ek=np.zeros(N,dtype=complex); ek[k]=1
        zk=self.luP.solve(ek); Zkk=zk[k]
        Inorton=self._norton()
        fc=self._fc_sources()
        Ieol=np.zeros(N,dtype=complex)
        Ifault=0j
        for it in range(niter):
            V0=self.luP.solve(Inorton+Ieol)     # tensões sem a falta
            Ifault_new=V0[k]/Zkk                 # corrente que zera V_k (compensação)
            V=V0 - Ifault_new*zk                 # tensões com falta franca em k
            newIeol=np.zeros(N,dtype=complex)
            for jb,(Imax,phi) in fc.items():
                jj=self.IDXP.get(jb)
                if jj is None: continue
                Vj=V[jj]; Vjm=abs(Vj)
                if Vjm>0.99: continue            # afundamento<0.01 -> fonte fora
                ang=np.angle(Vj)-phi if Vjm>1e-6 else -phi
                newIeol[jj]=Imax*np.exp(1j*ang)
            Ieol=(1-damp)*Ieol+damp*newIeol
            if abs(Ifault_new-Ifault)<tol*abs(Ifault_new)+1e-9:
                Ifault=Ifault_new; break
            Ifault=Ifault_new
        return abs(Ifault)*Ib

    def contribution(self, bus, kind='3F'):
        """Contribuicao de corrente de cada elemento incidente na barra para uma falta
        solida na propria barra. kind='3F' (modulo da corrente de fase, seq. positiva)
        ou '0' (modulo de I0 por ramo, seq. zero). Retorna dict {(tipo,bf,bt,nc): I_kA}.
        So considera ramos EM SERVICO (fora de dropB). Base: KCL fecha na corrente total."""
        kvb=self.M.bus_kv.get(bus,0)
        if not kvb: return {}
        Ib=SB/(np.sqrt(3)*kvb)
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


