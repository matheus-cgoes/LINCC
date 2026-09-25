"""LINCC — Linguagem Natural em Curto-Circuito.

Motor de curto-circuito para sistemas de transmissão: lê casos em formato .ANA, monta as
redes de sequência positiva e zero e calcula equivalentes de Thévenin e correntes de falta
por fatoração LU esparsa.

NÃO substitui ferramenta homologada. Ver README para isenção de responsabilidade.

═══════════════════════════════════════════════════════════════════════════════════════
PROTOCOLO DE TRABALHO — vale para toda chamada, sem precisar ser repetido no pedido
═══════════════════════════════════════════════════════════════════════════════════════

1. Este motor é a fonte de verdade. Importe e use; não recrie a modelagem de memória, não
   reescreva o parser, não calcule nada à mão. Todo número de um estudo sai daqui.

2. VALIDE O CASO ANTES DE EMITIR CORRENTE, e conduza isso sozinho — o usuário não precisa
   conhecer nem executar os comandos.

   Toda base real do ONS traz 400 a 500 eólicas e fotovoltaicas conectadas por conversor,
   e o número regulatório é o que as inclui. O motor só o devolve depois de conferir a
   leitura deste caso contra o relatório do ANAFAS do MESMO caso:

       from lincc import niveis_kA
       selo = S.validar_completo(niveis_kA("RELATORIO.LST"), limite=1.0)

   O que fazer conforme a situação, sem transferir a decisão técnica ao usuário:

   a) Relatório anexado -> valide e siga. Informe o resultado em uma linha ("caso
      conferido contra o relatório, erro máximo X%").
   b) Relatório NÃO anexado -> PEÇA-O ao usuário, explicando em linguagem simples: é o
      relatório de níveis de curto-circuito do ANAFAS, do mesmo caso, e serve para
      conferir a leitura do arquivo antes de emitir corrente.
   c) Usuário não tem o relatório -> explique as duas alternativas em português corrente,
      SEM mencionar nomes de função: ou você segue com o número que inclui as usinas de
      conversor, sem essa conferência, ou usa o valor conservador que as exclui. Pergunte
      qual ele prefere, execute (`liberar_completo_sem_gabarito()` ou
      `modo='sincronas'`) e REGISTRE a hipótese no relatório final.

   Nunca escolha em silêncio, e nunca devolva comando para o usuário executar.

3. BASES DO ANAREDE (.PWF), quando anexadas. Use-as sem que o usuário precise pedir:

   - Carga máxima dos circuitos: passe os cenários a `ajuste_sobrecorrente(...,
     cenarios=...)`. A carga sai da capacidade de EMERGÊNCIA declarada no ANAREDE, em vez
     de ser pedida ao usuário. Todo pickup que dependa de carga fica acima desse limite:
     em regime de emergência o equipamento não pode ser desligado pela proteção.
   - Curto-circuito entre cenários: `fluxo.curto_por_cenario(M, cenarios, barras)`. O
     ANAFAS calcula sempre a rede completa; os cenários retiram as usinas paradas, e o
     MÍNIMO de curto para sensibilidade costuma cair bem abaixo da rede completa (15% numa
     barra de 500 kV do caso de referência). O envelope já sai conservador nos dois lados:
     máximo com os geradores sem correspondência ligados, mínimo com eles desligados.
   - Antes de usar as duas bases juntas, `conciliar_bases(M, P)` e registre o resultado.

   Declare no relatório que os valores por cenário não têm gabarito no ANAFAS — ele não
   calcula despacho parcial — e informe a incerteza de mapeamento que o retorno traz.
   Fluxo por circuito é estimativa: o arquivo grava tensão com 3 casas, e o retorno traz
   a incerteza de cada valor. As capacidades são exatas.

4. DECLARE TODAS AS PREMISSAS. Toda função de alto nível devolve `premissas`: a lista do
   que foi assumido no cálculo — modo, tensão pré-falta, critérios de ajuste, origem da
   carga, hipóteses de despacho. Apresente-a ao usuário, sempre que a função for usada,
   em linguagem de engenharia. Nenhum número deve chegar ao usuário sem as premissas que
   o produziram.

5. AJUSTE SE REFERE À CAPACIDADE, NUNCA AO FLUXO. Todo ajuste que possa limitar a
   transmissão usa a capacidade do equipamento — de emergência quando declarada —, e não
   o carregamento de um cenário. A proteção é do equipamento: ajustar abaixo da
   capacidade limita o equipamento e pode atuar em contingência. O fluxo do ANAREDE é
   informação, não base de ajuste. Critérios completos em docs/metodologia-protecao.md.

6. REPORTE ESTADO E FALHAS. Cada função de ajuste traz `estado` —
   calculavel_verificada, faixa_inviavel, dados_faltantes, modelo_nao_suportado,
   validacao_pendente ou erro_execucao — e os estudos trazem `falhas`. Apresente o estado
   de cada item ao usuário; nunca mostre faixa sem estado nem omita uma falha. Um resultado
   em validacao_pendente não é resultado aprovado.

7. CRITÉRIOS DO USUÁRIO VÊM DO PEDIDO. Múltiplos de carga, escalas entre funções e
   margens de filosofia não têm padrão no código: se o usuário os informar, passe-os em
   `criterios`; se não, apresente a faixa admissível e diga que o critério falta. Ajuste
   de relé só é exportável com perfil de IED documentado (`perfil_ied`); sem ele, o
   resultado é insumo de estudo — diga isso ao usuário.

8. Não invente dado ausente. Relação de TC, ajuste de IED, placa de equipamento,
   capacidade de interrupção e carga máxima operativa NÃO estão no .ANA. As funções de
   alto nível devolvem `dados_faltantes` com o que falta e o critério que cada item
   bloqueia — reporte a lista em vez de estimar.

9. Declare o modo. 'completo' (padrão) inclui a contribuição de eólicas e fotovoltaicas
   conectadas por conversor; 'sincronas' é o Thévenin puro. Perto dessas usinas a
   diferença passa de 40%. Não misture os dois num mesmo critério.

10. Correntes saem em kA PRIMÁRIOS. Com TC, a corrente de base do estudo é a nominal
   primária do TC, não a do equipamento protegido.

11. Três armadilhas de modelagem: o identificador de circuito é STRING ('1', não 1); um
   banco de três enrolamentos exige remover TODAS as pernas do nó-estrela; e se o
   equipamento novo já está na base, o cenário "antes" é o contrafactual — remova-o.

FUNÇÕES DE ALTO NÍVEL — resolvem o estudo inteiro numa chamada

    impacto_entrada(M, [(bf, bt, nc)])        evolução de curto pela entrada de um
                                              equipamento, nos quatro tipos de defeito,
                                              com as barras acima do gatilho de 10% e o
                                              tipo que governou

    relatorio_curto(M, barra)                 correntes, Thévenin e contribuições

    estudo_barra(M, barra, dados, cenarios)   estudo de proteção de barra completo: 87B,
                                              checkzone, alarme, 50BF e EFP, com a
                                              corrente mínima entre rede completa, N-1,
                                              recomposição e cenários do ANAREDE. É a
                                              resposta padrão a "proteção da barra X",
                                              "pickup do 87B", "checkzone", "50BF", "EFP".
                                              Leva alguns minutos numa base do SIN — avise
                                              o usuário antes de rodar

    estudo_87L(M, (bf, bt, nc))              diferencial de linha: faixa do pickup entre a
                                              corrente capacitiva e a menor falta interna,
                                              e a maior passante externa como referência

    estudo_distancia(M, (bf, bt, nc))        proteção de distância: impedância aparente por
                                              laço em rede completa e N-1, limites de alcance
                                              das zonas, k0 (e Kr/Kx), SIR como indicador,
                                              região de carga pela emergência. Sem alcances
                                              informados, devolve os limites; com eles, as
                                              margens

    ajuste_sobrecorrente(M, tipo, elemento)   faixas admissíveis das funções de
                                              sobrecorrente (51, 50, SOTF, STUB, 67NT na
                                              linha; 51 e 50 no transformador) e se cada
                                              uma é viável, com a 51V quando a falta
                                              remota mínima fica abaixo do 51 (partida em
                                              0,8 pu e verificação da tensão no relé).
                                              NÃO escolhe o ajuste: devolve
                                              a faixa e o limite que governa. Faixa vazia
                                              significa função inviável — reporte, com o
                                              motivo, em vez de propor valor fora dela

    relatorio_protecao(M, tipo, elemento)     tipo: 'linha', 'transformador', 'barra',
                                              'reator' ou 'capacitor'. Traz as grandezas
                                              do tipo, N-1, as funções que o Submódulo
                                              2.11 exige e os dados faltantes

Elas embutem o protocolo acima. Um pedido não precisa enumerar tipos de defeito,
contingências nem formato de saída.

═══════════════════════════════════════════════════════════════════════════════════════
OS DOIS MODOS — a escolha muda o resultado
═══════════════════════════════════════════════════════════════════════════════════════

    M = AnaModel("caso.ANA");  S = Solver(M);  S.factor()

    S = Solver(M)                          modo 'completo' (PADRÃO)
    S = Solver(M, modo='sincronas')        Thévenin puro, sem conversores

O MODO É PROPRIEDADE DO SOLVER, não parâmetro de cada chamada. Toda grandeza da instância
— fault, contribution, branch_current, bus_voltage, line_end_open, fault_on_branch,
fault_on_shunt, envelope — segue o mesmo modo, e os solvers internos de cenário o herdam.

Passar `modo=` numa chamada isolada é exceção, para comparar os dois num mesmo estudo; a
diferença tem de ser declarada no relatório.

`completo` inclui as eólicas e fotovoltaicas conectadas por conversor (bloco DEOL) e é o
padrão, por ser o número regulatório. `sincronas` é o Thévenin puro da Ybus e as exclui.
Perto dessas usinas a diferença passa de 40% — não é refinamento, é outra resposta.

Cada modo tem uma âncora de validação distinta no relatório do ANAFAS. Confundi-las é o
erro mais comum e reprova função que está correta:

    sincronas  ->  'RELATORIO DE DADOS DE CURTO-CIRCUITO'    (MVA; exclui conversores)
    completo   ->  'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO'   (kA;  inclui conversores)

Não misture modos dentro de um mesmo critério. O envelope de TC combina ICC_MAX de um
cenário com ICC_MIN de outro: usar `sincronas` de um lado e `completo` do outro produz
margem fictícia.

QUAL USAR
    completo   capacidade de interrupção, saturação de TC, esforços eletrodinâmicos,
               limite superior de DiffOperLevel — é o número regulatório.
    ambos      sensibilidade, ICC_MIN, pickup de 51/51N, alcance de zonas. Conversor pleno
               não é fonte confiável em curto sustentado, e o mínimo com inversores pode
               ser maior ou menor conforme o afundamento. Assumir só um lado é que é erro.

Num caso COM registros DEOL, o modo completo vem BLOQUEADO até ser conferido contra o
próprio caso. Num caso sem DEOL, os dois modos coincidem e nada precisa ser validado.

    selo = S.validar_completo(niveis_kA, limite=1.0)     # {barra: corrente_kA}

Chame `lincc.orientacao()` para o guia completo de tolerância e limitações conhecidas.

ARQUIVO ÚNICO. Gerado por ferramentas/gerar_bundle.py a partir de src/lincc/ — não editar
à mão. Aqui todos os nomes do pacote são globais: use `import lincc_bundle as lincc` e as
chamadas documentadas acima valem como estão, inclusive lincc.fluxo.*, lincc.curvas.*,
lincc.sm211.* e lincc.dados_externos.*. Requer apenas numpy e scipy.
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
            # Potência nominal do elemento, coluna MVA do DCIR [176:184]. É a única
            # grandeza de CAPACIDADE que o .ANA traz — não há corrente de carregamento
            # nem limite operativo. Quando preenchida (14.105 de 24.405 registros no caso
            # de referência), dispensa o usuário de informar a nominal para o pickup do
            # 51 de linha e do transformador. Valor direto em MVA, sem escala implícita.
            MVA = _numf(ln[176:184]) if len(ln) > 176 else None
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
                # identidade do banco: circuito na mesma coluna dos demais ramos
                self.caps.append(dict(bf=bff, bt=btt, nc=ln[14:16].strip() or '1',
                                      tipo='S', X1=X1, X0=X0))
            elif tipo == 'L':
                cd,cp = self._conns(ln)
                self.branches.append(dict(tipo='L', bf=bff, bt=btt, nc=ln[14:16].strip(),
                                          R1=R1,X1=X1,R0=R0,X0=X0,S1=S1,S0=S0,MVA=MVA))
            elif tipo == 'T':
                cd,cp = self._conns(ln)
                rnde,xnde,rnpa,xnpa = self._aterr(ln)
                nn = ln[115:121].split() if len(ln) > 115 else []
                try: tnun = int(nn[-1]) if nn else 1
                except: tnun = 1
                self.branches.append(dict(tipo='T', bf=bff, bt=btt, nc=ln[14:16].strip(),
                                          R1=R1,X1=X1,R0=R0,X0=X0,cd=cd,cp=cp,
                                          rnde=rnde,xnde=xnde,rnpa=rnpa,xnpa=xnpa,nunop=tnun,
                                          MVA=MVA))
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
                nc = ln[12:16].strip() or '1'           # circuito da linha do reator
                self.shl.append(dict(bf=bf,bt=bt,nc=nc,term=term,Q=q,conn='YN',
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




# ====================================================================== #
#  Leitura dos relatórios do ANAFAS                                      #
# ====================================================================== #

# Cada seção tem régua própria, medida no próprio relatório. Duas armadilhas tratadas
# aqui, ambas descobertas por divergência numérica e ambas produzindo número plausível
# e errado:
#
#   1. O cabeçalho do relatório de níveis é ACENTUADO ('RELATÓRIO DE NÍVEIS'). Delimitar
#      seção procurando só por 'RELATORIO' faz a leitura atravessar para dentro dele.
#   2. Valor mais largo que a coluna invade o campo anterior, e a leitura por posição
#      absoluta perde o dígito inicial. Cada campo é lido da borda direita do campo
#      anterior até a sua própria borda.
_SECOES = {
    'niveis': dict(
        titulo='NÍVEIS DE CURTO-CIRCUITO', num=(2, 7), inicio=21,
        campos=[('vbas', 27), ('i3m', 37), ('i3a', 44), ('i3xr', 53), ('i3as', 61),
                ('i1m', 71), ('i1a', 78), ('i1xr', 87), ('i1as', 95),
                ('i2m', 105), ('i2a', 112), ('i2xr', 121), ('i2as', 129)]),
    'impedancias': dict(
        titulo='RELATORIO DE IMPEDANCIAS DE BARRA', num=(1, 6), inicio=20, escala=1 / 100.0,
        campos=[('z1m', 36), ('z1a', 53), ('z0m', 70), ('z0a', 87), ('zrm', 104), ('zra', 121)]),
}
_FIM_SECAO = ('RELATORIO DE', 'RELATÓRIO DE')
_EM_PU = {'z1m', 'z0m', 'zrm'}


def ler_relatorio(caminhos, secao='niveis'):
    """Lê uma seção do relatório do ANAFAS. Devolve {barra: {campo: valor}}.

    `caminhos` é um arquivo ou uma lista deles — as seções podem estar separadas.
    `secao`: 'niveis' (correntes em kA, inclui os conversores) ou 'impedancias'
    (Z1, Z0 e Z0+Z2 em pu, 10 decimais).
    """
    cfg = _SECOES.get(secao)
    if cfg is None:
        raise ValueError(f"secao deve ser uma de {sorted(_SECOES)}, recebido {secao!r}")
    if isinstance(caminhos, (str, bytes)):
        caminhos = [caminhos]
    a_num, b_num = cfg['num']
    escala = cfg.get('escala', 1.0)
    saida = {}
    for caminho in caminhos:
        with open(caminho, 'rb') as f:
            linhas = f.read().decode('cp1252', errors='replace').splitlines()
        ini = next((i for i, ln in enumerate(linhas) if cfg['titulo'] in ln), None)
        if ini is None:
            continue
        fim = next((i for i in range(ini + 1, len(linhas))
                    if any(h in linhas[i] for h in _FIM_SECAO)), len(linhas))
        for ln in linhas[ini + 1:fim]:
            if len(ln) < 20 or not ln[a_num:b_num].strip().isdigit():
                continue
            d = saida.setdefault(int(ln[a_num:b_num]), {})
            esq = cfg['inicio']
            for nome, dir_ in cfg['campos']:
                bruto = ln[esq:dir_].strip() if len(ln) >= esq else ''
                esq = dir_
                if not bruto:
                    continue
                try:
                    v = float(bruto)
                except ValueError:
                    continue            # '*****' = estouro total do campo
                d[nome] = v * escala if nome in _EM_PU else v
    return saida


def niveis_kA(caminhos, kind='3F'):
    """Correntes de curto-circuito do relatório, prontas para `Solver.validar_completo`.

    Devolve {barra: corrente_kA} para o tipo pedido: '3F', '1FT' ou '2FT'. É a seção que
    INCLUI a contribuição dos geradores conectados por conversor, e portanto a âncora de
    validação do modo completo.
    """
    col = {'3F': 'i3m', '1FT': 'i1m', '2FT': 'i2m'}.get(kind)
    if col is None:
        raise ValueError(f"kind deve ser '3F', '1FT' ou '2FT', recebido {kind!r}")
    return {b: d[col] for b, d in ler_relatorio(caminhos, 'niveis').items()
            if d.get(col, 0) > 0}


def impedancias_pu(caminhos):
    """Z1 e Z0 do relatório de impedâncias, para `Solver.conciliar`.

    Devolve (z1, z0), cada um {barra: |Z| em pu}.
    """
    d = ler_relatorio(caminhos, 'impedancias')
    return ({b: v['z1m'] for b, v in d.items() if v.get('z1m', 0) > 0},
            {b: v['z0m'] for b, v in d.items() if v.get('z0m', 0) > 0})


# ===================== parser do .PWF (ANAREDE) =====================

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


# ===================== Ybus, LU e faltas =====================

class Solver:
    def __init__(self, model, drop_branches=None, drop_gens=None, block_btb=True,
                 dispatch_file=None,   # despacho inferido OBSOLETO: estados do DBAR ('d') cobrem o caso
                 charging=False, modo='completo', manter_reatores=None,
                 drop_reatores_barra=None, bypass_capacitores=None):
        """`charging`: representar a capacitância de linha (campos S1 e S0), em π.

        PADRÃO DESLIGADO, e a razão é medida. O relatório de impedâncias de barra do
        ANAFAS — o gabarito contra o qual o motor é validado — NÃO inclui o charging:
        com ele ligado, Z1 cai de 100,000% para 50,4% das barras dentro de 1%, nas duas
        bases testadas. Logo o cálculo de impedância de barra do ANAFAS é sem charging.

        Já o cálculo de FALTA com terminal aberto o inclui: no caso de referência o
        trecho aberto injeta 33 A no ponto de falta, e a trifásica difere 4,11% do que o
        motor calcula sem ele. As duas coisas convivem no ANAFAS.

        Ligue apenas quando a capacitância importar para a grandeza em questão — falta
        com terminal aberto, linha longa em vazio — e NUNCA para conciliar contra o
        relatório de impedâncias, que reprovaria função correta.
        """
        self.M = model
        self.charging = bool(charging)
        # Reator de linha sai junto com a linha retirada: com a linha aberta nos dois
        # terminais, o reator deixa de ser caminho para a terra na barra. Exceção em
        # `manter_reatores`: linha pendurada no terminal fechado (terminal remoto aberto),
        # que continua conectada com os seus reatores.
        self.manterShl = {(a, b, str(c)) for a, b, c in (manter_reatores or [])}
        # Barras cujos reatores de barra estão desligados no cenário — o reator é um vão
        # da subestação e sai, por exemplo, na recomposição por um só elemento.
        self.dropH = set(drop_reatores_barra or [])
        # Capacitor série tem dois estados físicos distintos: em drop_branches o banco sai e
        # o circuito ABRE; em bypass_capacitores o banco é curto-circuitado e a linha segue
        # contínua sem a compensação. São cenários diferentes e não se confundem.
        self.bypassC = {(a, b, str(c)) for a, b, c in (bypass_capacitores or [])}
        self.block_btb_arg = block_btb
        self.dropG_arg = drop_gens
        if modo not in ('sincronas', 'completo'):
            raise ValueError(f"modo deve ser 'sincronas' ou 'completo', recebido {modo!r}")
        # Modo global da instância: toda grandeza calculada por este Solver segue este
        # modo, e os solvers internos de cenário o herdam. Um estudo tem um modo;
        # misturar dentro do mesmo envelope produz margem fictícia.
        self.modo = modo
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
            if self.charging and br['tipo']=='L' and br.get('S1'):
                yh = 1j*(br['S1']/100.0)/2      # modelo pi: metade em cada extremidade
                YP[i,i]+=yh; YP[j,j]+=yh
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
            kc=(bf,bt,str(c.get('nc','1'))); kr=(bt,bf,kc[2])
            if kc in self.dropB or kr in self.dropB: continue      # banco aberto
            x=(c['X1'] or 0)/100
            if kc in self.bypassC or kr in self.bypassC: x=1e-6   # banco em bypass
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
            bsh=(br.get('S0') or 0.0)/100.0 if self.charging else 0.0
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
            kc=(bf,bt,str(c.get('nc','1'))); kr=(bt,bf,kc[2])
            if kc in self.dropB or kr in self.dropB: continue      # banco aberto
            x=(c['X0'] or 0)/100
            if kc in self.bypassC or kr in self.bypassC: x=1e-6   # banco em bypass
            if abs(x)<1e-12 or not np.isfinite(x): continue
            i,j=IDX0[bf],IDX0[bt]; ys=1/(1j*x)
            Y[i,j]-=ys; Y[j,i]-=ys; Y[i,i]+=ys; Y[j,j]+=ys
        # Shunt de barra H: o registro já fornece a impedância homopolar R0+jX0.
        # RN/XN do lado do equipamento não é somado novamente (validado A/B vs ANAFAS).
        for h in M.shunts:
            b=h['bus']
            if b not in IDX0 or b in self.dropH: continue
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
            k=(s['bf'], s['bt'], str(s.get('nc','1'))); kr=(k[1], k[0], k[2])
            if (k in self.dropB or kr in self.dropB) and not (
                    k in self.manterShl or kr in self.manterShl):
                continue                              # linha retirada: reator sai junto
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
        self._gmut={}; self._Zseg=dict(Zseg)
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
            g=(segs, idx, Yp, seg_nodes)       # referência compartilhada, sem cópia por segmento
            for s in segs:
                self._gmut[s]=g
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
                "        O modo PADRÃO ('completo') inclui a contribuição deles e precisa ser\n"
                "        liberado contra o próprio caso:\n"
                "            S.validar_completo(niveis_kA, limite=1.0)\n"
                "        onde niveis_kA vem do 'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO'.\n"
                "        Para o Thévenin puro, sem essas fontes: fault(bus, kind, modo='sincronas').\n"
                "        Guia completo em lincc.orientacao()."
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

    def fault(self, bus, kind='3F', Zf=0.0, Vf=1.0, modo=None):
        """kind: '3F','1FT','2F','2FT'. Zf em pu. Retorna corrente em kA primários.

        modo='completo' (PADRÃO): inclui as injeções dos geradores de conversor pleno
            (bloco DEOL). Âncora de validação: 'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO'
            (kA). É o número regulatório, e por isso é o padrão. Zf não é suportado aqui.
        modo='sincronas': Thévenin puro da Ybus, SEM essas fontes. Âncora de validação:
            'RELATORIO DE DADOS DE CURTO-CIRCUITO' (MVA).

        Num caso SEM registros DEOL os dois modos coincidem e nada precisa ser validado.
        Com DEOL, o modo completo exige `validar_completo()` antes de responder — emitir
        injeção não conferida contra o próprio caso é pior do que não emitir.

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
        """
        modo = self._modo(modo)
        if modo == 'completo' and self._tem_fc():
            self._exigir_validacao_completo()
            return self.fault_fc(bus, kind, Zf=Zf)
        kv=self.M.bus_kv.get(bus,0)
        if not kv: return None
        Ib=SB/(np.sqrt(3)*kv)
        Z1,Z2,Z0=self.zth(bus)
        if Z1 is None: return None
        zf=complex(Zf)
        den={'3F':Z1+zf,'2F':Z1+Z2+2*zf,
             '1FT':(Z1+Z2+Z0+3*zf) if Z0 is not None else None}.get(kind)
        if den is not None and (abs(den)<1e-12 or not np.isfinite(den)):
            # impedância equivalente nula ou indefinida: ressonância no modelo ou curto
            # franco já presente. Um valor infinito ou nulo não é resultado válido.
            raise ValueError(f"falta {kind} em {bus}: impedância equivalente nula ou "
                             f"indefinida (ressonância série no modelo?)")
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

    def _zbarra_fontes(self, idxs):
        """Submatriz da Zbarra entre as barras indicadas, recortada de um cache.

        A submatriz entre as barras com fonte de conversor depende só da topologia desta
        instância: não da barra em falta nem do tipo de defeito. É calculada uma vez para
        todas as fontes e recortada a cada chamada — o que evita centenas de solves
        repetidos quando o mesmo caso é consultado em vários pontos ou tipos de falta.
        """
        cache = getattr(self, '_zfontes', None)
        if cache is None:
            todas = sorted({self.IDXP[b] for b in self._fc_sources() if b in self.IDXP})
            N = len(self.BLP)
            n = len(todas)
            Z = np.empty((n, n), dtype=complex)
            BLOCO = 32      # resolve em blocos: a coluna completa tem N linhas, só n interessam
            for c0 in range(0, n, BLOCO):
                cols = todas[c0:c0 + BLOCO]
                E = np.zeros((N, len(cols)), dtype=complex)
                for c, j in enumerate(cols):
                    E[j, c] = 1
                Z[:, c0:c0 + len(cols)] = self.luP.solve(E)[todas, :]
            cache = self._zfontes = ({j: c for c, j in enumerate(todas)}, Z)
        pos, Z = cache
        sel = [pos[j] for j in idxs]
        return Z[np.ix_(sel, sel)]

    def _estado_fc(self, bus, niter=400, damp=1.0, tol=1e-8, strict=True,
                   ang_prefalta=False, tol_saida=1e-5, Zf=0.0):
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
        zk = self.luP.solve(ek); Zkk = zk[k] + complex(Zf)   # Zf: falta não franca
        Inorton = self._norton()
        fc = self._fc_sources()

        def resolver(Ieol):
            V0 = self.luP.solve(Inorton + Ieol)
            If = V0[k] / Zkk                    # Zkk já inclui Zf
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
        Zsub = self._zbarra_fontes(idxs)                # n x n
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
        passo_base = damp
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
            # PASSO ADAPTATIVO. O passo cheio de Newton diverge quando as fontes estão
            # fortemente acopladas entre si — na barra 45019 do caso de referência o
            # acoplamento fora da diagonal de Zf chega a 31x a diagonal, e com damp=1,0 o
            # resíduo sobe a 7,9 pu. Reduzir o passo faz convergir para o mesmo valor
            # (23,149 kA com damp de 0,5 a 0,1), então é instabilidade do passo, não
            # ausência de solução. Aceita-se o fator que reduza o resíduo; se nenhum
            # reduzir, o menor evita o salto que divergiria.
            passo, melhor_res, melhor = passo_base, res, None
            for fator in (passo_base, passo_base / 2, passo_base / 4,
                          passo_base / 8, passo_base / 16):
                cand = Ivec + fator * dI
                Vc = Vth + Zf @ cand
                gc = np.array([sum(self._inj_fc(r, Vc[c], angs[c]) for r in ativos[c][2])
                               for c in range(n)], dtype=complex) - cand
                rc = float(np.max(np.abs(gc)))
                if melhor is None or rc < melhor_res:
                    melhor_res, melhor, passo = rc, cand, fator
                if rc < res:
                    break
            Ivec = melhor if melhor is not None else Ivec + (passo_base / 16) * dI
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

    def fault_fc(self, bus, kind='3F', niter=60, damp=1.0, tol=1e-8, strict=True, Zf=0.0):
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
        zf = complex(Zf)
        if kind == '3F':
            _, If, _ = self._estado_fc_robusto(bus, niter=niter, damp=damp, tol=tol, Zf=zf)
            return abs(If) * Ib
        # Faltas desequilibradas. O conversor injeta APENAS em sequência positiva (manual
        # do ANAFAS, item 2.8.3), então a iteração acontece na rede positiva — a mesma de
        # sempre. O que muda é a impedância que a falta apresenta a essa rede:
        #
        #     1FT   Z_eq = Z2 + Z0 + 3·Zf          I_fase = 3·Ia1
        #     2F    Z_eq = Z2 + 2·Zf               I_fase = √3·Ia1
        #     2FT   Z_eq = Z2 ∥ (Z0 + 3·Zf)        composição das três sequências
        #
        # Basta resolver o estado com esse Z_eq no lugar de Zf, e a máquina iterativa
        # cuida do resto: a tensão da barra em falta NÃO é zero numa falta assimétrica, e
        # é justamente essa tensão que define a injeção de cada conversor.
        #
        # Na falta 3F a tensão terminal colapsa e as injeções saturam; na assimétrica
        # elas ficam na rampa da curva. Por isso o estado precisa ser resolvido com a
        # falta correta, e não derivado do trifásico.
        #
        # Na falta assimétrica a tensão de sequência positiva da barra NÃO colapsa, e o
        # conversor responde à própria tensão terminal — tipicamente na RAMPA da curva do
        # SM 2.10, não saturado. Conferido pelo inverso em barras de parque do caso de
        # referência: a fração da curva que este código usa é a mesma que reproduz o
        # relatório (0,608 contra 0,608 em 77481 com |V1| = 0,637; 0,798 contra 0,798 em
        # 77485 com |V1| = 0,571). É justamente isso que a formulação antiga perdia, ao
        # reaproveitar o estado trifásico onde a tensão colapsa e a injeção satura.
        #
        # Ao medir a monofásica em barra de parque, filtre por corrente com significado
        # físico: 91% dessas barras têm corrente de referência abaixo de 0,05 kA, porque
        # o transformador do parque é delta e a sequência zero não passa. Sobre 40 A, uma
        # diferença de 5 A aparece como "12% de erro". Acima de 0,5 kA, 100% das barras
        # ficam dentro de 1%, com mediana de 0,012%.
        Z1, Z2, Z0 = self.zth(bus)
        if Z1 is None:
            return None
        if kind == '2F':
            zeq = Z2 + 2 * zf
            fator = np.sqrt(3)
        else:
            if Z0 is None:
                return None
            if kind == '1FT':
                zeq = Z2 + Z0 + 3 * zf
                fator = 3.0
            elif kind == '2FT':
                z0f = Z0 + 3 * zf
                if abs(Z2 + z0f) < 1e-18:
                    return None
                zeq = Z2 * z0f / (Z2 + z0f)
                fator = None
            else:
                return None
        _, Ia1, _ = self._estado_fc_robusto(bus, niter=niter, damp=damp, tol=tol, Zf=zeq)
        if Ia1 is None:
            return None
        if fator is not None:
            return abs(fator * Ia1) * Ib
        # 2FT: distribuir Ia1 entre negativa e zero e compor as fases.
        # A composição JÁ devolve corrente de fase — sem o √3 da fórmula fechada de
        # `fault`, onde ele é convenção reconciliada com o relatório sobre uma grandeza
        # intermediária, não corrente de fase. Aplicar os dois erra por exatamente √3.
        z0f = Z0 + 3 * zf
        Ia2 = -Ia1 * z0f / (Z2 + z0f)
        Ia0 = -Ia1 * Z2 / (Z2 + z0f)
        a = np.exp(2j * np.pi / 3)
        ib = Ia0 + a * a * Ia1 + a * Ia2
        ic = Ia0 + a * Ia1 + a * a * Ia2
        return max(abs(ib), abs(ic)) * Ib

    def contribution(self, bus, kind='3F', modo=None):
        """Contribuicao de corrente de cada elemento incidente na barra para uma falta
        solida na propria barra. kind='3F' (modulo da corrente de fase, seq. positiva)
        ou '0' (modulo de I0 por ramo, seq. zero). Retorna dict {(tipo,bf,bt,nc): I_kA}.
        So considera ramos EM SERVICO (fora de dropB). Base: KCL fecha na corrente total."""
        modo = self._modo(modo)
        kvb=self.M.bus_kv.get(bus,0)
        if not kvb: return {}
        Ib=SB/(np.sqrt(3)*kvb)
        if modo=='completo' and self._tem_fc():
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
        elif kind=='2FT':
            # Bifásica-terra: sequências negativa e zero em paralelo, vistas da positiva.
            if Z0ff is None: return None
            z2f, z0f = Z2ff+zf, Z0ff+zf
            par = z2f*z0f/(z2f+z0f) if abs(z2f+z0f)>1e-18 else 0j
            Ia1 = 1/(Z1ff+zf+par)
            Ia2 = -Ia1*z0f/(z2f+z0f) if abs(z2f+z0f)>1e-18 else 0j
            Ia0 = -Ia1*z2f/(z2f+z0f) if abs(z2f+z0f)>1e-18 else 0j
        else: return None
        V1=np.ones(len(self.BLP),dtype=complex)-Z1col*Ia1
        V2=-Z1col*Ia2
        V0=(-Z0col*Ia0) if (Z0col is not None and Ia0!=0) else None
        return dict(V1=V1,V2=V2,V0=V0,Ia1=Ia1,Ia2=Ia2,Ia0=Ia0,Z1ff=Z1ff,Z0ff=Z0ff)

    CACHE_DERIVADOS_MAX = 4     # topologias derivadas guardadas por instância (~160 MB cada)

    def _cache_guardar(self, chave, valor):
        """Guarda uma topologia derivada, descartando a mais antiga acima do limite."""
        cache = self.__dict__.setdefault('_cache_derivados', {})
        while len(cache) >= self.CACHE_DERIVADOS_MAX:
            cache.pop(next(iter(cache)))
        cache[chave] = valor
        return valor

    def _clone_model(self):
        """Cópia do caso com listas e dicionários próprios, para montar topologia derivada
        sem alterar o caso original."""
        import copy as _c
        Mm = _c.copy(self.M)
        for k in ('branches', 'shunts', 'shl', 'gens', 'caps', 'mutuas', 'svc', 'zig'):
            if hasattr(self.M, k):
                setattr(Mm, k, list(getattr(self.M, k)))
        for k in ('bus_kv', 'bus_name', 'deol'):
            if hasattr(self.M, k):
                setattr(Mm, k, dict(getattr(self.M, k)))
        if hasattr(self.M, 'eol'):
            Mm.eol = set(self.M.eol)
        return Mm

    def _derivado(self, Mm=None, drop_extra=(), manter_extra=(), dropH_extra=(), modo=None):
        """Solver derivado desta instância, herdando TUDO o que define o cenário: ramos,
        geradores e reatores retirados, reatores mantidos, bypass de capacitores, charging,
        modo e a conferência do caso. Uma topologia derivada nunca reintroduz um elemento
        que o cenário de origem tirou."""
        S2 = Solver(Mm if Mm is not None else self.M,
                    drop_branches=list(self.dropB) + list(drop_extra),
                    drop_gens=list(self.dropG) or None,
                    block_btb=getattr(self, 'block_btb_arg', True),
                    charging=self.charging, modo=self._modo(modo),
                    manter_reatores=list(self.manterShl) + list(manter_extra),
                    drop_reatores_barra=list(self.dropH) + list(dropH_extra),
                    bypass_capacitores=list(self.bypassC))
        S2.factor(avisar=False)
        if S2.modo == 'completo' and S2._tem_fc():
            S2.validado_completo = bool(getattr(self, 'validado_completo', False))
            S2._selo_completo = getattr(self, '_selo_completo', None)
        return S2

    def _perfil(self, fault_bus, kind='3F', Zf=0.0, modo=None):
        """Perfis de sequência (V1, V2, V0 e Ia1, Ia2, Ia0) de UM estado de solução.

        No modo completo a sequência positiva é o estado convergido com as fontes de
        conversor, e as sequências negativa e zero são as respostas das redes passivas às
        correntes desse mesmo estado. Correntes de ramo e tensões derivadas daqui são
        consistentes entre si — não há fator de escala aplicado depois.
        """
        prof = self._seq_profile(fault_bus, kind, Zf)
        if prof is None or not (self._modo(modo) == 'completo' and self._tem_fc()):
            return prof
        self._exigir_validacao_completo()
        Z1, Z2, Z0 = self.zth(fault_bus)
        zf = complex(Zf)
        if kind == '3F':
            zeq, r2, r0 = zf, 0, 0
        elif kind == '2F':
            zeq, r2, r0 = Z2 + 2 * zf, -1, 0
        elif kind == '1FT':
            zeq, r2, r0 = Z2 + Z0 + 3 * zf, 1, 1
        else:
            z0f = Z0 + 3 * zf
            zeq = Z2 * z0f / (Z2 + z0f)
            r2, r0 = -z0f / (Z2 + z0f), -Z2 / (Z2 + z0f)
        Vst, Ia1, _ = self._estado_fc_robusto(fault_bus, Zf=zeq)
        Ia2, Ia0 = r2 * Ia1, r0 * Ia1
        V2 = prof['V2'] * (Ia2 / prof['Ia2']) if abs(prof['Ia2']) > 1e-12 else prof['V2'] * 0
        V0 = (prof['V0'] * (Ia0 / prof['Ia0']) if (prof['V0'] is not None
                                                  and abs(prof['Ia0']) > 1e-12)
              else (prof['V0'] * 0 if prof['V0'] is not None else None))
        out = dict(prof)
        out.update(V1=Vst, V2=V2, V0=V0, Ia1=Ia1, Ia2=Ia2, Ia0=Ia0)
        return out

    def _i0_linha(self, V0, br, de):
        """Corrente de sequência zero numa linha, saindo do terminal `de`.

        Linha segmentada por acoplamento mútuo: usa um segmento livre de mútua, onde a
        corrente é a queda de tensão sobre a impedância do próprio segmento; se todos os
        segmentos estão acoplados, aplica a matriz primitiva do grupo. Sem isso a corrente
        seria a queda total sobre a impedância total, o que ignora a tensão induzida.
        """
        k = self.lt_key(br['bf'], br['bt'], br['nc'])
        cortes = getattr(self, 'cortes', {})
        z0 = zfin(br.get('R0'), br.get('X0'))
        para = br['bt'] if de == br['bf'] else br['bf']
        gm = getattr(self, '_gmut', {})

        def pelo_grupo(n1, n2, ks, sinal):
            grupo, idx, Yp, nos = gm[ks]
            dv = np.array([V0[self.I0P[nos[g][0]]] - V0[self.I0P[nos[g][1]]] for g in grupo])
            i_can = (Yp @ dv)[idx[ks]]                 # sentido canônico (menor -> maior)
            return sinal * (i_can if (n1, n2) == ks[:2] else -i_can)

        # linha acoplada em TODO o comprimento: um único segmento, sem nós auxiliares
        ks_inteira = ((de, para) if de < para else (para, de)) + (k,)
        if ks_inteira in gm:
            return pelo_grupo(de, para, ks_inteira, 1)
        if k not in cortes or k not in self.direc:
            if z0 is None or de not in self.I0P or para not in self.I0P:
                return 0j
            return (V0[self.I0P[de]] - V0[self.I0P[para]]) / z0
        a0, b0 = self.direc[k]
        ps = sorted(cortes[k])
        sinal = 1 if de == a0 else -1                 # corrente no sentido a0 -> b0
        segs = []
        for s in range(len(ps) - 1):
            n1 = self.aux.get((a0, b0, k[2], ps[s])); n2 = self.aux.get((a0, b0, k[2], ps[s + 1]))
            zs = self._Zseg.get((n1, n2, k, ps[s], ps[s + 1])) or \
                 self._Zseg.get((n2, n1, k, ps[s], ps[s + 1]))
            if n1 is None or n2 is None or zs is None:
                continue
            segs.append((n1, n2, zs))
        for n1, n2, zs in segs:
            ks = ((n1, n2) if n1 < n2 else (n2, n1)) + (k,)
            if ks not in gm:
                return sinal * (V0[self.I0P[n1]] - V0[self.I0P[n2]]) / zs
        if not segs:
            return 0j
        n1, n2, _ = segs[0]
        ks = ((n1, n2) if n1 < n2 else (n2, n1)) + (k,)
        return pelo_grupo(n1, n2, ks, sinal)

    def _find_branch(self, bf, bt, nc):
        for b in self.M.branches:
            if b['nc']==nc and {b['bf'],b['bt']}=={bf,bt}: return b
        return None

    def branch_current(self, fault_bus, bf, bt, nc, kind='3F', Zf=0.0, modo=None):
        """Correntes num ramo para uma falta em `fault_bus`, em kA primários.

        Sentido positivo: saindo de `bf` em direção a `bt`, como pedido na chamada.
        Tudo vem de UM estado de solução (`_perfil`): no modo completo, o estado convergido
        com as fontes de conversor; nenhum fator de escala é aplicado depois.

        Linha: três sequências, com a sequência zero recuperada considerando o acoplamento
        mútuo. Transformador: positiva e negativa pelo ramo e sequência zero pela conexão
        dos enrolamentos (`corrente_seq0_ramo`); banco com N unidades em paralelo devolve a
        corrente AGREGADA e, à parte, a por unidade. Capacitor série também é aceito.

        Devolve módulos (Ia, Ib, Ic, Imax, I1, I2, I0, I3I0), fasores complexos (`fasores`)
        e o `modo`.
        """
        prof = self._perfil(fault_bus, kind, Zf, modo)
        if prof is None:
            return None
        br = self._find_branch(bf, bt, nc)
        if br is None:
            for c in getattr(self.M, 'caps', []):
                if str(c.get('nc', '1')) == str(nc) and {c['bf'], c['bt']} == {bf, bt}:
                    br = dict(c, tipo='S', R1=0.0, R0=0.0)
                    break
        if br is None:
            return None
        if (br['bf'], br['bt'], br['nc']) in self.dropB or \
                (br['bt'], br['bf'], br['nc']) in self.dropB:
            return None
        de, para = (bf, bt)
        kvb = self.M.bus_kv.get(de, 0) or self.M.bus_kv.get(para, 0)
        if not kvb:
            return None
        Ib = SB / (np.sqrt(3) * kvb)
        z1 = zfin(br.get('R1'), br.get('X1'))
        nun = (br.get('nunop', 1) or 1) if br['tipo'] == 'T' else 1

        def dI(V, IDX, z):
            if V is None or z is None or abs(z) < 1e-12:
                return 0j
            if de not in IDX or para not in IDX:
                return 0j
            return (V[IDX[de]] - V[IDX[para]]) / z
        I1 = dI(prof['V1'], self.IDXP, z1) * nun
        I2 = dI(prof['V2'], self.IDXP, z1) * nun
        if prof['V0'] is None:
            I0 = 0j
        elif br['tipo'] == 'L':
            I0 = self._i0_linha(prof['V0'], br, de)
        elif br['tipo'] == 'T':
            I0 = -self.corrente_seq0_ramo(prof['V0'], br, de)
        else:
            I0 = dI(prof['V0'], self.I0P, zfin(br.get('R0'), br.get('X0')))
        a = np.exp(2j * np.pi / 3)
        Ia = I0 + I1 + I2; Ibf = I0 + a * a * I1 + a * I2; Ic = I0 + a * I1 + a * a * I2
        m = lambda x: abs(x) * Ib
        out = dict(Ia=m(Ia), Ib=m(Ibf), Ic=m(Ic), Imax=max(m(Ia), m(Ibf), m(Ic)),
                   I1=m(I1), I2=m(I2), I0=m(I0), I3I0=3 * m(I0), kV=kvb,
                   fasores=dict(Ia=Ia * Ib, Ib=Ibf * Ib, Ic=Ic * Ib,
                                I1=I1 * Ib, I2=I2 * Ib, I0=I0 * Ib),
                   sentido=f'de {de} para {para}', modo=self._modo(modo),
                   seqonly=False)
        if nun > 1:
            out['unidades'] = nun
            out['Imax_por_unidade'] = out['Imax'] / nun
        return out

    def bus_voltage(self, fault_bus, obs_bus, kind='3F', Zf=0.0, modo=None):
        """Tensões de fase e fase-fase (pu) numa barra observada durante uma falta.

        Mesmo estado de solução de `branch_current` (`_perfil`): no modo completo, a
        sequência positiva vem do estado convergido com as fontes de conversor.
        Devolve módulos, fasores e Vff_min — a menor tensão fase-fase, em pu da nominal.
        """
        prof = self._perfil(fault_bus, kind, Zf, modo)
        if prof is None or obs_bus not in self.IDXP:
            return None
        io = self.IDXP[obs_bus]
        V1 = prof['V1'][io]; V2 = prof['V2'][io]
        V0 = prof['V0'][self.I0P[obs_bus]] if (prof['V0'] is not None
                                                 and obs_bus in self.I0P) else 0j
        a = np.exp(2j * np.pi / 3)
        Va = V0 + V1 + V2; Vb = V0 + a * a * V1 + a * V2; Vc = V0 + a * V1 + a * a * V2
        vff = min(abs(Va - Vb), abs(Vb - Vc), abs(Vc - Va)) / np.sqrt(3)
        return dict(Va=abs(Va), Vb=abs(Vb), Vc=abs(Vc), V1=abs(V1), V2=abs(V2), V0=abs(V0),
                    Va_c=Va, Vb_c=Vb, Vc_c=Vc, V1_c=V1, V0_c=V0, Vff_min=vff,
                    modo=self._modo(modo))

    def _solver_terminal_aberto(self, br, closed):
        """Solver derivado com a extremidade de `br` oposta a `closed` aberta.

        A linha continua ligada ao terminal fechado e passa a terminar num nó fictício na
        ponta aberta, levando consigo o reator de linha daquela ponta — é como o ANAFAS
        representa o terminal aberto. Guardado em cache nesta instância.
        """
        chave = ('aberto', br['bf'], br['bt'], br['nc'], closed)
        cache = self.__dict__.setdefault('_cache_derivados', {})
        if chave in cache:
            return cache[chave]
        Mm = self._clone_model()
        X = max(Mm.bus_kv) + 1
        aberta = br['bt'] if closed == br['bf'] else br['bf']
        Mm.bus_kv[X] = self.M.bus_kv.get(aberta, 0) or self.M.bus_kv.get(closed, 0)
        Mm.bus_name[X] = 'FIC.ABERTO'
        nova = dict(br)
        if aberta == br['bt']:
            nova['bt'] = X
        else:
            nova['bf'] = X
        Mm.branches = [x for x in Mm.branches if x is not br] + [nova]
        shl = []
        for r in Mm.shl:
            if {r['bf'], r['bt']} == {br['bf'], br['bt']} and str(r.get('nc', '1')) == str(br['nc']):
                r = dict(r)
                r['bf'] = X if r['bf'] == aberta else r['bf']
                r['bt'] = X if r['bt'] == aberta else r['bt']
            shl.append(r)
        Mm.shl = shl
        manter = [(nova['bf'], nova['bt'], nova['nc'])]
        S2 = self._derivado(Mm, manter_extra=manter)
        return self._cache_guardar(chave, (S2, X, nova))

    def line_end_open(self, bf, bt, nc, closed, kind='3F', p=1.0, Zf=0.0, modo=None):
        """Falta na linha (bf,bt,nc) com o terminal remoto ABERTO. kA primários.

        Topologia real: a ponta oposta a `closed` é aberta e a linha fica pendurada no
        terminal fechado, com os seus reatores. `p` é a posição da falta a partir de
        `closed`: p → 0 junto ao disjuntor, p = 1 na ponta aberta. Devolve a corrente que
        atravessa o TC do terminal fechado. Segue o modo da instância; o acoplamento mútuo
        da linha aberta não é mantido na topologia derivada.
        """
        br = self._find_branch(bf, bt, nc)
        if br is None or br['tipo'] != 'L':
            return None
        if modo is not None and modo != self.modo:
            S = Solver(self.M, drop_branches=list(self.dropB), modo=modo,
                       charging=self.charging, manter_reatores=list(self.manterShl),
                       drop_reatores_barra=list(self.dropH),
                       bypass_capacitores=list(self.bypassC))
            S.validado_completo = getattr(self, 'validado_completo', False)
            S._selo_completo = getattr(self, '_selo_completo', None)
            return S.line_end_open(bf, bt, nc, closed, kind, p, Zf)
        p = min(max(float(p), 0.0), 1.0)
        S2, X, nova = self._solver_terminal_aberto(br, closed)
        if p >= 1.0 - 1e-6:
            r = S2.branch_current(X, closed, X, nova['nc'], kind, Zf)
            return r['Imax'] if r else None
        r = S2.fault_on_branch(closed, X, nova['nc'], p, kind, Zf)
        return r.get('I_term_%d' % closed) if r else None

    def varredura_line_end_open(self, bf, bt, nc, closed, kinds=('3F', '1FT', '2F', '2FT'),
                                pontos=(0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)):
        """Varre a posição da falta com o terminal remoto aberto.

        Devolve {kind: [(p, I_kA), ...]}. É a condição que dimensiona o alcance das zonas
        de distância: a corrente cai monotonicamente com a distância da falta, e o extremo
        de sensibilidade está na ponta oposta.
        """
        saida = {}
        for kind in kinds:
            serie = [(p, I) for p in pontos
                     if (I := self.line_end_open(bf, bt, nc, closed, kind, p=p))]
            if serie:
                saida[kind] = serie
        return saida

    def fault_on_branch(self, bf, bt, nc, p, kind='3F', Zf=0.0, modo=None):
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
        chave=('ramo',sbf,sbt,br['nc'],round(p,9))
        cache=self.__dict__.setdefault('_cache_derivados',{})
        S2=cache[chave] if chave in cache else self._cache_guardar(chave, self._derivado(Mm))
        out={'kV':kvL,'p':p,'mutua_aprox':has_mut}
        out['If']=S2.fault(F,kind,Zf=Zf)
        # corrente que cada terminal fornece à falta: sentido do terminal para o ponto F
        ci=S2.branch_current(F, sbf,F,br['nc'],kind,Zf)
        cj=S2.branch_current(F, sbt,F,br['nc'],kind,Zf)
        out['I_term_%d'%sbf]=ci['Imax'] if ci else None
        out['I_term_%d'%sbt]=cj['Imax'] if cj else None
        out['3I0_term_%d'%sbf]=ci['I3I0'] if ci else None
        out['3I0_term_%d'%sbt]=cj['I3I0'] if cj else None
        return out

    def fault_on_shunt(self, bus, p, kind='1FT', Zf=0.0, modo=None):
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
        S2=self._derivado(Mm, modo=modo)
        return {'kV':kvb,'p':p,'If':S2.fault(F,kind,Zf=Zf),
                'I_terminal':(lambda c: c['Imax'] if c else None)(
                    S2.branch_current(F,bus,F,'RT',kind,Zf))}

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

    def _modo(self, modo=None):
        """Modo efetivo desta chamada. `None` usa o da instância, que é o normal.

        Passar `modo` explicitamente é exceção — serve para comparar os dois num mesmo
        estudo, e nesse caso a diferença tem de ser declarada no relatório.
        """
        m = modo or getattr(self, 'modo', 'completo')
        if m not in ('sincronas', 'completo'):
            raise ValueError(f"modo deve ser 'sincronas' ou 'completo', recebido {m!r}")
        return m

    def _tem_fc(self):
        """O caso tem geradores de conversor pleno?

        Sem eles os dois modos coincidem: não há injeção a validar, e exigir
        `validar_completo` seria atrito sem propósito — inclusive nos casos sintéticos
        de teste, que não têm DEOL.
        """
        return bool(self._fc_sources())

    def _exigir_validacao_completo(self):
        """Bloqueia o modo completo enquanto o modelo de injeção não for validado.

        O modo completo só é liberado depois de `validar_completo()` conferir as
        correntes contra a seção de níveis do caso EM USO. Emitir número não validado
        num estudo de proteção é pior do que não emitir.
        """
        if not getattr(self, 'validado_completo', False):
            raise RuntimeError(
                "modo 'completo' não liberado NESTE CASO. O MODELO de injeção já é "
                "validado — 828 barras em duas bases, 100% dentro de 1% — mas o parser lê "
                "o FORMATO, não um caso específico, e um registro que não apareça no caso "
                "de referência é ignorado em silêncio.\n"
                "  Com o relatório do ANAFAS em mãos:\n"
                "      S.validar_completo(niveis_kA)        # seção de NÍVEIS do caso\n"
                "  Sem o relatório, assumindo o risco de leitura do caso:\n"
                "      S.liberar_completo_sem_gabarito()    # marca o estudo como não conferido\n"
                "  Ou use o Thévenin puro, que não depende disso:\n"
                "      S.fault(bus, kind, modo='sincronas')")

    def liberar_completo_sem_gabarito(self, motivo=''):
        """Libera o modo completo sem conferir contra o relatório deste caso.

        Use quando o relatório do ANAFAS não está disponível e o modo síncronas não serve.

        A distinção importa: o MODELO de injeção é validado — 828 barras em duas bases,
        100% dentro de 1% — e isso não muda de caso para caso. O que fica sem conferir é a
        LEITURA deste caso: o parser lê o FORMATO, não um caso específico, e um tipo de
        registro que não apareça no caso de referência é ignorado em silêncio. O número
        sai, e pode sair errado sem aviso.

        O selo registra a ausência de gabarito, e é isso que deve constar no estudo:
        `S.selo_completo()['conferido_no_caso']` volta False.
        """
        self.validado_completo = True
        self._selo_completo = dict(conferido_no_caso=False, liberado=True, forcado=True,
                                   motivo=motivo or 'relatório do caso não disponível')
        return self._selo_completo

    def selo_completo(self):
        """Como o modo completo foi liberado neste caso. Declare no estudo."""
        s = dict(getattr(self, '_selo_completo', None) or {})
        s.setdefault('conferido_no_caso', False)
        s.setdefault('liberado', bool(getattr(self, 'validado_completo', False)))
        return s

    def validar_completo(self, niveis_kA, kind='3F', limite=1.0, forcar=False,
                         ignorar=()):
        """Confere `fault_fc` contra a seção de níveis do ANAFAS e libera o modo completo.

        `niveis_kA`: {barra: corrente_kA} lida da seção de níveis do MESMO caso.
        `ignorar`: barras fora do critério, para divergência conhecida e documentada;
            continuam no selo, marcadas.

        Só libera se o erro máximo ficar dentro de `limite` (%). Barras que NÃO CONVERGEM
        ficam fora do veredito: não produzem número, e portanto não podem aprovar nem
        reprovar o caso — mas entram no selo, em `nao_convergiram`, para que o estudo saiba
        onde o modo completo não responde.

        `forcar=True` equivale a `liberar_completo_sem_gabarito()`.
        """
        if forcar:
            return self.liberar_completo_sem_gabarito('forcar=True')
        ignorar = set(ignorar)
        erros, excluidas, nao_convergiram = [], [], []
        for b, ref in (niveis_kA or {}).items():
            if b not in self.IDXP or not ref or ref <= 0:
                continue
            try:
                calc = self.fault_fc(b, kind)
            except RuntimeError:
                nao_convergiram.append(b)
                continue
            if not calc:
                continue
            e = (calc - ref) / ref * 100
            (excluidas if b in ignorar else erros).append((b, e))
        if not erros:
            raise ValueError(
                "nenhuma barra comparável entre o caso e os níveis fornecidos"
                + (f" ({len(nao_convergiram)} não convergiram)" if nao_convergiram else ""))
        v = np.array([e for _, e in erros])
        pior = max(erros, key=lambda t: abs(t[1]))
        selo = dict(n=len(v), erro_max=float(np.max(np.abs(v))),
                    mediana=float(np.median(np.abs(v))),
                    pct_dentro=float((np.abs(v) < limite).mean() * 100),
                    pior_barra=pior[0], pior_erro=float(pior[1]), limite=limite,
                    ignoradas=[(b, float(e)) for b, e in excluidas],
                    nao_convergiram=sorted(nao_convergiram),
                    conferido_no_caso=True)
        self.validado_completo = selo['erro_max'] < limite
        selo['liberado'] = self.validado_completo
        self._selo_completo = selo
        if self.validado_completo:
            # A conferência é da LEITURA do caso: fica registrada no próprio modelo, e todo
            # cálculo derivado dele (contingência, recomposição, cenário) a herda.
            self.M._leitura_conferida = dict(selo)
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


    def corrente_seq0_ramo(self, V0, br, bus):
        """Corrente de sequência zero que o ramo `br` injeta na barra `bus`, em pu.

        Necessária para o 3I0 dos bays de TRANSFORMADOR, que `branch_current` não cobre:
        na rede de sequência zero um trafo não é um ramo série genérico. A topologia
        depende da conexão:

          YN-YN  ramo série: I0 = (V0_i − V0_j) / (z0 + 3Zn_i + 3Zn_j)
          D-YN   caminho para a terra no lado YN: I0 = V0_YN / (z0 + 3Zn)
          D-D    não há caminho de sequência zero: I0 = 0

        `V0` é o vetor de tensões de sequência zero do estado de falta.
        """
        if br['tipo'] != 'T':
            z0 = zfin(br.get('R0'), br.get('X0'))
            if z0 is None or bus not in self.I0P:
                return 0j
            o = br['bt'] if br['bf'] == bus else br['bf']
            if o not in self.I0P:
                return 0j
            return (V0[self.I0P[o]] - V0[self.I0P[bus]]) / z0
        z0 = zfin(br.get('R0'), br.get('X0'))
        if z0 is None:
            return 0j
        cd = self.conn_type(br.get('cd', 'YN'))
        cp = self.conn_type(br.get('cp', 'YN'))
        lado_de = (bus == br['bf'])
        znd = zn3(br.get('rnde'), br.get('xnde'))
        znp = zn3(br.get('rnpa'), br.get('xnpa'))
        nun = br.get('nunop', 1) or 1
        if bus not in self.I0P:
            return 0j
        vb = V0[self.I0P[bus]]
        if cd == 'D' and cp == 'D':
            return 0j
        if cd == 'YN' and cp == 'YN':
            if znd is None or znp is None:
                return 0j
            o = br['bt'] if lado_de else br['bf']
            if o not in self.I0P:
                return 0j
            return nun * (V0[self.I0P[o]] - vb) / (z0 + znd + znp)
        # D-YN: caminho para a terra no lado aterrado; do outro lado não circula
        aterrado_de = (cd == 'YN')
        if lado_de != aterrado_de:
            return 0j
        zn = znd if aterrado_de else znp
        if zn is None:
            return 0j
        return -nun * vb / (z0 + zn)


def branches_at(model, bus, tipos=('L','T')):
    """Ramos incidentes na barra (lista de (bf,bt,nc)) — util para montar contingencias."""
    return [(br['bf'],br['bt'],br['nc']) for br in model.branches
            if bus in (br['bf'],br['bt']) and br['tipo'] in tipos]


# ===================== motor de protecao =====================

def recomposicao_87b(model, bus, kinds=('3F','1FT'), modo='completo'):
    """ICC_MIN de recomposicao para 87B: falta na barra energizada por UM elemento de cada vez.
    Para cada ramo (L ou perna 138 de banco de trafo) incidente na barra, isola a barra a esse
    unico elemento (dropa todos os demais incidentes) e calcula a falta. Retorna
    (tabela: [(rotulo,(bf,bt,nc),{kind:I_kA})], icc_min:{kind:I_kA}). Elementos que nao
    energizam a barra (Icc~0) aparecem na tabela e devem ser excluidos do ICC_MIN pelo analista."""
    inc=branches_at(model, bus)
    tab=[]; mins={k:float('inf') for k in kinds}
    for keep in inc:
        drop=[b for b in inc if b!=keep]
        # Energização por um só elemento: o reator de barra também é um vão e sai. É a
        # hipótese de menor corrente, e a que reproduz o ANAFAS na recomposição.
        S=Solver(model, drop_branches=drop, modo=modo, drop_reatores_barra=[bus])
        S.factor(avisar=False)
        if modo=='completo' and getattr(model, '_leitura_conferida', None):
            S.validado_completo=True
            S._selo_completo=dict(model._leitura_conferida, conferido_no_caso=True)
        elif modo=='completo':
            # A recomposição monta dezenas de cenários; cada um é um Solver novo, e o
            # bloqueio do modo completo é por instância. Propaga-se a liberação, porque a
            # decisão de usar o modo completo foi tomada por quem chamou.
            S.liberar_completo_sem_gabarito('cenário interno de recomposição')
        vals={}
        for k in kinds:
            I=S.fault(bus, kind=k, modo=modo)
            vals[k]=I
            if I is not None and I>1e-3: mins[k]=min(mins[k], I)
        br=next(b for b in model.branches if (b['bf'],b['bt'],b['nc'])==keep)
        o=br['bt'] if br['bf']==bus else br['bf']
        rot=f"{br['tipo']} p/ {model.bus_name.get(o,'')[:12]}"
        tab.append((rot, keep, vals))
    return tab, mins



def envelope_contribuicoes(model, barra, tipos=('3F', '1FT', '2F', '2FT'),
                           vizinhanca=1, p_close_in=0.005, solver=None, modo=None):
    """Envelope de correntes por bay, para ajuste de proteção de barra.

    Executa o conjunto de casos que um estudo de barra pede, sem que seja preciso
    enumerá-los a cada vez:

      * os quatro tipos de defeito: monofásico, trifásico, bifásico e bifásico-terra;
      * sistema completo e contingência simples (N-1) até `vizinhanca` barras;
      * as contingências sendo RETIRADA de equipamento e FALTA NA LINHA COM O TERMINAL
        OPOSTO ABERTO, que é a condição de abertura sequencial de disjuntor;
      * defeito na própria barra e defeito close-in dentro de cada equipamento.

    Devolve, POR BAY, a maior e a menor corrente do loop fase-fase e do loop de terra
    (3I0), com o cenário em que cada extremo ocorreu — que é o que alimenta a corrente
    mínima de operação e a de alarme.

    Estrutura devolvida:

        {bay: {'fase': {'max': (kA, cenario), 'min': (kA, cenario)},
               'terra': {'max': (kA, cenario), 'min': (kA, cenario)},
               'casos': [(cenario, tipo, I_fase_kA, I_3I0_kA), ...]}}

    O bay é identificado pela tupla (tipo, bf, bt, nc) do elemento incidente. O mínimo
    considera apenas cenários em que o bay está em serviço e a corrente é não nula: um
    bay retirado não define mínimo de sensibilidade.
    """
    S0 = solver or Solver(model, modo=modo or 'completo')
    if not hasattr(S0, 'luP'):
        S0.factor(avisar=False)
    incid = [(br['tipo'], br['bf'], br['bt'], br['nc'])
             for br in model.branches if barra in (br['bf'], br['bt'])
             and (br['bf'], br['bt'], br['nc']) not in S0.dropB]
    if not incid:
        return {}

    # --- cenários: (rótulo, drop_branches, barra_em_falta, ramo_close_in) -------------
    cen = [('sistema completo', [], barra, None)]
    # close-in dentro de cada equipamento incidente
    for e in incid:
        cen.append((f'close-in em {e[0]} {e[1]}-{e[2]}/{e[3]}', [], barra, e))
    # N-1: retirada de cada elemento incidente e dos elementos das barras vizinhas
    alvos = set(incid)
    if vizinhanca >= 1:
        viz = {e[2] if e[1] == barra else e[1] for e in incid}
        for br in model.branches:
            if (br['bf'] in viz or br['bt'] in viz):
                alvos.add((br['tipo'], br['bf'], br['bt'], br['nc']))
    for e in sorted(alvos):
        if e in incid and len(incid) == 1:
            continue                      # não deixar a barra sem alimentação
        cen.append((f'N-1 sem {e[0]} {e[1]}-{e[2]}/{e[3]}', [(e[1], e[2], e[3])], barra, None))
    # falta na linha com o terminal oposto aberto
    for e in incid:
        if e[0] == 'L':
            # a topologia real (linha pendurada) é montada a partir da rede de origem
            cen.append((f'terminal oposto aberto em {e[1]}-{e[2]}/{e[3]}',
                        [], barra, ('LEO',) + e[1:]))

    saida = {e: {'casos': []} for e in incid}
    cache = {}
    for rot, drop, fb, extra in cen:
        # retirada integral do equipamento (transformador leva todas as pernas)
        drop_eq = []
        for r in drop:
            drop_eq += _equipamento(model, r, barra)
        chave = tuple(sorted(set(drop_eq)))
        if chave not in cache:
            try:
                cache[chave] = S0 if not drop_eq else _solver(
                    model, list(chave), getattr(S0, 'modo', 'completo'))
            except Exception as ex:
                cache[chave] = None
                for e in incid:
                    saida[e].setdefault('falhas', []).append(f'{rot}: {type(ex).__name__}')
        S = cache[chave]
        if S is None:
            continue
        for tipo in tipos:
            if extra and extra[0] == 'LEO':
                # terminal oposto aberto: topologia real, só o vão da própria linha
                e = next((x for x in incid if (x[1], x[2], x[3]) == tuple(extra[1:])), None)
                br = S._find_branch(*extra[1:]) if e else None
                if br is None:
                    continue
                try:
                    S2, X, nova = S._solver_terminal_aberto(br, barra)
                    pontas = [('junto ao disjuntor',
                               S2.fault_on_branch(barra, X, nova['nc'], 1e-3, tipo)),
                              ('na ponta aberta',
                               S2.branch_current(X, barra, X, nova['nc'], tipo))]
                except Exception as ex:
                    saida[e].setdefault('falhas', []).append(f'{rot}, {tipo}: {type(ex).__name__}')
                    continue
                for onde, r in pontas:
                    if not r:
                        continue
                    if 'Imax' in r:
                        ifs, i3 = r['Imax'], r['I3I0']
                    else:
                        ifs, i3 = r.get('I_term_%d' % barra), r.get('3I0_term_%d' % barra)
                    if ifs:
                        saida[e]['casos'].append((f'{rot}, falta {onde} · {tipo}', tipo,
                                                  ifs, i3 or 0.0))
                continue
            if extra:
                # close-in dentro do equipamento: falta logo após o TC do vão
                e = extra
                try:
                    r = S.fault_on_branch(barra, e[2] if e[1] == barra else e[1], e[3], 1e-3, tipo)
                except Exception as ex:
                    saida[e].setdefault('falhas', []).append(f'{rot}, {tipo}: {type(ex).__name__}')
                    continue
                if r and r.get('I_term_%d' % barra):
                    saida[e]['casos'].append((f'{rot} · {tipo}', tipo, r['I_term_%d' % barra],
                                              r.get('3I0_term_%d' % barra) or 0.0))
                continue
            for e in incid:
                if set(_equipamento(model, (e[1], e[2], e[3]), barra)) & set(chave):
                    continue                                  # vão fora de serviço
                try:
                    r = S.branch_current(fb, e[1], e[2], e[3], tipo)
                except Exception as ex:
                    saida[e].setdefault('falhas', []).append(f'{rot}, {tipo}: {type(ex).__name__}')
                    continue
                if r:
                    saida[e]['casos'].append((f'{rot} · {tipo}', tipo, r['Imax'], r['I3I0']))

    for e, d in saida.items():
        for campo, idx in (('fase', 2), ('terra', 3)):
            vals = [(c[idx], c[0]) for c in d['casos'] if c[idx] > 1e-9]
            if not vals:
                d[campo] = {'max': (0.0, '—'), 'min': (0.0, '—')}
                continue
            d[campo] = {'max': max(vals), 'min': min(vals)}
    return saida


def tabela_envelope(env, model=None, largura=46):
    """Formata o resultado de `envelope_contribuicoes` como texto pronto para relatório."""
    linhas = []
    cab = f"{'BAY':<26} {'FASE máx':>10} {'FASE mín':>10} {'3I0 máx':>10} {'3I0 mín':>10}"
    linhas.append(cab)
    linhas.append('-' * len(cab))
    for e, d in env.items():
        nome = f"{e[0]} {e[1]}-{e[2]}/{e[3]}"
        linhas.append(f"{nome:<26} {d['fase']['max'][0]:10.3f} {d['fase']['min'][0]:10.3f} "
                      f"{d['terra']['max'][0]:10.3f} {d['terra']['min'][0]:10.3f}")
    linhas.append('')
    linhas.append('Cenário de cada extremo (kA primários):')
    for e, d in env.items():
        nome = f"{e[0]} {e[1]}-{e[2]}/{e[3]}"
        linhas.append(f"  {nome}")
        for campo, rot in (('fase', 'fase-fase'), ('terra', '3I0')):
            for extremo in ('max', 'min'):
                val, cen = d[campo][extremo]
                linhas.append(f"     {rot:<10} {extremo:>3}: {val:9.3f}   {cen[:largura]}")
    return '\n'.join(linhas)



# ====================================================================== #
#  Funções de alto nível                                                 #
#                                                                        #
#  Encapsulam os estudos recorrentes para que o pedido possa ser curto:   #
#  o protocolo — quais tipos de defeito, quais contingências, o que       #
#  declarar, o que não estimar — fica AQUI, e não no prompt do usuário.   #
# ====================================================================== #

_KINDS = ('3F', '1FT', '2F', '2FT')


def _premissas_curto(S):
    """Premissas presentes em todo cálculo de curto-circuito desta instância."""
    sel = S.selo_completo() if hasattr(S, 'selo_completo') else {}
    p = ['tensão pré-falta de 1,0 pu em todas as barras, sem carregamento prévio',
         'correntes em kA primários (A primários nos ajustes)',
         'sequência negativa igual à positiva: o .ANA não traz reatância de sequência '
         'negativa das máquinas; grandezas de sequência negativa (46, 67Q) têm essa '
         'limitação e não são conferidas contra o ANAFAS']
    if S.modo == 'completo' and S._tem_fc():
        p.append('modo completo: inclui a contribuição dos geradores conectados por '
                 'conversor, conforme a curva do Submódulo 2.10')
        p.append('leitura do caso conferida contra o relatório do ANAFAS'
                 if sel.get('conferido_no_caso') else
                 'leitura do caso NÃO conferida contra o relatório do ANAFAS')
    else:
        p.append('modo síncronas: Thévenin sem a contribuição dos geradores de conversor')
    return p


def _solver(model, drop=None, modo='completo', manter_reatores=None,
            drop_reatores_barra=None, bypass_capacitores=None):
    # avisar=False: numa chamada de alto nível o aviso apareceria uma vez por cenário
    # interno — o relatório declara o modo no retorno, que é onde interessa.
    S = Solver(model, drop_branches=list(drop) if drop else None, modo=modo,
               manter_reatores=manter_reatores, drop_reatores_barra=drop_reatores_barra,
               bypass_capacitores=bypass_capacitores)
    S.factor(avisar=False)
    conf = getattr(model, '_leitura_conferida', None)
    if modo == 'completo' and conf:
        S.validado_completo = True
        S._selo_completo = dict(conf, conferido_no_caso=True)
        return S
    if modo == 'completo':
        S.liberar_completo_sem_gabarito('chamada de alto nível sem gabarito do caso')
    return S


def impacto_entrada(model, ramos, limiar=10.0, kinds=_KINDS, kv_min=69.0,
                    modo='completo', i_min_kA=0.1):
    """Impacto da entrada em operação de um equipamento na evolução de curto-circuito.

    `ramos` são os ramos do equipamento NOVO, como [(bf, bt, nc), ...]. Se o equipamento
    já está representado na base — o caso usual em horizonte de planejamento — o cenário
    "antes" é o contrafactual: os ramos são removidos. Um banco de três enrolamentos exige
    TODAS as pernas do nó-estrela na lista, senão o equipamento continua parcialmente
    conectado e o resultado não significa nada.

    Varre as barras de `kv_min` para cima nos quatro tipos de defeito e devolve as que
    variam `limiar` % ou mais, com o tipo que governou. Barras abaixo de `i_min_kA` são
    ignoradas: ali o percentual não tem significado físico.

    Devolve dict com 'barras' (lista ordenada pela maior variação), 'limiar', 'modo' e
    'n_avaliadas'. Cada barra traz: num, nome, kv, antes, depois, variacao_pct, kind.

    O gatilho de 10% é o usual para exigir revisão dos estudos de proteção existentes.
    """
    ramos = [(int(a), int(b), str(c)) for a, b, c in ramos]
    S_com = _solver(model, None, modo)
    S_sem = _solver(model, ramos, modo)
    alvo = [b for b, kv in model.bus_kv.items() if kv and kv >= kv_min]
    saida = []
    for b in alvo:
        pior = None
        for kind in kinds:
            try:
                a = S_sem.fault(b, kind, modo=modo)
                c = S_com.fault(b, kind, modo=modo)
            except Exception:
                continue
            if not a or not c or a < i_min_kA:
                continue
            d = (c - a) / a * 100.0
            if pior is None or abs(d) > abs(pior[0]):
                pior = (d, kind, a, c)
        if pior and abs(pior[0]) >= limiar:
            saida.append(dict(num=b, nome=model.bus_name.get(b, ''), kv=model.bus_kv[b],
                              antes=pior[2], depois=pior[3], variacao_pct=pior[0],
                              kind=pior[1]))
    saida.sort(key=lambda d: -abs(d['variacao_pct']))
    prem = _premissas_curto(S_com) + [
        'cenário "antes" obtido retirando o equipamento do caso (contrafactual)',
        f"tipos de defeito avaliados: {', '.join(kinds)}; reportado o que governou",
        f"barras de {kv_min:g} kV para cima; ignoradas as com corrente abaixo de "
        f"{i_min_kA:g} kA, onde o percentual não tem significado",
        f"gatilho de revisão: variação de {limiar:g}%",
        'rede completa do ANAFAS, sem despacho de cenário']
    return dict(barras=saida, limiar=limiar, modo=modo, n_avaliadas=len(alvo),
                ramos=ramos, premissas=prem)


def relatorio_curto(model, barra, kinds=_KINDS, modo='completo', solver=None):
    """Relatório de curto-circuito de uma barra: correntes, Thévenin e contribuições.

    Devolve dict com 'correntes' {kind: kA}, 'zth' (Z1, Z2, Z0 em pu), 'contribuicoes'
    {(tipo,bf,bt,nc): kA} e 'modo'. É o bloco básico sobre o qual os relatórios de
    proteção são montados.
    """
    S = solver or _solver(model, None, modo)
    out = dict(barra=barra, nome=model.bus_name.get(barra, ''),
               kv=model.bus_kv.get(barra), modo=modo, correntes={}, avisos=[])
    for kind in kinds:
        try:
            out['correntes'][kind] = S.fault(barra, kind, modo=modo)
        except Exception as e:
            out['avisos'].append(f"{kind}: {type(e).__name__} — {str(e)[:80]}")
    z = S.zth(barra)
    out['zth'] = dict(Z1=z[0], Z2=z[1], Z0=z[2]) if z and z[0] is not None else None
    try:
        out['contribuicoes'] = S.contribution(barra, '3F', modo=modo)
    except Exception:
        out['contribuicoes'] = {}
    out['premissas'] = _premissas_curto(S) + ['rede completa do ANAFAS, sem despacho de cenário']
    return out


def _ramos_incidentes(model, bus):
    """Ramos incidentes na barra como [(bf, bt, nc), ...], independente do formato que
    `branches_at` devolva."""
    out = []
    for x in branches_at(model, bus):
        if isinstance(x, dict):
            out.append((x['bf'], x['bt'], str(x['nc'])))
        else:
            t = tuple(x)
            # aceita (tipo,bf,bt,nc) ou (bf,bt,nc)
            if len(t) >= 4 and isinstance(t[0], str):
                out.append((t[1], t[2], str(t[3])))
            elif len(t) >= 3:
                out.append((t[0], t[1], str(t[2])))
    return out


def _equipamento(model, ramo, barra=None):
    """Ramos que compõem o EQUIPAMENTO do ramo dado: transformador de três enrolamentos é
    representado com nó fictício (tensão nula), e retirá-lo exige todas as pernas.
    Transformador de dois enrolamentos, linha e capacitor série são o próprio ramo."""
    a, b, c = ramo[0], ramo[1], str(ramo[2])
    for no in (a, b):
        if no != barra and not model.bus_kv.get(no):
            return [(x['bf'], x['bt'], str(x['nc'])) for x in model.branches
                    if no in (x['bf'], x['bt'])]
    return [(a, b, c)]


def _k0(br):
    """Fator de compensação de sequência zero: k0 = (Z0L − Z1L) / (3·Z1L)."""
    z1 = zfin(br.get('R1'), br.get('X1'))
    z0 = zfin(br.get('R0'), br.get('X0'))
    if z1 is None or z0 is None or abs(z1) < 1e-12:
        return None
    return (z0 - z1) / (3 * z1)


def relatorio_protecao(model, tipo, elemento, modo='completo', dados=None,
                       kinds=_KINDS, n1=True):
    """Relatório de proteção de um equipamento: linha, transformador, barra, reator ou
    capacitor série.

    `elemento` é (bf, bt, nc) para linha, transformador e capacitor; o número da barra
    para barra; e (barra, nc) ou a barra para reator. `dados` são os valores externos que
    o usuário já tem (relação de TC, placa, carga máxima); o que faltar é listado, não
    estimado.

    Monta, conforme o tipo:

      linha         correntes nos dois terminais, falta com terminal remoto aberto em
                    várias posições, Z1, Z0 e k0, e N-1 na barra local
      transformador passa-através por enrolamento, correntes nas barras dos dois lados —
                    o 50 precisa ser sensível na local e insensível na do outro lado
      barra         envelope por bay com o cenário de cada extremo e ICC_MIN de recomposição
      reator        correntes no ponto de conexão e falta intermediária no reator
      capacitor     correntes nos terminais, para avaliar sub e sobrealcance de distância

    Devolve dict com as grandezas, as funções que o Submódulo 2.11 exige para o tipo, e
    'dados_faltantes' — o que o .ANA não contém e o critério que cada um bloqueia.

    NÃO produz ajuste. Produz os insumos: o ajuste depende de critério, e critério é
    decisão de engenharia, declarada pelo usuário.
    """
    pass
    pass
    S = _solver(model, None, modo)
    out = dict(tipo=tipo, elemento=elemento, modo=modo, grandezas={}, avisos=[])

    if tipo == 'barra':
        b = int(elemento if not isinstance(elemento, (tuple, list)) else elemento[0])
        out['grandezas']['curto_na_barra'] = relatorio_curto(model, b, kinds, modo, S)
        out['grandezas']['envelope_por_bay'] = envelope_contribuicoes(model, b, kinds,
                                                                      solver=S)
        try:
            tabela, icc_min = recomposicao_87b(model, b, modo=modo)
            out['grandezas']['recomposicao'] = dict(por_elemento=tabela, icc_min=icc_min)
        except Exception as e:
            out['avisos'].append(f"recomposição: {str(e)[:80]}")
        chave_dados = 'barra'

    elif tipo in ('linha', 'transformador', 'capacitor'):
        bf, bt, nc = (list(elemento) + ['1'])[:3]
        bf, bt, nc = int(bf), int(bt), str(nc)
        br = S._find_branch(bf, bt, nc)
        if br is None:
            raise ValueError(f"elemento {bf}-{bt}/{nc} não existe na base")
        out['grandezas']['Z1'] = zfin(br.get('R1'), br.get('X1'))
        out['grandezas']['Z0'] = zfin(br.get('R0'), br.get('X0'))
        out['grandezas']['k0'] = _k0(br)
        out['grandezas']['MVA_nominal'] = br.get('MVA')
        for rot, b in (('terminal_local', bf), ('terminal_remoto', bt)):
            out['grandezas'][f'curto_{rot}'] = relatorio_curto(model, b, kinds, modo, S)
        if tipo == 'linha':
            try:
                out['grandezas']['terminal_remoto_aberto'] = \
                    S.varredura_line_end_open(bf, bt, nc, bf, kinds)
            except Exception as e:
                out['avisos'].append(f"terminal aberto: {str(e)[:80]}")
        if tipo == 'transformador':
            for rot, b in (('local', bf), ('outro_lado', bt)):
                try:
                    out['grandezas'][f'passa_atraves_{rot}'] = \
                        S.contribution(b, '3F', modo=modo).get(
                            (br['tipo'], bf, bt, nc))
                except Exception:
                    pass
        if n1:
            viz = [r for r in _ramos_incidentes(model, bf) if r != (bf, bt, nc)]
            n1_out = {}
            for r in viz:
                try:
                    Sn = _solver(model, [r], modo)
                    n1_out[f"sem {r[0]}-{r[1]}/{r[2]}"] = {
                        k: Sn.fault(bf, k, modo=modo) for k in kinds}
                except Exception:
                    continue
            out['grandezas']['n_1_no_terminal_local'] = n1_out
        chave_dados = {'linha': 'linha', 'transformador': 'transformador',
                       'capacitor': 'linha'}[tipo]

    elif tipo == 'reator':
        b = int(elemento[0] if isinstance(elemento, (tuple, list)) else elemento)
        out['grandezas']['curto_no_ponto_de_conexao'] = relatorio_curto(model, b, kinds,
                                                                        modo, S)
        interm = {}
        for frac in (0.1, 0.25, 0.5, 0.75, 0.9):
            try:
                interm[frac] = S.fault_on_shunt(b, frac, '1FT')
            except Exception:
                continue
        if interm:
            out['grandezas']['falta_intermediaria_no_reator'] = interm
        chave_dados = 'reator'
    else:
        raise ValueError("tipo deve ser linha, transformador, barra, reator ou capacitor")

    out['funcoes_sm211'] = funcoes_exigidas(
        tipo if tipo in ('linha', 'transformador', 'reator', 'barra') else 'linha')
    falta = faltantes(chave_dados, dados,
                      model=model if tipo != 'barra' and tipo != 'reator' else None,
                      elemento=(int(elemento[0]), int(elemento[1]), str(elemento[2]))
                      if tipo in ('linha', 'transformador', 'capacitor') else None)
    out['dados_faltantes'] = falta
    out['dados_faltantes_texto'] = RELATORIO(falta, tipo)
    prem = _premissas_curto(S) + ['rede completa do ANAFAS, sem despacho de cenário']
    if n1 and tipo in ('linha', 'transformador', 'capacitor'):
        prem.append('contingência N-1: retirada de cada elemento incidente no terminal local')
    if tipo == 'barra':
        prem.append('recomposição: barra energizada por um só elemento de cada vez, com as '
                    'demais conexões e o reator de barra desligados')
        prem.append('envelope por vão: quatro tipos de defeito, rede completa e N-1 até uma '
                    'barra vizinha, retirada de equipamento e terminal remoto aberto')
    if tipo == 'linha':
        prem.append('terminal remoto aberto: para posições intermediárias, o efeito dos '
                    'conversores é aplicado pela razão medida no terminal')
    prem.append('funções exigidas conforme o Submódulo 2.11; critérios de ajuste não '
                'aplicados — o relatório traz insumos, não ajustes')
    out['premissas'] = prem
    return out


# ====================================================================== #
#  Sobrecorrente                                                         #
# ====================================================================== #

# Critérios padrão. Todos parametrizáveis: são convenção de filosofia de proteção, e o
# usuário pode ter os seus. Nenhum vem do Submódulo 2.11, que não define ajuste.
CRITERIOS_SOBRECORRENTE = {
    'linha': dict(
        f51_carga=1.20,        # pickup do 51: 120% da carga de EMERGÊNCIA da LT
        t_z2=0.40,             # tempo da zona 2, s — o 51 deve ser igual ou mais lento
        f50_margem=1.20,       # 50 só se o pickup superar a falta na barra remota nisso
        sotf_frac_min=0.80,    # SOTF abaixo de 80% do Icc mínimo remoto
        stub_frac=0.50,        # STUB até 50% do Icc da barra
        f67nt_min_in_tc=0.10,  # 67NT: no mínimo 10% de In do TC
        f67nt_max_1f=0.70,     # 67NT: no máximo 70% da monofásica remota
    ),
    'transformador': dict(
        f51_nominal=None,      # pickup do 51: sem padrão universal — informar o critério
                               # (ex.: {'f51_nominal': 1.5}); sem ele, dados_faltantes
        f50_margem=1.20,       # 50 acima do passa-através e do inrush com essa margem
    ),
    # 51V — comum a linha e transformador
    '51V': dict(
        v_partida=0.80,        # tensão de partida, pu da fase-fase nominal
        margem_k=1.20,         # k·I> ≤ falta remota mínima / margem (guia MiCOM P14x)
    ),
}


def _avaliar_51v(S, bus_rele, pickup51, faltas, crit51v, prem):
    """Verifica a necessidade da 51V e calcula o fator de redução.

    `faltas`: [(corrente_A, barra_em_falta, tipo), ...] para as faltas remotas que o 51
    deve enxergar. A 51V é necessária quando a menor delas fica abaixo do pickup do 51 —
    a impedância do equipamento limita a corrente de falta a níveis de carga, e só a
    tensão distingue as duas situações.

    Ajuste, conforme os guias de aplicação (Siemens 7SR, MiCOM P14x, Relion PHPVOC/
    VRPVOC, SEL): o pickup normal permanece acima da carga; abaixo da tensão de partida
    ele é reduzido pelo fator k, com k·I> abaixo da falta remota mínima com margem. A
    tensão no relé durante essa falta precisa ficar abaixo da tensão de partida — senão a
    51V não se sensibiliza e a proteção fica sem cobertura.
    """
    faltas = [f for f in faltas if f[0]]
    if not pickup51 or not faltas:
        return None
    imin, fbus, fk = min(faltas)
    out = dict(necessaria=imin < pickup51, i_falta_remota_min=imin,
               condicao=f'falta {fk} na barra {fbus}', pickup_51=pickup51)
    if not out['necessaria']:
        out['conclusao'] = '51 enxerga a falta remota mínima; 51V dispensável'
        return out
    k = imin / (crit51v['margem_k'] * pickup51)
    try:
        v = S.bus_voltage(fbus, bus_rele, fk)
        vrele = v['Vff_min'] if v else None
    except Exception:
        vrele = None
    out.update(v_partida=crit51v['v_partida'], k=k, pickup_51V=k * pickup51,
               v_rele_na_falta=vrele, alertas=[])
    if vrele is None:
        out['alertas'].append('tensão no relé durante a falta não calculada')
    elif vrele >= crit51v['v_partida']:
        out['alertas'].append(
            f'tensão no relé na falta remota mínima ({vrele:.3f} pu) não cai abaixo da '
            f'partida ({crit51v["v_partida"]:.2f} pu): a 51V não se sensibiliza')
    if k < 0.1:
        out['alertas'].append(f'fator k = {k:.2f} abaixo da faixa usual dos relés')
    # Os dois princípios são objetos distintos (L09): no CONTROLE, a tensão habilita um
    # pickup reduzido fixo; na RESTRIÇÃO, o pickup varia continuamente com a tensão. Aqui a
    # restrição usa a forma linear genérica pickup(V) = I>·max(k, V/Vs); a curva real de
    # cada IED vem do perfil do fabricante.
    vs = crit51v['v_partida']
    out['controle'] = dict(
        habilita=(vrele is not None and vrele < vs), pickup=k * pickup51,
        margem=(imin / (k * pickup51)) if (vrele is not None and vrele < vs) else None)
    if vrele is not None:
        pk_r = pickup51 * max(k, min(1.0, vrele / vs))
        out['restricao'] = dict(pickup_na_tensao=pk_r, margem=imin / pk_r,
                                opera=imin > pk_r, forma='linear genérica')
        if imin <= pk_r:
            out['alertas'].append(f'na restrição, o pickup na tensão da falta ({pk_r:.0f} A) '
                                  f'fica acima da falta remota mínima ({imin:.0f} A)')
    prem.append(f"51V: necessária quando a falta remota mínima fica abaixo do pickup do 51; "
                f"partida em {crit51v['v_partida']:.2f} pu da tensão fase-fase; pickup "
                f"reduzido por k com k·I> ≤ falta remota mínima / {crit51v['margem_k']:.1f}; "
                f"bloqueio por falha de fusível do TP; tensão no relé verificada no modo do "
                f"estudo")
    return out



CAMPOS_EVIDENCIA = ('fonte', 'secao', 'revisao', 'base', 'unidade', 'resolucao',
                    'classe_evidencia')


def politica_exportacao(resultado, perfil_ied=None):
    """Decide se um resultado de ajuste pode ser exportado como ajuste de IED.

    Exportar exige: perfil do IED com cada regra documentada (fonte, seção, revisão, base,
    unidade, resolução, classe de evidência) e toda função em calculavel_verificada. Um
    exemplo de manual não vira requisito. Sem isso, o resultado serve como INSUMO de
    estudo, não como ajuste a transferir para o relé.
    """
    motivos = []
    if not perfil_ied:
        motivos.append('perfil de IED não informado')
    else:
        for par, regra in (perfil_ied.get('regras') or {}).items():
            falta = [c for c in CAMPOS_EVIDENCIA if not regra.get(c)]
            if falta:
                motivos.append(f'regra {par} sem ' + ', '.join(falta))
            if regra.get('classe_evidencia') == 'exemplo':
                motivos.append(f'regra {par} tem classe "exemplo": não vira requisito')
    for nome, f in (resultado.get('funcoes') or {}).items():
        itens = f.values() if isinstance(f, dict) and 'estado' not in f else [f]
        for x in itens:
            if isinstance(x, dict) and x.get('estado') not in (None, 'calculavel_verificada'):
                motivos.append(f'{nome}: {x.get("estado")}')
    return dict(exportavel=not motivos, motivos=motivos)


ESTADOS = ('calculavel_verificada', 'faixa_inviavel', 'dados_faltantes',
           'modelo_nao_suportado', 'validacao_pendente', 'erro_execucao')


def _estado(f, conferido=True):
    """Estado explícito de um resultado de ajuste. Resultado incompleto nunca aparece
    como faixa aprovada."""
    if f.get('erro'):
        return 'erro_execucao'
    if f.get('viavel') is False or f.get('necessaria') and f.get('alertas') and any(
            'não se sensibiliza' in a for a in f['alertas']):
        return 'faixa_inviavel'
    if f.get('pickup') is None and f.get('min') is None and f.get('max') is None:
        return 'dados_faltantes'
    if f.get('viavel') is None and ('min' in f or 'max' in f) and (
            f.get('min') is None or f.get('max') is None):
        return 'dados_faltantes'
    return 'calculavel_verificada' if conferido else 'validacao_pendente'


def quantizar(valor, faixa, passo, sentido='baixo'):
    """Arredonda um ajuste ao passo do relé sem sair da faixa admissível.

    `sentido`='baixo' arredonda para baixo (ajustes limitados por sensibilidade), 'cima'
    para cima (limitados por segurança). Se o valor arredondado sair da faixa, tenta o
    outro sentido; se nenhum couber, devolve None — a faixa não comporta o passo do relé.
    """
    import math
    if valor is None or not passo:
        return valor
    lo, hi = faixa if faixa else (None, None)
    f = math.floor if sentido == 'baixo' else math.ceil
    g = math.ceil if sentido == 'baixo' else math.floor
    for fn in (f, g):
        q = fn(valor / passo) * passo
        if (lo is None or q >= lo - 1e-9) and (hi is None or q <= hi + 1e-9):
            return q
    return None


def _faixa(minimo, maximo):
    """Faixa admissível. Viável se o limite inferior não exceder o superior."""
    if minimo is None or maximo is None:
        return dict(min=minimo, max=maximo, viavel=None)
    return dict(min=minimo, max=maximo, viavel=minimo <= maximo)


def ajuste_sobrecorrente(model, tipo, elemento, dados=None, criterios=None,
                         modo='completo', curva='MI', norma='IEC', cenarios=None,
                         perfil_ied=None):
    """Faixas admissíveis e viabilidade das funções de sobrecorrente de um equipamento.

    NÃO escolhe o ajuste. Para cada função devolve a faixa que os critérios admitem, se ela
    é viável, qual limite governa, e o que falta para fechá-la. Escolher dentro da faixa é
    decisão de engenharia.

    `tipo`: 'linha' ou 'transformador'. `elemento`: (bf, bt, nc), com `bf` o terminal do
    relé. `dados`: valores externos em A — carga_max_lt, in_tc, inrush, in_nominal. O que
    faltar é reportado, não estimado; a corrente nominal é lida da base quando o campo MVA
    está preenchido.

    `cenarios`: {nome: PwfModel} com as bases do ANAREDE. Quando fornecido, a carga
    máxima da linha sai da capacidade de emergência declarada lá, em vez de ser pedida ao
    usuário — e a origem fica registrada no retorno.

    Linha: 51 (pickup e tempo coordenado com a zona 2), 50 (só se seletivo para falta na
    barra remota), SOTF, STUB e 67NT. Transformador: 51 e 50 (acima do inrush e do
    passa-através para falta na barra do outro lado, abaixo da falta na barra local).

    Toda corrente em A primários.
    """
    pass
    _curvas = curvas
    dados = dict(dados or {})
    crit = dict(CRITERIOS_SOBRECORRENTE.get(tipo, {}))
    crit.update(criterios or {})
    bf, bt, nc = int(elemento[0]), int(elemento[1]), str(elemento[2])
    informados = {k for k, v in dados.items() if v not in (None, '')}
    da_caso = set()
    for k, v in da_base(model, bf, bt, nc).items():
        if k not in dados or dados[k] in (None, ''):
            dados[k] = v
            da_caso.add(k)
    origem_carga = 'informada pelo usuário' if dados.get('carga_max_lt') else None
    if cenarios and tipo == 'linha' and dados.get('carga_max_lt') in (None, ''):
        pass
        cm = carga_maxima(cenarios, bf, bt, nc)
        if cm and cm.get('carga_max_A'):
            dados['carga_max_lt'] = cm['carga_max_A']
            origem_carga = 'ANAREDE, ' + cm['origem']
    S = _solver(model, None, modo)
    kA = lambda x: x * 1000.0 if x is not None else None
    out = dict(tipo=tipo, elemento=(bf, bt, nc), modo=modo, curva=_curvas.descreve(curva, norma),
               criterios=crit, funcoes={}, faltantes=[], origem_carga_max=origem_carga)
    prem = _premissas_curto(S)
    prem.append(f"curva de tempo inverso: {_curvas.descreve(curva, norma)}")
    if origem_carga:
        prem.append(f"carga máxima da linha: {origem_carga}")
    if da_caso & {'in_nominal', 'in_lt'}:
        prem.append('corrente nominal obtida do campo MVA do caso .ANA')
    if informados:
        prem.append('dados informados pelo usuário: ' + ', '.join(sorted(informados)))
    out['premissas'] = prem

    def falta(k):
        if dados.get(k) in (None, ''):
            if k not in out['faltantes']:
                out['faltantes'].append(k)
            return True
        return False

    if tipo == 'linha':
        # correntes vistas pelo TC do terminal bf
        def i_ramo(fbus, kind):
            r = S.branch_current(fbus, bf, bt, nc, kind)
            return kA(r['Imax']) if r else None
        i_barra_remota = {k: i_ramo(bt, k) for k in ('3F', '1FT', '2F')}
        r1f = S.branch_current(bt, bf, bt, nc, '1FT')
        i3i0_remota = kA(r1f['I3I0']) if r1f else None      # 3I0 no TC, não a corrente de fase
        i_barra_local = {k: kA(S.fault(bf, k)) for k in ('3F', '1FT')}
        i_leo = {k: kA(S.line_end_open(bf, bt, nc, bf, k, p=1.0)) for k in ('3F', '2F', '1FT')}

        # --- 51: pickup pela carga, tempo pelo defeito mais severo ---
        pk = None if falta('carga_max_lt') else crit['f51_carga'] * float(dados['carga_max_lt'])
        severo = max(v for v in list(i_barra_remota.values()) + list(i_leo.values()) if v)
        f51 = dict(pickup=pk, criterio=f"{crit['f51_carga']:.0%} da carga máxima",
                   i_defeito_mais_severo=severo)
        prem.append(f"51 de linha: pickup em {crit['f51_carga']:.0%} da carga de emergência; "
                    f"tempo de {crit['t_z2']*1000:.0f} ms (zona 2) no defeito mais severo, "
                    f"entre falta na barra remota e terminal remoto aberto")
        prem.append(f"50 de linha: habilitado só se o pickup superar em "
                    f"{crit['f50_margem']-1:.0%} a falta na barra remota")
        prem.append(f"SOTF: acima da carga de emergência e abaixo de "
                    f"{crit['sotf_frac_min']:.0%} do curto mínimo remoto; STUB até "
                    f"{crit['stub_frac']:.0%} do curto da barra; 67NT entre "
                    f"{crit['f67nt_min_in_tc']:.0%} de In do TC e "
                    f"{crit['f67nt_max_1f']:.0%} da 3I0 no TC para monofásica remota")
        if pk:
            try:
                f51['tms_minimo'] = _curvas.tms_para_tempo(severo, pk, crit['t_z2'], curva, norma)
                f51['tempo_no_defeito'] = crit['t_z2']
            except ValueError as e:
                f51['aviso'] = str(e)
        out['funcoes']['51'] = f51
        c51v = dict(CRITERIOS_SOBRECORRENTE['51V']); c51v.update(
            {k[4:]: v for k, v in (criterios or {}).items() if k.startswith('51V_')})
        faltas = [(i_barra_remota.get(k), bt, k) for k in ('3F', '2F')]
        faltas += [(i_leo.get(k), bt, k) for k in ('3F', '2F')]
        r51v = _avaliar_51v(S, bf, pk, faltas, c51v, prem)
        if r51v:
            out['funcoes']['51V'] = r51v

        # --- 50: só se seletivo para falta na barra remota ---
        i_remota_max = max(v for v in i_barra_remota.values() if v)
        # teto do 50: falta close-in na própria linha, com a corrente que o TC realmente vê
        # (a contribuição do terminal remoto não passa por ele)
        try:
            ci = S.fault_on_branch(bf, bt, nc, 1e-3, '3F')
            i_local = kA(ci.get('I_term_%d' % bf)) if ci else None
        except Exception:
            i_local = None
        i_local = i_local or i_barra_local['3F']
        piso = crit['f50_margem'] * i_remota_max
        f50 = _faixa(piso, i_local)
        f50.update(criterio=f"acima de {crit['f50_margem']:.0%} da falta na barra remota",
                   i_barra_remota=i_remota_max, i_barra_local=i_local)
        if f50['viavel'] is False:
            f50['conclusao'] = 'não habilitar: sem seletividade para falta na barra remota'
        out['funcoes']['50'] = f50

        # --- SOTF: acima da carga de emergência, abaixo de 80% do mínimo remoto ---
        # O piso é a carga máxima (emergência): a função não pode atuar com a linha
        # energizada e carregada no limite de emergência. Sem ela, usa-se a nominal e o
        # retorno registra que o piso é provisório.
        i_min_remoto = min(v for v in (i_barra_remota['2F'], i_barra_remota['1FT']) if v)
        teto = crit['sotf_frac_min'] * i_min_remoto
        if dados.get('carga_max_lt') not in (None, ''):
            piso, base_piso = float(dados['carga_max_lt']), 'carga de emergência'
        elif not falta('in_lt'):
            piso, base_piso = float(dados['in_lt']), 'corrente nominal (provisório)'
        else:
            piso, base_piso = None, None
        fs = _faixa(piso, teto)
        fs.update(criterio=f"acima da carga de emergência e abaixo de "
                           f"{crit['sotf_frac_min']:.0%} do mínimo remoto (bifásica ou "
                           f"monofásica)",
                  i_min_remoto=i_min_remoto, base_do_piso=base_piso)
        if fs['viavel'] is False:
            fs['conclusao'] = ('faixa vazia: a carga supera o limite superior — '
                               'avaliar unidade 51V')
        out['funcoes']['SOTF'] = fs

        # --- STUB: até 50% do Icc da barra ---
        out['funcoes']['STUB'] = dict(max=crit['stub_frac'] * i_local,
                                      criterio=f"até {crit['stub_frac']:.0%} do Icc da barra",
                                      i_barra=i_local)

        # --- 67NT: entre 10% de In do TC e 70% da monofásica remota ---
        teto = crit['f67nt_max_1f'] * i3i0_remota if i3i0_remota else None
        piso = None if falta('in_tc') else crit['f67nt_min_in_tc'] * float(dados['in_tc'])
        f67 = _faixa(piso, teto)
        f67.update(criterio=f"entre {crit['f67nt_min_in_tc']:.0%} de In do TC e "
                            f"{crit['f67nt_max_1f']:.0%} da monofásica remota",
                   usual=piso, i_3i0_remota=i3i0_remota, curva='muito inversa')
        out['funcoes']['67NT'] = f67

    elif tipo == 'transformador':
        # --- 51: 150% da nominal ---
        inom = dados.get('in_nominal')
        if inom in (None, ''):
            falta('in_nominal')
        if cenarios and 'in_nominal' in da_caso:
            pass
            cm = carga_maxima(cenarios, bf, bt, nc)
            if cm and cm.get('cap_normal_A'):
                inom = cm['cap_normal_A']
                prem.append('corrente nominal do transformador: capacidade normal declarada '
                            'no ANAREDE')
        f51n = crit.get('f51_nominal')
        if not f51n and 'criterio_51_transformador' not in out['faltantes']:
            out['faltantes'].append('criterio_51_transformador')
        out['funcoes']['51'] = dict(
            pickup=f51n * float(inom) if (inom and f51n) else None,
            criterio=(f"{f51n:.0%} da nominal" if f51n else
                      'critério não definido: o múltiplo da nominal depende da filosofia e '
                      'do perfil de carga do transformador'))
        if f51n:
            prem.append(f"51 de transformador: pickup em {f51n:.0%} da corrente NOMINAL, "
                        f"critério informado; não referido à capacidade de emergência")
        prem.append(f"50 de transformador: acima de {crit['f50_margem']:.0%} do maior entre "
                    f"o passa-através para falta na barra do outro lado e o inrush, e "
                    f"abaixo da falta na barra local; banco de três enrolamentos com a "
                    f"barra do outro lado localizada pelo nó-estrela")
        # --- 50: faixa entre passa-através/inrush e falta local ---
        # Em banco de três enrolamentos o `bt` do elemento é o nó-estrela fictício
        # (kV = 0), não uma barra física. A "barra do outro lado" é a do enrolamento de
        # maior tensão entre as demais pernas do mesmo nó — é nela que a falta passante
        # deve ser aplicada, com a corrente medida no ramo do terminal do relé.
        outro = bt
        if not model.bus_kv.get(bt):
            pernas = [(x['bt'] if x['bf'] == bt else x['bf']) for x in model.branches
                      if x['tipo'] == 'T' and bt in (x['bf'], x['bt'])]
            pernas = [b for b in pernas if b != bf and model.bus_kv.get(b)]
            if pernas:
                outro = max(pernas, key=lambda b: model.bus_kv.get(b, 0))
        out['barra_outro_lado'] = outro
        pk51 = out['funcoes']['51']['pickup']
        c51v = dict(CRITERIOS_SOBRECORRENTE['51V']); c51v.update(
            {k[4:]: v for k, v in (criterios or {}).items() if k.startswith('51V_')})
        faltas = []
        for k in ('3F', '2F'):
            try:
                r = S.branch_current(outro, bf, bt, nc, k)
                faltas.append((kA(r['Imax']) if r else None, outro, k))
            except Exception:
                pass
        r51v = _avaliar_51v(S, bf, pk51, faltas, c51v, prem)
        if r51v:
            out['funcoes']['51V'] = r51v
        try:
            r = S.branch_current(outro, bf, bt, nc, '3F')
            passa = r['Imax'] if r else None
        except Exception:
            passa = None
        passa = kA(passa)
        # teto do 50 do transformador: falta nos terminais do próprio transformador, com a
        # corrente vista pelo TC do lado do relé
        try:
            ci = S.fault_on_branch(bf, bt, nc, 1e-3, '3F')
            i_local = kA(ci.get('I_term_%d' % bf)) if ci else None
        except Exception:
            i_local = None
        i_local = i_local or kA(S.fault(bf, '3F'))
        base = [x for x in (passa, None if falta('inrush') else float(dados['inrush'])) if x]
        piso = crit['f50_margem'] * max(base) if base else None
        f50 = _faixa(piso, i_local)
        f50.update(criterio=f"acima de {crit['f50_margem']:.0%} do passa-através e do inrush, "
                            f"abaixo da falta na barra local",
                   i_passante_barra_outro_lado=passa, i_barra_local=i_local)
        if f50['viavel'] is False:
            f50['conclusao'] = 'faixa vazia: 50 não é seletivo'
        out['funcoes']['50'] = f50
    else:
        raise ValueError("tipo deve ser 'linha' ou 'transformador'")
    conferido = bool(S.selo_completo().get('conferido_no_caso')) or not (
        S.modo == 'completo' and S._tem_fc())
    for f in out['funcoes'].values():
        if isinstance(f, dict):
            f['estado'] = _estado(f, conferido)
    out['exportacao'] = politica_exportacao(out, perfil_ied)
    return out


# ====================================================================== #
#  Estudo de proteção de barra: 87B, checkzone, alarme, 50BF e EFP       #
# ====================================================================== #

CRITERIOS_BARRA = dict(
    f_icc=0.67,          # ajuste sugerido: 67% do curto mínimo (relação de sensibilidade 1,5)
    f_checkzone=None,    # checkzone: sem escala fixa — faixa própria; informar se desejado
    f_alarme=None,       # alarme: sem escala fixa — faixa pela menor carga REAL dos vãos
    piso_in_tc=0.05,     # todo pickup acima de 5% de In do TC de referência
    f_icc_max=0.80,      # teto: pickup abaixo de 80% da menor falta (guia REB670)
    faixa_tc=(0.5, 1.5), # faixa típica do pickup: 50% a 150% de In do maior TC (guia REB670)
)

# Slope da diferencial de barra: parâmetro do IED, não do estudo. Cada fabricante define a
# corrente de restrição e a característica de forma própria, e o mesmo percentual produz
# curvas diferentes — por isso o LINCC informa a referência de cada um em vez de calcular.
SLOPE_87B_POR_FABRICANTE = {
    'SEL-487B': 'SLP1 60% (carga e falta interna) e SLP2 80% (modo de alta segurança, '
                'comutado pela detecção de falta externa) — valores padrão do manual',
    'Siemens 7SS85': 'fator de estabilização k ajustável de 0,10 a 0,80; limiar Idiff de '
                     '0,20 a 4,00 × corrente nominal do objeto',
    'ABB/Hitachi REB670': 'slope fixo em 53% no algoritmo; só o nível de operação é ajustado',
    'GE MiCOM P74x': 'não verificado nesta revisão',
}


def estudo_barra(model, barra, dados=None, cenarios=None, criterios=None,
                 modo='completo', kinds=_KINDS, perfil_ied=None):
    """Estudo de proteção de uma barra: 87B, checkzone, alarme diferencial, 50BF e EFP.

    Resolve o estudo inteiro a partir do pedido "proteção da barra X". Tudo em A primários.

    Corrente mínima de curto na barra: o menor valor entre rede completa, N-1 de cada
    equipamento incidente (transformador com todas as pernas) e do reator de barra,
    recomposição por cada alimentação isolada (com o reator de barra desligado) e, com os
    casos do ANAREDE, o menor cenário de despacho — incluindo a recomposição nesse
    cenário. Não se usa a condição com apenas o reator de barra conectado.

    Cargas por vão: capacidade de emergência e nominal do ANAREDE; sem ele, a potência
    nominal do .ANA, declarada como provisória.

    Critérios (padrão em CRITERIOS_BARRA, todos declarados em `premissas`):

      87B        carga de emergência < pickup < curto mínimo; sugerido 67% do curto
                 mínimo. Se a faixa não existir, prevalece o curto.
      checkzone  80% do pickup do 87B.
      alarme     15% do pickup do 87B, abaixo da menor carga nominal dos vãos — para
                 detectar TC aberto sem disparo, que o pickup acima da carga garante.
      50BF       carga nominal do vão < pickup < falta na extremidade oposta da linha com
                 o terminal remoto aberto, com a alimentação local mais fraca.
      EFP        pickup < falta junto ao disjuntor aberto, nas duas posições de TC; sem
                 piso de carga, porque com o disjuntor aberto só circula corrente de falta.
      todas      pickup >= 5% de In do TC de referência (maior relação da zona), quando
                 `dados['in_tc_ref']` é informado, ou o ajuste mínimo do relé, se maior.

    Slope: valores de partida declarados, não calculados — dependem da definição de
    restrição do IED e do estudo de saturação.

    O estudo fatora uma topologia por condição (N-1, recomposição, cada par de linha e
    alimentação fraca) e leva alguns minutos numa base do SIN.
    """
    pass
    pass
    crit = dict(CRITERIOS_BARRA); crit.update(criterios or {})
    dados = dict(dados or {})
    kv = model.bus_kv.get(barra)
    Ib = SB / (np.sqrt(3) * kv)
    inc = _ramos_incidentes(model, barra)
    kinds = tuple(kinds)

    def outro(r):
        return r[1] if r[0] == barra else r[0]

    def e_trafo(r):
        return not model.bus_kv.get(outro(r))

    def equipamento(r):
        return _equipamento(model, r, barra)

    def nome(r):
        return f"{'T' if e_trafo(r) else 'L'} {r[0]}-{r[1]}/{r[2]}"

    S0 = _solver(model, None, modo)
    prem = _premissas_curto(S0)
    cand = []          # (corrente_A, condição)

    I_DESENERGIZADA = 1.0     # A — abaixo disso a condição deixa a barra sem alimentação

    def curto_barra(S, rot):
        for k in kinds:
            try:
                v = S.fault(barra, k) * 1000.0
            except Exception:
                continue
            if v > I_DESENERGIZADA:
                cand.append((v, f'{rot}, {k}'))

    # --- corrente mínima na barra ---
    curto_barra(S0, 'rede completa')
    for r in inc:
        try:
            curto_barra(_solver(model, equipamento(r), modo), f'N-1 sem {nome(r)}')
        except Exception:
            pass
    tem_reator = any(h.get('bus') == barra for h in model.shunts)
    if tem_reator:
        curto_barra(_solver(model, None, modo, drop_reatores_barra=[barra]),
                    'N-1 sem o reator de barra')
    tab, _ = recomposicao_87b(model, barra, kinds=kinds, modo=modo)
    for rot, ram, v in tab:
        for k in kinds:
            if v.get(k) and v[k] * 1000.0 > I_DESENERGIZADA:
                cand.append((v[k] * 1000.0, f'recomposição por {nome(ram)}, {k}'))
    recomp = {ram: v for _, ram, v in tab}
    if cenarios:
        pass
        cc = curto_por_cenario(model, cenarios, [barra], kinds=kinds, modo=modo,
                               caso_conferido=bool(getattr(model, '_leitura_conferida', None)))
        piores = []
        for k in kinds:
            e = cc['extremos'].get((barra, k))
            if e:
                cand.append((e['min'][0], f"cenário {e['min'][1]}, {k}"))
                piores.append(e['min'])
        if piores:
            nome_cen = min(piores)[1]
            Mc, _ = aplicar_despacho(model, cenarios[nome_cen], sem_correspondencia='retirar')
            tabc, _ = recomposicao_87b(Mc, barra, kinds=kinds, modo=modo)
            for rot, ram, v in tabc:
                for k in kinds:
                    if v.get(k) and v[k] * 1000.0 > I_DESENERGIZADA:
                        cand.append((v[k] * 1000.0,
                                     f'recomposição por {nome(ram)} no cenário {nome_cen}, {k}'))
        prem += [p for p in cc['premissas'] if p not in prem]
    icc_min, cond_min = min(cand)
    categorias = {}
    for v, c in cand:
        cat = ('recomposição' if c.startswith('recomposição') else
               'cenário' if c.startswith('cenário') else
               'contingência' if c.startswith('N-1') else 'rede completa')
        if cat not in categorias or v < categorias[cat][0]:
            categorias[cat] = (v, c)

    # --- cargas por vão ---
    cargas = {}
    for r in inc:
        c = dict(emergencia_A=None, nominal_A=None, origem=None)
        if cenarios:
            pass
            cm = carga_maxima(cenarios, r[0], r[1], r[2])
            if cm and (cm.get('cap_emergencia_A') or cm.get('cap_normal_A')):
                c.update(emergencia_A=cm.get('cap_emergencia_A') or cm.get('cap_normal_A'),
                         nominal_A=cm.get('cap_normal_A'), origem='ANAREDE')
        if c['origem'] is None:
            b = da_base(model, *r)
            if b.get('in_nominal'):
                c.update(nominal_A=b['in_nominal'], emergencia_A=None,
                         origem='.ANA, potência nominal; capacidade de emergência não '
                                'declarada')
        cargas[nome(r)] = c
    emerg = [c['emergencia_A'] for c in cargas.values() if c['emergencia_A']]
    nomin = [c['nominal_A'] for c in cargas.values() if c['nominal_A']]
    hip_carga = None
    if emerg:
        carga_max = max(emerg)
    elif nomin:
        # HIPÓTESE EXPLÍCITA: sem capacidade de emergência declarada, o piso de carga usa a
        # nominal — que é menor que a emergência e portanto não protege contra atuação em
        # regime de emergência. Registrada nas premissas e nos alertas do 87B.
        carga_max = max(nomin)
        hip_carga = ('capacidade de emergência não declarada: piso de carga do 87B pela '
                     'NOMINAL, abaixo da emergência real')
    else:
        carga_max = None
    carga_min_nom = min(nomin) if nomin else None

    carga_min_real = None
    if cenarios:
        pass
        reais = []
        for pwf in cenarios.values():
            fl = fluxos(pwf)
            for r in inc:
                f = fl.get((r[0], r[1], r[2])) or fl.get((r[1], r[0], r[2]))
                if f and f.get('calculavel'):
                    i = f['I_de_A'] if (f is fl.get((r[0], r[1], r[2])) and r[0] == barra) \
                        else f['I_para_A']
                    if i:
                        reais.append(i)
        carga_min_real = min(reais) if reais else None
    in_ref = dados.get('in_tc_ref')
    piso_tc = (max(crit['piso_in_tc'], dados.get('ajuste_minimo_rele', 0) or 0) * float(in_ref)
               if in_ref else None)

    def aplica_piso(v, alertas):
        if piso_tc and v < piso_tc:
            alertas.append(f'elevado ao piso de medição de {piso_tc:.0f} A '
                           f'({crit["piso_in_tc"]:.0%} de In do TC de referência)')
            return piso_tc
        return v

    funcoes, alertas87 = {}, []
    if hip_carga:
        alertas87.append(hip_carga)
        prem.append(hip_carga)
    sug = crit['f_icc'] * icc_min
    if carga_max is None:
        pk = sug; alertas87.append('carga dos vãos não disponível: piso de carga não verificado')
    elif carga_max < icc_min:
        if sug > carga_max:
            pk = sug
        else:
            pk = carga_max
            alertas87.append(f'67% do curto mínimo fica abaixo da carga de emergência; '
                             f'pickup na carga, com relação de sensibilidade '
                             f'{icc_min / pk:.2f}')
    else:
        pk = sug
        alertas87.append('carga de emergência acima do curto mínimo: prevalece o curto — '
                         'TC aberto no vão mais carregado pode provocar disparo')
    pk = aplica_piso(pk, alertas87)
    if pk > crit['f_icc_max'] * icc_min:
        alertas87.append(f"pickup acima de {crit['f_icc_max']:.0%} do curto mínimo "
                         f"(teto recomendado pelo guia do REB670)")
    if in_ref:
        lo, hi = crit['faixa_tc']
        if not (lo * float(in_ref) <= pk <= hi * float(in_ref)):
            alertas87.append(f"pickup fora da faixa típica de {lo:.0%} a {hi:.0%} de In do "
                             f"maior TC ({lo*float(in_ref):.0f} a {hi*float(in_ref):.0f} A)")
    if pk >= icc_min:
        alertas87.append('pickup não fica abaixo do curto mínimo: sensibilidade não garantida')
    passo = crit.get('passo_ajuste')
    if passo:
        q = quantizar(pk, (carga_max, crit['f_icc_max'] * icc_min), passo, 'baixo')
        if q is None:
            alertas87.append(f'faixa não comporta o passo de ajuste de {passo} A')
        else:
            pk = q
    funcoes['87B'] = dict(pickup=pk, faixa=(carga_max, icc_min), icc_min=icc_min,
                          minimos_por_categoria=categorias,
                          condicao_icc_min=cond_min, relacao=icc_min / pk,
                          carga_emergencia_max=carga_max, alertas=alertas87)
    # checkzone: critério próprio — operar para toda falta interna da barra, com a mesma
    # corrente mínima; sem escala fixa em relação ao 87B
    ac = []
    teto_ck = crit['f_icc_max'] * icc_min
    if crit.get('f_checkzone'):
        ck = aplica_piso(crit['f_checkzone'] * pk, ac)
    else:
        ck = None
        ac.append('ajuste não sugerido: informe o critério da checkzone; a faixa garante '
                  'operação para toda falta interna')
    funcoes['checkzone'] = dict(pickup=ck, min=piso_tc, max=teto_ck,
                                viavel=(piso_tc or 0) <= teto_ck,
                                relacao=(icc_min / ck) if ck else None, alertas=ac)
    # alarme de TC aberto: abaixo da MENOR CORRENTE REAL conduzida pelos vãos — é ela que
    # aparece como diferencial quando um TC abre; a nominal não serve de referência.
    # Limite inferior (diferencial permanente) e temporização dependem dos TCs.
    aa = []
    if carga_min_real is None:
        aa.append('menor corrente real dos vãos indisponível: requer os casos do ANAREDE')
    if crit.get('f_alarme'):
        al = aplica_piso(crit['f_alarme'] * pk, aa)
    else:
        al = None
        aa.append('ajuste não sugerido: informe o critério; o limite superior é a menor '
                  'corrente real dos vãos')
    if al and carga_min_real and al >= carga_min_real:
        aa.append(f'alarme acima da menor corrente real dos vãos ({carga_min_real:.0f} A): '
                  f'TC aberto nesse vão não será detectado')
    funcoes['alarme'] = dict(pickup=al, min=None, max=carga_min_real,
                             viavel=None, temporizacao=None,
                             limite_superior=carga_min_real, alertas=aa)
    funcoes['slope'] = dict(calculado=False, por_fabricante=dict(SLOPE_87B_POR_FABRICANTE),
                            observacao='parâmetro do IED: seguir o manual do fabricante e o '
                                       'estudo de saturação dos TCs')

    # --- 50BF e EFP por vão de linha ---
    bf, efp = {}, {}
    falhas = []
    linhas = [r for r in inc if not e_trafo(r)]
    conf = getattr(model, '_leitura_conferida', None)
    for L in linhas:
        rem = outro(L)
        c50, cef_l = [], []
        for k in kinds:
            # 50BF: falta na extremidade oposta com o terminal remoto aberto (rede normal)
            try:
                v = S0.line_end_open(L[0], L[1], L[2], barra, k, p=1.0)
                if v:
                    c50.append((v * 1000.0,
                                f'falta na extremidade oposta, remoto aberto, rede normal, {k}'))
            except Exception as ex:
                falhas.append(f'50BF {nome(L)} rede normal {k}: {type(ex).__name__}')
            # EFP lado da linha: disjuntor local aberto, falta junto a ele, alimentação remota
            try:
                v = S0.line_end_open(L[0], L[1], L[2], rem, k, p=1.0)
                if v:
                    cef_l.append((v * 1000.0,
                                  f'disjuntor local aberto, alimentação pelo terminal remoto, {k}'))
            except Exception as ex:
                falhas.append(f'EFP {nome(L)} {k}: {type(ex).__name__}')
        for F in inc:
            if F == L:
                continue
            # alimentação local só por F; a linha L fica, e é aberta no terminal remoto
            SF = Solver(model, drop_branches=[x for x in inc if x not in (F, L)],
                        drop_reatores_barra=[barra], modo=modo)
            if modo == 'completo':
                if conf:
                    SF.validado_completo = True
                    SF._selo_completo = dict(conf, conferido_no_caso=True)
                else:
                    SF.liberar_completo_sem_gabarito('cenário de alimentação fraca')
            for k in kinds:
                try:
                    v = SF.line_end_open(L[0], L[1], L[2], barra, k, p=1.0)
                except Exception as ex:
                    falhas.append(f'50BF {nome(L)} só {nome(F)} {k}: {type(ex).__name__}')
                    continue
                if v:
                    c50.append((v * 1000.0,
                                f'extremidade oposta, remoto aberto, só {nome(F)}, {k}'))
        cef_b = [(recomp[F][k] * 1000.0, f'alimentação só por {nome(F)}, {k}')
                 for F in recomp if F != L for k in kinds
                 if recomp[F].get(k) and recomp[F][k] * 1000.0 > I_DESENERGIZADA]
        c50 = [x for x in c50 if x[0] > I_DESENERGIZADA]
        cef_l = [x for x in cef_l if x[0] > I_DESENERGIZADA]
        if not c50 or not cef_l:
            continue
        car = cargas[nome(L)]
        i50, c50m = min(c50)
        a50 = []
        s50 = crit['f_icc'] * i50
        if car['nominal_A'] and s50 <= car['nominal_A']:
            if car['nominal_A'] < i50:
                s50 = car['nominal_A']
                a50.append('67% do curto mínimo fica abaixo da carga nominal; pickup na carga')
            else:
                a50.append('carga nominal acima do curto mínimo: prevalece o curto')
        s50 = aplica_piso(s50, a50)
        bf[nome(L)] = dict(pickup=s50, faixa=(car['nominal_A'], i50), icc_min=i50,
                           condicao=c50m, relacao=i50 / s50, alertas=a50)
        il, cl = min(cef_l)
        ib_, cb = min(cef_b) if cef_b else (None, None)
        el, eb = [], []
        efp[nome(L)] = dict(
            tc_lado_linha=dict(pickup=aplica_piso(crit['f_icc'] * il, el), icc_min=il,
                               condicao=cl, alertas=el),
            tc_lado_barra=(dict(pickup=aplica_piso(crit['f_icc'] * ib_, eb), icc_min=ib_,
                                condicao=cb, alertas=eb) if ib_ else None))
    funcoes['50BF'] = bf
    funcoes['EFP'] = efp
    conferido = bool(getattr(model, '_leitura_conferida', None)) or not S0._tem_fc() \
        or modo != 'completo'
    for nomef in ('87B', 'checkzone', 'alarme'):
        funcoes[nomef]['estado'] = _estado(funcoes[nomef], conferido)
    funcoes['slope']['estado'] = 'modelo_nao_suportado'
    for grupo in (bf, efp):
        for v in grupo.values():
            for f in ([v] if 'pickup' in v else [x for x in v.values() if isinstance(x, dict)]):
                f['estado'] = _estado(f, conferido)

    prem += [
        f'corrente mínima na barra: menor entre rede completa, N-1 de cada equipamento '
        f'(transformador com todas as pernas){", reator de barra" if tem_reator else ""} e '
        f'recomposição por cada alimentação isolada' +
        (', e o menor cenário de despacho do ANAREDE com a sua recomposição' if cenarios else ''),
        'recomposição: demais conexões e reator de barra desligados; não se usa a condição '
        'com apenas o reator de barra conectado',
        'condições que deixam a barra sem alimentação são desconsideradas',
        f"87B: acima da carga de emergência e abaixo do curto mínimo; sugerido "
        f"{crit['f_icc']:.0%} do curto mínimo; se a faixa não existir, prevalece o curto",
        "checkzone: faixa própria — acima do piso de medição e abaixo do teto de "
        "sensibilidade para toda falta interna; sem escala fixa em relação ao 87B",
        "alarme de TC aberto: abaixo da menor corrente REAL conduzida pelos vãos nos "
        "cenários do ANAREDE; limite inferior (diferencial permanente) e temporização "
        "dependem dos TCs e não foram verificados",
        f"50BF: acima da carga nominal do vão e abaixo da falta na extremidade oposta com o "
        f"terminal remoto aberto, na alimentação local mais fraca; sugerido "
        f"{crit['f_icc']:.0%} dessa corrente. Disparos sem corrente de falta (sobretensão, "
        f"transferência) exigem lógica por contato do disjuntor; se a sensibilidade exigir, o "
        f"detector pode ficar abaixo da carga — a iniciação por disparo evita operação indevida",
        f"EFP: abaixo da falta junto ao disjuntor aberto, sugerido {crit['f_icc']:.0%}; lado "
        f"da linha alimentado pelo terminal remoto, lado da barra pela barra; sem piso de "
        f"carga; a posição real do TC define qual vale",
        "slope: parâmetro do IED, não calculado — SEL-487B 60%/80% com comutação por falta "
        "externa, Siemens 7SS85 k de 0,10 a 0,80, REB670 fixo em 53%; os percentuais não são "
        "transferíveis entre fabricantes",
        f"87B: verificado o teto de {crit['f_icc_max']:.0%} do curto mínimo e, com o TC "
        f"informado, a faixa típica de {crit['faixa_tc'][0]:.0%} a {crit['faixa_tc'][1]:.0%} "
        f"de In do maior TC (guia do REB670)",
        'cargas por vão: ' + ('capacidades do ANAREDE (emergência e normal)' if cenarios
                              else 'potência nominal do .ANA; emergência não disponível'),
        'arranjo da subestação não informado: cargas por vão, sem composição por diagonal',
        '50BF e EFP de vãos de transformador não calculados',
    ]
    if piso_tc:
        prem.append(f"piso de medição: {crit['piso_in_tc']:.0%} de In do TC de referência "
                    f"({float(in_ref):.0f} A)")
    faltantes = []
    if not in_ref:
        faltantes.append('in_tc_ref')
    if not cenarios:
        faltantes.append('casos do ANAREDE (carga de emergência por vão)')
    res = dict(barra=barra, nome=model.bus_name.get(barra, ''), kv=kv, modo=modo,
                funcoes=funcoes, cargas=cargas, premissas=prem, faltantes=faltantes,
                falhas=falhas,
                funcoes_sm211=funcoes_exigidas('barra'))
    res['exportacao'] = politica_exportacao(res, perfil_ied)
    return res


# ====================================================================== #
#  Diferencial de linha (87L)                                            #
# ====================================================================== #

def estudo_87L(model, linha, dados=None, criterios=None, modo='completo',
               kinds=_KINDS, posicoes=(0.001, 0.5, 0.999), n1=True, perfil_ied=None):
    """Diferencial de linha de dois terminais: faixa de pickup e referências de estabilidade.

    Limite inferior: corrente capacitiva da linha na tensão máxima de operação — aparece
    como diferencial em regime. Limite superior: a menor corrente diferencial para falta
    INTERNA, varrida ao longo da linha (`posicoes`) em rede completa e N-1 em torno dos
    dois terminais; a diferencial de uma falta interna é a própria corrente de falta, com
    os dois terminais alimentando ou com um deles fraco. Referência de estabilidade: a
    maior corrente passante para falta externa nas duas barras.

    `criterios`: 'v_max' (pu, padrão 1,05), 'margem_capacitiva' e 'relacao_sensibilidade'
    (sem padrão — critério do usuário); `dados`: 'in_tc_ref' para o piso de medição.
    A característica percentual, a compensação de corrente capacitiva e o canal de
    comunicação do IED não estão modelados.
    """
    crit = dict(criterios or {})
    dados = dict(dados or {})
    bf, bt, nc = int(linha[0]), int(linha[1]), str(linha[2])
    S0 = _solver(model, None, modo)
    br = S0._find_branch(bf, bt, nc)
    if br is None or br['tipo'] != 'L':
        raise ValueError(f'linha {bf}-{bt}/{nc} não encontrada')
    kv = model.bus_kv.get(bf)
    Ib = SB / (np.sqrt(3) * kv) * 1000.0                  # A
    vmax = crit.get('v_max', 1.05)
    b_pu = (br.get('S1') or 0.0) / 100.0                  # susceptância total, pu
    i_cap = b_pu * vmax * Ib if b_pu else None
    prem = _premissas_curto(S0)

    cen = [('rede completa', [])]
    if n1:
        vistos = set()
        for b in (bf, bt):
            for r in _ramos_incidentes(model, b):
                eq = tuple(sorted(_equipamento(model, r, b)))
                if (bf, bt, nc) in eq or (bt, bf, nc) in eq or eq in vistos:
                    continue
                vistos.add(eq)
                cen.append((f'N-1 sem {r[0]}-{r[1]}/{r[2]}', list(eq)))
    internas, externas, falhas = [], [], []
    for rot, drop in cen:
        try:
            S = S0 if not drop else _solver(model, drop, modo)
        except Exception as ex:
            falhas.append(f'{rot}: {type(ex).__name__}')
            continue
        for k in kinds:
            for p in posicoes:
                try:
                    r = S.fault_on_branch(bf, bt, nc, p, k)
                except Exception as ex:
                    falhas.append(f'{rot}, p={p}, {k}: {type(ex).__name__}')
                    continue
                if r and r.get('If'):
                    internas.append((r['If'] * 1000.0, f'{rot}, falta interna a {p:.0%}, {k}'))
            for fb in (bf, bt):
                try:
                    r = S.branch_current(fb, bf, bt, nc, k)
                except Exception as ex:
                    falhas.append(f'{rot}, externa em {fb}, {k}: {type(ex).__name__}')
                    continue
                if r:
                    externas.append((r['Imax'] * 1000.0, f'{rot}, falta externa em {fb}, {k}'))
    i_int_min = min(internas) if internas else (None, None)
    i_ext_max = max(externas) if externas else (None, None)
    alertas = []
    piso = i_cap * crit['margem_capacitiva'] if (i_cap and crit.get('margem_capacitiva')) else i_cap
    if dados.get('in_tc_ref'):
        piso_tc = 0.05 * float(dados['in_tc_ref'])
        if piso is None or piso_tc > piso:
            piso = piso_tc
    teto = (i_int_min[0] / crit['relacao_sensibilidade']
            if (i_int_min[0] and crit.get('relacao_sensibilidade')) else i_int_min[0])
    viavel = (piso is None or teto is None) or piso < teto
    if not viavel:
        alertas.append('corrente capacitiva acima da menor falta interna: exige compensação '
                       'de corrente capacitiva no IED')
    if not crit.get('relacao_sensibilidade'):
        alertas.append('relação de sensibilidade não informada: teto na própria falta mínima')
    prem += [
        f'corrente capacitiva da linha a {vmax:.2f} pu, pela susceptância total do cadastro',
        'falta interna varrida em ' + ', '.join(f'{p:.0%}' for p in posicoes) +
        ' da linha, rede completa e N-1 em torno dos dois terminais; diferencial = corrente '
        'de falta',
        'estabilidade referida à maior corrente passante para falta externa nas duas barras',
        'característica percentual, compensação capacitiva e canal do IED não modelados',
    ]
    f = dict(min=piso, max=teto, viavel=viavel, pickup=None,
             i_capacitiva=i_cap, i_interna_min=i_int_min[0], condicao_interna=i_int_min[1],
             i_passante_max=i_ext_max[0], condicao_passante=i_ext_max[1], alertas=alertas)
    conferido = bool(getattr(model, '_leitura_conferida', None)) or not S0._tem_fc() \
        or modo != 'completo'
    f['estado'] = _estado(f, conferido)
    out = dict(linha=(bf, bt, nc), modo=modo, funcoes={'87L': f}, premissas=prem,
               falhas=falhas,
               faltantes=[x for x, ok in (('relacao_sensibilidade', crit.get('relacao_sensibilidade')),
                                         ('in_tc_ref', dados.get('in_tc_ref'))) if not ok])
    out['exportacao'] = politica_exportacao(out, perfil_ied)
    return out


# ===================== protecao de distancia =====================

def para_secundario(valor, grandeza, rtc=None, rtp=None):
    """Converte grandeza primária para o secundário dos transformadores de instrumento.

    grandeza: 'corrente' (A → A, divide pela relação do TC), 'tensao' (kV → V, divide pela
    relação do TP) ou 'impedancia' (Ω → Ω, multiplica por RTC/RTP). As relações são
    adimensionais (ex.: TC 3000/1 → 3000; TP 500 kV/115 V → 4347,8). Sem a relação
    necessária devolve None: não se exporta secundário sem o dado.
    """
    if valor is None:
        return None
    if grandeza == 'corrente':
        return valor / rtc if rtc else None
    if grandeza == 'tensao':
        return valor * 1000.0 / rtp if rtp else None
    if grandeza == 'impedancia':
        return valor * rtc / rtp if (rtc and rtp) else None
    raise ValueError("grandeza deve ser 'corrente', 'tensao' ou 'impedancia'")


def _lacos(V, I, k0):
    """Impedâncias aparentes dos laços de interesse, em Ω primários, por tipo de falta."""
    Va, Vb, Vc = V['Va_c'], V['Vb_c'], V['Vc_c']
    Ia, Ib, Ic = I['Ia'], I['Ib'], I['Ic']
    IN = Ia + Ib + Ic

    def z(num, den):
        return num / den if abs(den) > 1e-12 else None
    return {'AG': z(Va, Ia + k0 * IN), 'BG': z(Vb, Ib + k0 * IN), 'CG': z(Vc, Ic + k0 * IN),
            'AB': z(Va - Vb, Ia - Ib), 'BC': z(Vb - Vc, Ib - Ic)}


_LACO_POR_FALTA = {'1FT': ('AG',), '2F': ('BC',), '2FT': ('BC', 'BG', 'CG'), '3F': ('AB',)}


def estudo_distancia(model, linha, terminal=None, criterios=None, dados=None,
                     cenarios=None, modo='completo', kinds=('3F', '1FT', '2F', '2FT'),
                     n1=True):
    """Estudo de distância de um terminal de linha.

    `linha` = (bf, bt, nc); `terminal` é a barra do relé (padrão: bf).
    `criterios`: alcances das zonas em Ω primários ou como múltiplo de Z1L, por exemplo
        {'Z1': 0.85, 'Z2': 1.2, 'Z3': 2.0, 'unidade': 'ZL'} ou {'Z1': 25.0, 'unidade': 'ohm'};
        e 'v_min_carga' (pu, padrão 0,95) e 'fp_carga' para a região de carga.
    `dados`: 'rtc' e 'rtp' (relações) para converter ao secundário.
    `cenarios`: casos do ANAREDE, para a capacidade de emergência da linha.

    Devolve dados da linha (Z1L, Z0L, k0, Kr, Kx), impedâncias aparentes por cenário para
    falta na barra remota e no fim de cada linha adjacente, os limites de alcance, o SIR
    como indicador, os alertas (capacitor série, circuito paralelo), as premissas e o
    estado.
    """
    pass
    crit = dict(criterios or {})
    dados = dict(dados or {})
    bf, bt, nc = int(linha[0]), int(linha[1]), str(linha[2])
    rele = int(terminal) if terminal is not None else bf
    remoto = bt if rele == bf else bf
    kv = model.bus_kv.get(rele)
    zb = kv * kv / SB                                    # Ω de base
    S0 = _solver(model, None, modo)
    br = S0._find_branch(bf, bt, nc)
    if br is None or br['tipo'] != 'L':
        raise ValueError(f'linha {bf}-{bt}/{nc} não encontrada')
    z1 = zfin(br.get('R1'), br.get('X1')) * zb
    z0 = zfin(br.get('R0'), br.get('X0'))
    z0 = z0 * zb if z0 is not None else None
    k0 = (z0 - z1) / (3 * z1) if z0 is not None else 0j
    kr = ((z0.real - z1.real) / (3 * z1.real)) if (z0 is not None and abs(z1.real) > 1e-9) else None
    kx = ((z0.imag - z1.imag) / (3 * z1.imag)) if (z0 is not None and abs(z1.imag) > 1e-9) else None
    ang_l = np.angle(z1)

    def proj(z):
        """Componente da impedância aparente na direção da linha, em Ω."""
        return None if z is None else abs(z) * np.cos(np.angle(z) - ang_l)

    # --- cenários: rede completa e N-1 em torno dos dois terminais ---
    cen = [('rede completa', [], [])]
    if n1:
        vistos = set()
        for b in (rele, remoto):
            for r in _ramos_incidentes(model, b):
                eq = tuple(sorted(_equipamento(model, r, b)))
                if (bf, bt, nc) in eq or (bt, bf, nc) in eq or eq in vistos:
                    continue
                vistos.add(eq)
                cen.append((f'N-1 sem {r[0]}-{r[1]}/{r[2]}', list(eq), []))

    # --- pontos de falta: barra remota e extremidade das linhas adjacentes ---
    adj, paralelos = [], []
    for r in _ramos_incidentes(model, remoto):
        if {r[0], r[1]} == {bf, bt} and r[2] == nc:
            continue
        outro = r[1] if r[0] == remoto else r[0]
        if outro == rele:
            paralelos.append(r)          # circuito paralelo: volta ao terminal do relé
            continue
        if model.bus_kv.get(outro):                      # só linhas e trafos com barra física
            adj.append((r, outro))

    # bancos série na linha ou nas adjacentes: estado físico próprio (inserido e bypass) e
    # pontos de falta nos dois terminais do banco, antes e depois dele (C01)
    barras_viz0 = {rele, remoto} | {o for _, o in adj}
    bancos = [c for c in getattr(model, 'caps', []) if {c['bf'], c['bt']} & barras_viz0]
    for c in bancos:
        kc = (c['bf'], c['bt'], str(c.get('nc', '1')))
        cen.append((f"bypass do banco {kc[0]}-{kc[1]}/{kc[2]}", [], [kc]))
    pontos_banco = []
    for c in bancos:
        for lado in (c['bf'], c['bt']):
            if lado != rele and model.bus_kv.get(lado) and lado != remoto:
                pontos_banco.append((f"terminal {lado} do banco {c['bf']}-{c['bt']}", lado))
    medidas = {'barra remota': []}
    for nome, _ in pontos_banco:
        medidas.setdefault(nome, [])
    for r, outro in adj:
        medidas[f'fim de {r[0]}-{r[1]}/{r[2]}'] = []
    falhas = []
    for rot, drop, byp in cen:
        try:
            S = S0 if not (drop or byp) else _solver(model, drop, modo,
                                                      bypass_capacitores=byp or None)
        except Exception as ex:
            falhas.append(f'{rot}: {type(ex).__name__}')
            continue
        pontos = [('barra remota', remoto)] + [(f'fim de {r[0]}-{r[1]}/{r[2]}', o)
                                               for r, o in adj
                                               if (r[0], r[1], r[2]) not in set(drop)]
        pontos += pontos_banco
        for nome, fb in pontos:
            for k in kinds:
                try:
                    V = S.bus_voltage(fb, rele, k)
                    I = S.branch_current(fb, rele, remoto, nc, k)
                except Exception as ex:
                    falhas.append(f'{rot}, {nome}, {k}: {type(ex).__name__}')
                    continue
                if not V or not I:
                    continue
                Vk = {c: V[c] * kv / np.sqrt(3) for c in ('Va_c', 'Vb_c', 'Vc_c')}   # kV
                lac = _lacos(Vk, I['fasores'], k0)                                   # Ω
                for laco in _LACO_POR_FALTA[k]:
                    zap = lac.get(laco)
                    if zap is not None and np.isfinite(zap):
                        medidas[nome].append(dict(cenario=rot, falta=k, laco=laco,
                                                  Z=zap, Zproj=proj(zap)))

    def extremo(lista, fn):
        vals = [m for m in lista if m['Zproj'] is not None and m['Zproj'] > 0]
        return fn(vals, key=lambda m: m['Zproj']) if vals else None

    adj_min = [extremo(v, min) for n, v in medidas.items() if n.startswith('fim de')]
    adj_max = [extremo(v, max) for n, v in medidas.items() if n.startswith('fim de')]
    banco_min = [extremo(v, min) for n, v in medidas.items() if n.startswith('terminal')]
    banco_min = [x for x in banco_min if x]
    adj_min = [x for x in adj_min if x]
    adj_max = [x for x in adj_max if x]
    lim_z2_teto = min(adj_min, key=lambda m: m['Zproj']) if adj_min else None
    ref_z3 = max(adj_max, key=lambda m: m['Zproj']) if adj_max else None
    remota = medidas['barra remota']

    # --- região de carga: capacidade de emergência e tensão mínima ---
    v_min = crit.get('v_min_carga', 0.95)
    s_emerg = None
    if cenarios:
        pass
        cm = carga_maxima(cenarios, bf, bt, nc)
        if cm and cm.get('cap_emergencia_A'):
            s_emerg = np.sqrt(3) * kv * cm['cap_emergencia_A'] / 1000.0      # MVA
    z_carga = ((v_min * kv) ** 2 / s_emerg) if s_emerg else None

    # --- SIR como indicador: fonte atrás do relé, sem a linha protegida ---
    try:
        Ssir = _solver(model, [(bf, bt, nc)], 'sincronas')
        zs = Ssir.zth(rele)[0]
        sir = abs(zs * zb) / abs(z1) if zs is not None else None
    except Exception:
        sir = None

    # --- alertas: capacitor série e circuito paralelo ---
    alertas = []
    barras_viz = {rele, remoto} | {o for _, o in adj}
    caps = [c for c in getattr(model, 'caps', []) if {c['bf'], c['bt']} & barras_viz]
    if caps:
        alertas.append(f'{len(caps)} capacitor(es) série na linha ou nas adjacentes: '
                       f'avaliados com o banco inserido e em bypass; o comportamento do MOV '
                       f'e a inversão de tensão exigem estudo transitório')
        if banco_min:
            m = min(banco_min, key=lambda x: x['Zproj'])
            alertas.append(f"menor impedância aparente nos terminais de banco: "
                           f"{m['Zproj']:.2f} Ω ({m['cenario']}, {m['falta']}) — "
                           f"a zona 1 não pode alcançar esse ponto")
    mut = [m for m in model.mutuas
           if {m['bf1'], m['bt1']} == {bf, bt} or {m['bf2'], m['bt2']} == {bf, bt}]
    if mut:
        alertas.append(f'{len(mut)} acoplamento(s) mútuo(s) de sequência zero com a linha: '
                       f'circuito paralelo — avaliar compensação de mútua no laço fase-terra')
    if paralelos:
        alertas.append(f'circuito paralelo entre os mesmos terminais '
                       f'({", ".join(f"{a}-{b}/{c}" for a, b, c in paralelos)}): altera infeed e '
                       f'outfeed e exige avaliar compensação de mútua; a falta no fim do '
                       f'paralelo é a própria barra local e não entra como adjacente')
    if kr is not None and kx is not None and abs(complex(kr, kx) - k0) > 1e-3 * abs(k0 or 1):
        alertas.append('Kr/Kx diferem das partes de k0: use a forma que o IED implementa')

    # --- margens, se os alcances foram informados ---
    zonas = {}
    unid = crit.get('unidade', 'ZL')
    for zn in ('Z1', 'Z2', 'Z3', 'Z4'):
        if zn not in crit:
            continue
        alc = crit[zn] * abs(z1) if unid == 'ZL' else float(crit[zn])
        d = dict(alcance_ohm=alc, alertas=[])
        if zn == 'Z1':
            d['margem_sobrealcance'] = (abs(z1) - alc) / abs(z1)
            if alc >= abs(z1):
                d['alertas'].append('zona 1 alcança a barra remota ou além')
        if zn == 'Z2':
            d['margem_cobertura'] = (alc - abs(z1)) / abs(z1)
            if alc <= abs(z1):
                d['alertas'].append('zona 2 não cobre a linha inteira')
            if lim_z2_teto:
                d['margem_adjacentes'] = (lim_z2_teto['Zproj'] - alc) / lim_z2_teto['Zproj']
                if alc >= lim_z2_teto['Zproj']:
                    d['alertas'].append(
                        f"zona 2 alcança o fim de linha adjacente "
                        f"({lim_z2_teto['cenario']}, {lim_z2_teto['falta']})")
        if zn in ('Z3', 'Z4') and z_carga:
            d['margem_carga'] = (z_carga - alc) / z_carga
            if alc >= z_carga:
                d['alertas'].append('alcance invade a região de carga de emergência')
        d['estado'] = 'faixa_inviavel' if d['alertas'] else 'validacao_pendente'
        rtc, rtp = dados.get('rtc'), dados.get('rtp')
        d['alcance_secundario_ohm'] = para_secundario(alc, 'impedancia', rtc, rtp)
        zonas[zn] = d

    prem = _premissas_curto(S0) + [
        'impedância aparente medida laço a laço sobre o mesmo estado de solução: AG para '
        'monofásica, BC para bifásica, BC/BG/CG para bifásica-terra, AB para trifásica',
        'compensação residual com k0 complexo; Kr e Kx informados à parte',
        'cenários: rede completa e N-1 de cada equipamento em torno dos dois terminais',
        'pontos de falta: barra remota e extremidade das linhas adjacentes',
        'comparação por módulo projetado na direção da linha; a região real depende da '
        'característica do IED e não está modelada',
        'SIR como indicador de desempenho, não como critério de proibição',
    ]
    if z_carga:
        prem.append(f'região de carga: capacidade de emergência do ANAREDE e tensão '
                    f'mínima de {v_min:.2f} pu')
    faltantes = []
    if not crit or not any(z in crit for z in ('Z1', 'Z2', 'Z3', 'Z4')):
        faltantes.append('alcances das zonas (critério do usuário)')
    if not cenarios:
        faltantes.append('casos do ANAREDE (capacidade de emergência para a região de carga)')
    if not (dados.get('rtc') and dados.get('rtp')):
        faltantes.append('rtc e rtp (conversão ao secundário)')
    return dict(
        linha=(bf, bt, nc), terminal=rele, remoto=remoto, kv=kv, modo=modo,
        Z1L_ohm=z1, Z0L_ohm=z0, k0=k0, Kr=kr, Kx=kx, SIR=sir,
        limites=dict(z1_teto_ohm=abs(z1), z2_piso_ohm=abs(z1),
                     z2_teto_ohm=lim_z2_teto['Zproj'] if lim_z2_teto else None,
                     z2_teto_condicao=lim_z2_teto and f"{lim_z2_teto['cenario']}, "
                                                      f"{lim_z2_teto['falta']}",
                     z3_referencia_ohm=ref_z3['Zproj'] if ref_z3 else None,
                     z3_referencia_condicao=ref_z3 and f"{ref_z3['cenario']}, "
                                                       f"{ref_z3['falta']}",
                     z_carga_min_ohm=z_carga),
        medidas=medidas, zonas=zonas, alertas=alertas, falhas=falhas,
        premissas=prem, faltantes=faltantes,
        exportacao=dict(exportavel=False,
                        motivos=['característica do IED não modelada: resultado é insumo']),
    )


# ===================== motor de fluxo de potencia =====================

def corrente_nominal(mva, kv):
    """Corrente correspondente a uma potência aparente, em A. I = MVA·1000/(√3·kV)."""
    if not mva or not kv:
        return None
    return float(mva) * 1000.0 / (np.sqrt(3) * float(kv))


def carregamento(pwf, bf, bt, nc=None):
    """Carregamento de um circuito no cenário lido, em A, e suas capacidades.

    Devolve dict com a corrente de operação e os três limites do DLIN — normal,
    emergência e equipamento. É o dado que o .ANA não tem e que o critério do 51 de
    linha, do SOTF e do pickup do 87B exigem.
    """
    br = pwf.circuito(bf, bt, nc)
    if br is None:
        return None
    kv = pwf.bus_kv.get(bf) or pwf.bus_kv.get(bt)
    out = {
        'cap_normal_A': br.get('Cn'),
        'cap_emergencia_A': br.get('Ce'),
        'cap_equipamento_A': br.get('Cq'),
        'kv': kv,
    }
    p, q = br.get('P'), br.get('Q')
    if p is not None and q is not None and kv:
        out['corrente_A'] = corrente_nominal((p * p + q * q) ** 0.5, kv)
    return out


def tensao_barra(pwf, bus):
    """Tensão e ângulo da barra no cenário lido: (V em pu, ângulo em grau)."""
    b = pwf.barras.get(bus)
    if b is None:
        return None
    return b.get('V'), b.get('A')


def envelope_cenarios(cenarios, funcao):
    """Aplica `funcao(pwf)` a cada cenário e devolve mínimo e máximo, COM o cenário.

    `cenarios` é {nome: PwfModel}. O mínimo de curto dimensiona sensibilidade e o máximo
    dimensiona suportabilidade, e eles costumam cair em cenários DIFERENTES — por isso o
    retorno nomeia de onde veio cada extremo, em vez de devolver só os números.

    Nos casos de referência a variação dominante é diurno contra noturno (~2.200 barras
    despachadas de diferença, efeito solar), e não máxima contra mínima carga (~30).
    Varrer só níveis de carga perderia quase toda a variação.
    """
    vals = []
    for nome, pwf in (cenarios or {}).items():
        try:
            v = funcao(pwf)
        except Exception:
            continue
        if v is not None:
            vals.append((float(v), nome))
    if not vals:
        return None
    return {'min': min(vals), 'max': max(vals), 'n': len(vals)}


# ====================================================================== #
#  Fluxo por circuito, avaliado sobre o estado convergido do caso        #
# ====================================================================== #

SEM_LIMITE = 9999.0     # marcador do ANAREDE para capacidade não declarada


def _cap(v):
    """Capacidade em MVA, ou None quando ausente ou igual ao marcador de 'sem limite'."""
    if v is None or v <= 0 or v >= SEM_LIMITE:
        return None
    return float(v)


def fluxos(pwf):
    """Corrente e potência em cada circuito, nas duas extremidades, a partir do estado
    convergido do caso.

    Não resolve fluxo de potência: avalia as correntes com as tensões e ângulos que o
    ANAREDE já convergiu. Linha em modelo π com a susceptância total do circuito; trafo
    com tap na barra de origem, como é a convenção do ANAREDE.

    Devolve {(bf, bt, nc): dict} com, para cada extremidade, corrente em A, potência
    aparente em MVA, e o carregamento em relação às três capacidades declaradas.
    """
    V = {}
    for b, d in pwf.barras.items():
        # Barra desligada tira de serviço os circuitos que chegam nela, mesmo que o
        # registro do circuito não traga marca de desligado — é o que o ANAREDE faz.
        if d.get('V') is None or d.get('estado') == 'D':
            continue
        ang = np.deg2rad(d.get('A') or 0.0)
        V[b] = d['V'] * np.exp(1j * ang)
    saida = {}
    for c in pwf.circuitos:
        if c.get('estado') == 'D':
            continue
        bf, bt = c['bf'], c['bt']
        if bf not in V or bt not in V:
            continue
        R = (c.get('R') or 0.0) / 100.0
        X = (c.get('X') or 0.0) / 100.0
        z = complex(R, X)
        if abs(z) < 1e-12:
            continue
        y = 1.0 / z
        bsh = (c.get('Mvar') or 0.0) / 100.0            # susceptância total, pu
        a = c.get('Tap') or 1.0
        phs = np.deg2rad(c.get('Phs') or 0.0)
        t = a * np.exp(1j * phs)
        Vi, Vj = V[bf], V[bt]
        # tap na barra de origem: Ii = y/|t|²·Vi − y/t*·Vj ;  Ij = −y/t·Vi + y·Vj
        Ii = y / (abs(t) ** 2) * Vi - y / np.conj(t) * Vj + 1j * bsh / 2 * Vi
        Ij = -y / t * Vi + y * Vj + 1j * bsh / 2 * Vj
        Si = Vi * np.conj(Ii) * 100.0
        Sj = Vj * np.conj(Ij) * 100.0
        kvf, kvt = pwf.bus_kv.get(bf), pwf.bus_kv.get(bt)
        caps = {k: _cap(c.get(k)) for k in ('Cn', 'Ce', 'Cq')}
        s_max = max(abs(Si), abs(Sj))
        # Incerteza do fluxo pelo arredondamento do arquivo: tensão com 3 casas e ângulo
        # com ~1 casa (pior caso). Mediana de 2,3% nas linhas de 230 kV e acima no caso de
        # referência. Em chave de interligação (impedância quase nula) o fluxo não pode ser
        # obtido das tensões gravadas, e o valor é marcado como não calculável.
        incerteza = (0.0005 + np.deg2rad(0.05)) / abs(z) * 100.0 if abs(z) else None
        chave = abs(z) < 0.0005
        saida[(bf, bt, c['nc'])] = dict(
            S_de_MVA=abs(Si), S_para_MVA=abs(Sj),
            P_de_MW=Si.real, Q_de_Mvar=Si.imag,
            P_para_MW=Sj.real, Q_para_Mvar=Sj.imag,
            I_de_A=abs(Ii) * 100e3 / (np.sqrt(3) * kvf) if kvf else None,
            I_para_A=abs(Ij) * 100e3 / (np.sqrt(3) * kvt) if kvt else None,
            cap_normal_MVA=caps['Cn'], cap_emergencia_MVA=caps['Ce'],
            cap_equipamento_MVA=caps['Cq'],
            carregamento_normal=(s_max / caps['Cn']) if caps['Cn'] else None,
            carregamento_emergencia=(s_max / caps['Ce']) if caps['Ce'] else None,
            incerteza_MVA=incerteza, calculavel=not chave,
        )
    return saida


def balanco(pwf, fl=None):
    """Resíduo do balanço de potência ATIVA em cada barra: Pg − Pl − Σ P saindo, em MW.

    Num caso convergido o resíduo é da ordem da tolerância do ANAREDE. É a verificação de
    que `fluxos` está certo: se a régua de algum campo estivesse errada, o balanço não
    fecharia. Usa-se o ativo porque bancos shunt e compensadores estáticos — blocos que
    este parser não lê — mexem só no reativo.

    Devolve {barra: resíduo_MW}.
    """
    fl = fl if fl is not None else fluxos(pwf)
    sai = {}
    for (bf, bt, nc), d in fl.items():
        sai[bf] = sai.get(bf, 0.0) + d['P_de_MW']
        sai[bt] = sai.get(bt, 0.0) + d['P_para_MW']
    res = {}
    for b, d in pwf.barras.items():
        if d.get('estado') == 'D':
            continue
        res[b] = (d.get('Pg') or 0.0) - (d.get('Pl') or 0.0) - sai.get(b, 0.0)
    return res



# ====================================================================== #
#  Despacho do cenário aplicado ao curto-circuito                        #
# ====================================================================== #

def aplicar_despacho(ana, pwf, saltos=3, sem_correspondencia='manter'):
    """Cópia do caso de curto-circuito com o despacho de um cenário do ANAREDE.

    O ANAFAS representa a rede sempre completa, com todas as unidades em operação. O
    ANAREDE traz, por cenário, quais usinas estão gerando. Esta função tira do caso de
    curto as fontes que o cenário deixa paradas — e só isso: impedâncias, topologia e
    modelo de cálculo ficam intactos. O motor de curto-circuito não é alterado.

    Critério, fonte a fonte:

      * gerador de conversor (bloco DEOL): casado pelo número da barra; sai se a geração
        ativa no cenário é nula.
      * gerador síncrono cuja barra existe no fluxo: idem.
      * gerador síncrono cuja barra não existe no fluxo — terminais de gerador que o
        ANAREDE agrega: sobe pela rede, até `saltos` barras, até a primeira que tenha
        geração declarada no fluxo, e herda o estado dela.
      * sem correspondência: `sem_correspondencia='manter'` (padrão) mantém o gerador,
        que é conservador para SUPORTABILIDADE; 'retirar' o tira, que é conservador para
        SENSIBILIDADE. Os dois juntos dão a faixa de incerteza do mapeamento.

    Devolve (caso_do_cenario, relatorio). O relatório conta o que saiu, o que ficou por
    decisão e o que ficou por falta de correspondência — é o que o estudo deve declarar.
    """
    import copy
    from collections import deque

    def gera(b):
        d = pwf.barras.get(b)
        if d is None or d.get('estado') == 'D':
            return None
        return abs(d.get('Pg') or 0.0) > 1e-6

    adj = {}
    for x in ana.branches:
        adj.setdefault(x['bf'], []).append(x['bt'])
        adj.setdefault(x['bt'], []).append(x['bf'])

    def estado_por_topologia(b):
        vis = {b}
        q = deque([(b, 0)])
        while q:
            u, d = q.popleft()
            if u != b and u in pwf.barras and pwf.barras[u].get('tipo') in ('1', '2'):
                return gera(u)
            if d >= saltos:
                continue
            for v in adj.get(u, []):
                if v not in vis:
                    vis.add(v)
                    q.append((v, d + 1))
        return None

    rel = dict(sincronos_retirados=0, sincronos_mantidos=0, sincronos_sem_correspondencia=0,
               conversores_retirados=0, conversores_mantidos=0,
               conversores_sem_correspondencia=0)
    gens = []
    for g in ana.gens:
        b = g['bus']
        st = gera(b) if b in pwf.barras else estado_por_topologia(b)
        if st is None:
            rel['sincronos_sem_correspondencia'] += 1
            if sem_correspondencia == 'manter':
                gens.append(g)
        elif st:
            rel['sincronos_mantidos'] += 1
            gens.append(g)
        else:
            rel['sincronos_retirados'] += 1
    deol = {}
    for b, regs in ana.deol.items():
        st = gera(b)
        if st is None:
            rel['conversores_sem_correspondencia'] += 1
            if sem_correspondencia == 'manter':
                deol[b] = regs
        elif st:
            rel['conversores_mantidos'] += 1
            deol[b] = regs
        else:
            rel['conversores_retirados'] += 1
    M = copy.copy(ana)
    M.gens = gens
    M.deol = deol
    M.eol = set(deol)
    rel['cenario'] = getattr(pwf, 'titulo', '')
    return M, rel


def curto_por_cenario(ana, cenarios, barras, kinds=('3F', '1FT'), modo='completo',
                      caso_conferido=False):
    """Corrente de curto-circuito em cada cenário de despacho, com os extremos nomeados.

    `cenarios` é {nome: PwfModel}. Devolve, para cada barra e tipo de defeito, o MÁXIMO e o
    MÍNIMO entre os cenários, cada um com o nome do cenário em que ocorreu.

    O envelope é conservador nos dois lados. Parte dos geradores síncronos do caso de
    curto não tem correspondência no fluxo — terminais que o ANAREDE agrega —, e o estado
    deles no cenário é desconhecido. Por isso cada extremo é calculado sob a hipótese que
    o torna seguro para o seu uso:

      máximo  (suportabilidade)  com os geradores sem correspondência LIGADOS
      mínimo  (sensibilidade)    com os geradores sem correspondência DESLIGADOS

    A distância entre as duas hipóteses é a incerteza do mapeamento, e vem no retorno —
    no caso de referência chega a 8% numa barra de 500 kV.

    `caso_conferido`: se a leitura do .ANA já foi conferida contra o relatório do ANAFAS,
    os cenários herdam a conferência — são o mesmo arquivo, com fontes retiradas. Os
    valores por cenário não têm gabarito no ANAFAS, que só calcula a rede completa, e o
    método fica declarado no retorno.
    """
    pass

    def calcular(M):
        S = Solver(M, modo=modo)
        S.factor(avisar=False)
        if modo == 'completo' and S._tem_fc():
            S.liberar_completo_sem_gabarito(
                'cenário derivado de caso conferido' if caso_conferido
                else 'cenário de despacho, leitura não conferida')
        res = {}
        for b in barras:
            for k in kinds:
                try:
                    res[(b, k)] = S.fault(b, k) * 1000.0
                except Exception as ex:
                    res[(b, k)] = None
                    falhas.append((b, k, type(ex).__name__))
        return res

    falhas = []
    saida = {'despacho': {}, 'por_cenario_max': {}, 'por_cenario_min': {}, 'modo': modo,
             'metodo': ('fontes paradas no cenário do ANAREDE retiradas do caso de '
                        'curto-circuito; impedâncias e topologia inalteradas; geradores '
                        'sem correspondência ligados para o máximo e desligados para o '
                        'mínimo'),
             'conferido_contra_anafas': False}
    for nome, pwf in cenarios.items():
        M_max, rel = aplicar_despacho(ana, pwf, sem_correspondencia='manter')
        M_min, _ = aplicar_despacho(ana, pwf, sem_correspondencia='retirar')
        saida['despacho'][nome] = rel
        saida['por_cenario_max'][nome] = calcular(M_max)
        saida['por_cenario_min'][nome] = calcular(M_min)
    extremos = {}
    for b in barras:
        for k in kinds:
            mx = [(r[(b, k)], n) for n, r in saida['por_cenario_max'].items()
                  if r.get((b, k)) is not None]
            mn = [(r[(b, k)], n) for n, r in saida['por_cenario_min'].items()
                  if r.get((b, k)) is not None]
            if mx and mn:
                vmax, vmin = max(mx), min(mn)
                faixa = [abs(saida['por_cenario_max'][n][(b, k)] -
                              saida['por_cenario_min'][n][(b, k)])
                         / saida['por_cenario_max'][n][(b, k)] * 100
                         for n in saida['por_cenario_max']
                         if saida['por_cenario_max'][n].get((b, k))
                         and saida['por_cenario_min'][n].get((b, k))]
                extremos[(b, k)] = {'max': vmax, 'min': vmin,
                                    'incerteza_mapeamento_pct': max(faixa) if faixa else None}
    saida['extremos'] = extremos
    # falha não some: entra no denominador, e um extremo calculado sem todos os cenários
    # não é declarado completo
    saida['falhas'] = falhas
    saida['cenarios_avaliados'] = len(cenarios) * 2
    saida['completo'] = not falhas
    saida['premissas'] = [
        'tensão pré-falta de 1,0 pu, sem carregamento prévio',
        f'modo {modo}',
        'despacho de cada cenário do ANAREDE aplicado ao caso do ANAFAS: fontes com '
        'geração nula retiradas; impedâncias e topologia inalteradas',
        'geradores síncronos fora do fluxo casados subindo até três barras pela rede',
        'geradores sem correspondência: ligados no máximo, desligados no mínimo',
        'despacho binário por usina (ligada ou parada), sem número de unidades',
        'valores por cenário sem gabarito no ANAFAS, que calcula só a rede completa']
    return saida


def carga_maxima(cenarios, bf, bt, nc=None):
    """Carga máxima de um circuito, a partir das bases do ANAREDE.

    Devolve dict em A com as três capacidades declaradas (exatas — não sofrem
    arredondamento) e o maior fluxo observado entre os cenários, com o nome do cenário.

    `carga_max_A` é o valor que os critérios de proteção usam: a capacidade de
    EMERGÊNCIA, e na falta dela a normal. Em regime de emergência o equipamento não pode
    ser desligado indevidamente pela proteção, então todo pickup que dependa de carga
    precisa ficar acima desse limite. A capacidade normal é sempre menor que a de
    emergência e não serve como referência de pickup.

    O fluxo observado vem ao lado para comparação — é uma fotografia dos cenários, não um
    limite.
    """
    caps = {}
    obs = []
    kv = None
    for nome, pwf in cenarios.items():
        c = pwf.circuito(bf, bt, nc)
        if c is None:
            continue
        kv = kv or pwf.bus_kv.get(bf) or pwf.bus_kv.get(bt)
        for k in ('Cn', 'Ce', 'Cq'):
            v = _cap(c.get(k))
            if v:
                caps[k] = max(caps.get(k, 0), v)
        fl = fluxos(pwf)
        f = fl.get((c['bf'], c['bt'], c['nc']))
        if f and f.get('calculavel'):
            s = max(f['S_de_MVA'], f['S_para_MVA'])
            obs.append((s, nome))
    if not kv:
        return None
    a = lambda mva: corrente_nominal(mva, kv) if mva else None
    if caps.get('Ce'):
        ref, origem = caps['Ce'], 'capacidade de emergência'
    elif caps.get('Cn'):
        ref, origem = caps['Cn'], 'capacidade normal (emergência não declarada)'
    else:
        ref, origem = None, None
    out = dict(kv=kv,
               cap_normal_A=a(caps.get('Cn')), cap_emergencia_A=a(caps.get('Ce')),
               cap_equipamento_A=a(caps.get('Cq')),
               carga_max_A=a(ref), origem=origem)
    if obs:
        s, nome = max(obs)
        out['fluxo_max_observado_A'] = a(s)
        out['cenario_do_fluxo_max'] = nome
    out['premissas'] = [f'carga máxima: {origem}' if origem else 'carga máxima não declarada',
                        'capacidades lidas do ANAREDE (exatas); fluxo observado é estimativa '
                        'sobre tensões gravadas com três casas']
    return out


# ===================== curvas de tempo inverso =====================

# (A, B, C) da forma t = TMS·[A/((I/Is)^B − 1) + C]
CURVAS = {
    'IEC': {
        'NI':  (0.14,  0.02, 0.0),      # normalmente inversa
        'MI':  (13.5,  1.0,  0.0),      # muito inversa   <- padrão dos estudos SGBH
        'EI':  (80.0,  2.0,  0.0),      # extremamente inversa
        'LTI': (120.0, 1.0,  0.0),      # tempo longo inversa
    },
    'IEEE': {
        'MODINV': (0.0515, 0.02, 0.114),   # moderadamente inversa
        'MI':     (19.61,  2.0,  0.491),   # muito inversa
        'EI':     (28.2,   2.0,  0.1217),  # extremamente inversa
    },
}

NORMA_PADRAO = 'IEC'
CURVA_PADRAO = 'MI'

_NOMES = {
    'NI': 'normalmente inversa', 'MI': 'muito inversa',
    'EI': 'extremamente inversa', 'LTI': 'tempo longo inversa',
    'MODINV': 'moderadamente inversa',
}


def constantes(curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """Devolve (A, B, C) da curva. Levanta ValueError com as opções válidas."""
    n = (norma or NORMA_PADRAO).upper()
    if n not in CURVAS:
        raise ValueError(f"norma deve ser uma de {sorted(CURVAS)}, recebido {norma!r}")
    c = (curva or CURVA_PADRAO).upper()
    if c not in CURVAS[n]:
        raise ValueError(f"curva {curva!r} não existe em {n}; disponíveis: "
                         f"{sorted(CURVAS[n])}")
    return CURVAS[n][c]


def tempo(I, Is, tms=1.0, curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """Tempo de operação, em segundos, para corrente `I` e pickup `Is` (mesma unidade).

    Devolve `inf` quando I ≤ Is: abaixo do pickup a unidade não opera. Aceita escalar ou
    array de correntes.
    """
    A, B, C = constantes(curva, norma)
    k = _FATOR_IED.get((norma or NORMA_PADRAO).upper(), 1.0)
    m = np.asarray(I, dtype=float) / float(Is)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = k * tms * (A / (m ** B - 1.0) + C)
        t = np.where(m > 1.0, t, np.inf)
    return float(t) if np.ndim(t) == 0 else t


def tms_para_tempo(I, Is, t_alvo, curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """TMS que produz `t_alvo` na corrente `I`. É o inverso de `tempo`.

    Usado para ajustar o 51 de linha ao tempo exigido pela coordenação com a zona 2.
    """
    A, B, C = constantes(curva, norma)
    m = float(I) / float(Is)
    if m <= 1.0:
        raise ValueError(f"I/Is = {m:.3f} não supera o pickup: a unidade não operaria")
    k = _FATOR_IED.get((norma or NORMA_PADRAO).upper(), 1.0)
    base = k * (A / (m ** B - 1.0) + C)
    if base <= 0:
        raise ValueError("curva degenerada para esta relação I/Is")
    return float(t_alvo) / base


def descreve(curva=CURVA_PADRAO, norma=NORMA_PADRAO):
    """Rótulo para relatório, com a norma explícita — ela nunca deve ficar implícita."""
    A, B, C = constantes(curva, norma)
    n = (norma or NORMA_PADRAO).upper(); c = (curva or CURVA_PADRAO).upper()
    return f"{n} {_NOMES.get(c, c)} (A={A}, B={B}, C={C})"


_FATOR_IED = {}
_FONTE_IED = {}


def curva_do_ied(fabricante, modelo, nome, A, B, C, fonte, secao, revisao, fator_td=1.0):
    """Registra a curva documentada de um IED: t = fator_td · TD · [A/((I/Is)^B − 1) + C].

    Exige fonte, seção e revisão do manual: curva sem documento não é usada para ajuste.
    Devolve (curva, norma) a passar em `tempo`, com norma = 'IED:<FABRICANTE>:<MODELO>'.
    """
    for campo, v in (('fonte', fonte), ('secao', secao), ('revisao', revisao)):
        if not v:
            raise ValueError(f"curva de IED sem {campo}: registro recusado")
    norma = f"IED:{fabricante}:{modelo}".upper()
    CURVAS.setdefault(norma, {})[nome.upper()] = (A, B, C)
    _FATOR_IED[norma] = float(fator_td)
    _FONTE_IED[(norma, nome.upper())] = dict(fonte=fonte, secao=secao, revisao=revisao)
    return nome.upper(), norma


# ===================== Submodulo 2.11 =====================

# item 4.x — funções exigidas por componente. (código, descrição, item do submódulo)
FUNCOES = {
    'linha': [
        ('21/21N', 'distância para faltas entre fases e fase-terra, temporizadores independentes por zona', '4.2.1.2(a)'),
        ('67N/67Q', 'sobrecorrente direcional residual e/ou de sequência negativa, com unidades instantânea e temporizada', '4.2.1.2(b)'),
        ('LPP',     'lógica de detecção de perda de potencial, para bloqueio e alarme', '4.2.1.2(c)'),
        ('SOTF',    'detecção de falta durante a energização da LT (switch onto fault)', '4.2.1.2(d)'),
        ('59',      'sobretensão com elementos instantâneos e temporizados independentes nas três fases', '4.2.1.2(e)'),
        ('68/78',   'bloqueio por oscilação de potência (68 OSB), disparo (68 OST) e perda de sincronismo (78 OST)', '4.2.1.2(f)'),
        ('79/25',   'dois esquemas de religamento automático e verificação de sincronismo, redundantes', '4.2.2.1'),
    ],
    'transformador': [
        ('87',      'diferencial percentual por fase, com restrição ou bloqueio para inrush e sobreexcitação', '4.4.1(a)(1)'),
        ('50/51',   'sobrecorrente instantânea e temporizada de fase, vinculada a CADA enrolamento', '4.4.1(a)(2)'),
        ('50/51R',  'sobrecorrente instantânea e temporizada residual, vinculada a CADA enrolamento', '4.4.1(a)(2)'),
        ('50/51N',  'sobrecorrente de neutro, vinculada a CADA ponto de aterramento', '4.4.1(a)(3)'),
        ('59G',     'sobretensão de sequência zero no terciário em delta, para alarme de falta à terra', '4.4.1(a)(4)'),
        ('87N',     'diferencial de terra restrita, vinculada a CADA ponto de aterramento', '4.4.1(a)(5)'),
        ('63/20',   'detecção de gás ou aumento de pressão interna, inclusive do comutador', '4.4.1(b)(1)'),
        ('26/49',   'sobretemperatura de óleo e de enrolamento, dois níveis cada', '4.4.1(b)(2,3)'),
    ],
    'reator': [
        ('87',      'diferencial por fase, com bloqueio ou restrição para inrush e sobreexcitação', '4.5.1(a)(1)'),
        ('87R',     'diferencial de terra restrita', '4.5.1(a)(2)'),
        ('50/51',   'sobrecorrente instantânea e temporizada de fase, do lado da LT ou da barra onde o reator está conectado', '4.5.1(a)(3)'),
        ('50/51R',  'sobrecorrente instantânea e temporizada residual, do mesmo lado', '4.5.1(a)(3)'),
        ('50/51R-N','sobrecorrente residual do lado do neutro, ou 50/51N', '4.5.1(a)(4)'),
        ('63/20',   'detecção de gás ou pressão interna', '4.5.1(b)(1)'),
        ('26/49',   'sobretemperatura de óleo e de enrolamento, dois níveis cada', '4.5.1(b)(2,3)'),
    ],
    'barra': [
        ('87B',     'princípio diferencial ou comparação de fase, por fase; exceto arranjo em anel', '4.6.1'),
    ],
    'disjuntor': [
        ('50BF',    'detecção de corrente do esquema de falha de disjuntor', '4.7.3(a)'),
        ('62BF',    'temporização do esquema de falha de disjuntor', '4.7.3(b)'),
    ],
}

# item 4.1.2 e 4.7.2 — tempos máximos, em ms
TEMPOS = {
    'eliminacao_acima_230kV': (70, '4.1.2(a)', 'tempo total de eliminação, defeito sólido sem falha de disjuntor'),
    'eliminacao_230kV':       (90, '4.1.2(b)', 'idem, em 230 kV'),
    'falha_disjuntor':        (250, '4.7.2', 'tempo total pelo esquema de falha de disjuntor, incluindo relés auxiliares e abertura'),
}


def tempo_maximo(kv, falha_disjuntor=False):
    """Tempo máximo de eliminação em ms, conforme o item 4.1.2 (ou 4.7.2)."""
    if falha_disjuntor:
        return TEMPOS['falha_disjuntor'][0]
    return TEMPOS['eliminacao_230kV'][0] if kv <= 230 else TEMPOS['eliminacao_acima_230kV'][0]


def funcoes_exigidas(tipo):
    """Funções que o Submódulo 2.11 exige para o componente."""
    if tipo not in FUNCOES:
        raise ValueError(f"tipo deve ser um de {sorted(FUNCOES)}, recebido {tipo!r}")
    return list(FUNCOES[tipo])


def exige_stub(arranjo):
    """Stub Bus Protection é exigida em disjuntor e meio, barra dupla com disjuntor duplo
    e anel — item 4.1.6, para falta no trecho que permanece energizado com a seccionadora
    da função de transmissão aberta e os disjuntores fechados."""
    a = (arranjo or '').lower()
    return any(k in a for k in ('disjuntor e meio', 'disjuntor duplo', 'anel'))


def verificar_escopo(tipo, previstas):
    """Compara as funções previstas no estudo com as exigidas. Devolve as que faltam.

    Verificação documental, não de ajuste: diz o que o Submódulo 2.11 exige e o estudo
    não contempla.
    """
    tem = {p.upper().replace(' ', '') for p in (previstas or [])}
    falta = []
    for cod, desc, item in funcoes_exigidas(tipo):
        alternativas = {c.upper().replace(' ', '') for c in cod.replace('/', ' ').split()}
        alternativas.add(cod.upper().replace(' ', ''))
        if not (alternativas & tem):
            falta.append((cod, desc, item))
    return falta


# ===================== dados externos =====================

# chave -> (rótulo, unidade, o que bloqueia se faltar)
CATALOGO = {
    'carga_max_lt':     ('Carga máxima da LT', 'A ou MVA',
                         'pickup do 51 de linha (120% da carga máxima). O .ANA traz a '
                         'potência NOMINAL no campo MVA, que não é a carga máxima '
                         'operativa — confirme se serve ao critério'),
    'in_lt':            ('Corrente nominal da LT', 'A',
                         'limite inferior do SOTF'),
    'rtc':              ('Relação do TC do vão', '-',
                         'conversão para secundário e limite inferior do 67NT'),
    'in_tc':            ('Corrente nominal primária do TC', 'A',
                         'pickup do 67NT (10% de In do TC)'),
    'mva_trafo':        ('Potência nominal do transformador (placa)', 'MVA',
                         'pickup do 51 do trafo (150% da nominal) e estimativa de inrush'),
    'inrush':           ('Corrente de inrush', 'A ou múltiplo de In',
                         'limite inferior do 50 do trafo'),
    'mva_reator':       ('Potência nominal do reator', 'Mvar',
                         'corrente nominal de referência do reator'),
    'icc_disj':         ('Capacidade de interrupção do disjuntor', 'kA',
                         'verificação de suportabilidade'),
    'ajustes_vizinhos': ('Ajustes dos IEDs adjacentes', '-',
                         'verificação de coordenação com os elementos vizinhos'),
    'zf_sotf':          ('Impedância de falta para o critério do SOTF', 'ohm ou pu',
                         'limite superior do SOTF (80% do Icc mínimo remoto)'),
}

# o que cada tipo de estudo exige
EXIGIDOS = {
    'linha':          ('carga_max_lt', 'in_lt', 'rtc', 'in_tc', 'zf_sotf',
                       'icc_disj', 'ajustes_vizinhos'),
    'transformador':  ('mva_trafo', 'inrush', 'rtc', 'in_tc', 'icc_disj',
                       'ajustes_vizinhos'),
    'reator':         ('mva_reator', 'rtc', 'in_tc', 'icc_disj'),
    'barra':          ('rtc', 'in_tc', 'icc_disj'),
}


def da_base(model, bf, bt, nc):
    """Extrai da base o que ela puder fornecer para o elemento (bf,bt,nc).

    O .ANA traz a potência nominal no campo MVA do DCIR — a única grandeza de capacidade
    do arquivo. Onde estiver preenchida, dispensa o usuário de informar a nominal, e a
    corrente nominal sai dela: In = MVA·1000 / (√3 · kV).

    Não há carregamento MÁXIMO no arquivo: o campo é potência nominal, e o critério do 51
    de linha pede a carga máxima operativa, que costuma diferir. Quando só o MVA existe,
    o valor é devolvido com a chave `mva_nominal` e cabe a quem usa decidir se serve.
    """
    achado = {}
    for br in model.branches:
        if (br['bf'], br['bt'], str(br['nc'])) != (bf, bt, str(nc)):
            continue
        mva = br.get('MVA')
        if mva:
            kv = model.bus_kv.get(br['bf'], 0) or model.bus_kv.get(br['bt'], 0)
            achado['mva_nominal'] = mva
            if kv:
                achado['in_nominal'] = mva * 1000.0 / (3 ** 0.5 * kv)
            if br['tipo'] == 'L':
                achado['in_lt'] = achado.get('in_nominal')
            else:
                achado['mva_trafo'] = mva
        break
    return achado


def faltantes(tipo, fornecidos=None, model=None, elemento=None):
    """Lista o que falta para parametrizar `tipo`.

    `fornecidos` é o dict do usuário. Se `model` e `elemento=(bf,bt,nc)` forem dados, o
    que a base puder fornecer é considerado presente — não se pede ao usuário um dado que
    o arquivo já traz.
    """
    if tipo not in EXIGIDOS:
        raise ValueError(f"tipo deve ser um de {sorted(EXIGIDOS)}, recebido {tipo!r}")
    tem = dict(fornecidos or {})
    if model is not None and elemento is not None:
        for k, v in da_base(model, *elemento).items():
            tem.setdefault(k, v)
    return [k for k in EXIGIDOS[tipo] if tem.get(k) in (None, '')]


def RELATORIO(chaves, tipo=None):
    """Texto pedindo os dados que faltam, com o que cada um bloqueia."""
    if not chaves:
        return "Todos os dados externos necessários foram fornecidos."
    cab = (f"Faltam {len(chaves)} dado(s) para parametrizar"
           + (f" {tipo}" if tipo else "") + ". O .ANA não os contém:\n")
    linhas = []
    for k in chaves:
        rot, uni, bloq = CATALOGO[k]
        linhas.append(f"  {rot} [{uni}]\n      necessário para: {bloq}")
    return cab + "\n".join(linhas) + (
        "\n\nO cálculo de curto-circuito não depende destes dados e segue normalmente.")


# ===================== orientação para agentes =====================

_ORIENTACAO = """
═══════════════════════════════════════════════════════════════════════════════════════
LINCC — guia de modos, tolerância e limitações conhecidas
═══════════════════════════════════════════════════════════════════════════════════════

0. ORGANIZAÇÃO

   Dois parsers e três motores, em arquivos separados:

       parser_anafas   base de curto-circuito (.ANA)    -> AnaModel
       parser_anarede  base de fluxo de potência (.PWF) -> PwfModel
       solver          motor de CURTO-CIRCUITO
       protecao        motor de PROTEÇÃO
       fluxo           motor de FLUXO DE POTÊNCIA

   A dependência corre numa direção só: proteção usa o solver, o solver não conhece
   proteção. O cálculo de curto é validado barra a barra contra o ANAFAS e não muda
   porque um critério de proteção mudou. Detalhes em docs/arquitetura.md.

1. OS DOIS MODOS

   S.fault(bus, kind)                    'completo' (PADRÃO): inclui o bloco DEOL.
   S.fault(bus, kind, modo='sincronas')  Thévenin puro, SEM conversores.

   Validar cada um contra a seção certa do relatório do ANAFAS:
       sincronas -> 'RELATORIO DE DADOS DE CURTO-CIRCUITO'   (MVA)
       completo  -> 'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO'  (kA)
   Comparar `fault` com a seção de níveis reprova função correta: a seção de níveis
   inclui os conversores e o Thévenin não.

2. COMO ESCOLHER A TOLERÂNCIA

   `validar_completo(niveis, limite=X)` só libera o modo se o erro máximo ficar dentro
   de X%. No caso de referência (BR2812PI, 828 barras com conversor próximo):

       tolerância    dentro     fora
          0,1%        96,2%      31
          0,5%        99,5%       4
          1,0%       100,0%       0     <- recomendado, e o caso de referência passa

   Mediana 0,019%, p95 0,067%, máximo 0,920%, sobre as 817 barras que convergem entre as
   828 com conversor próximo. Mantenha 1%: é o critério que o caso de referência atende
   sem exclusões, e apertar para 0,5% rejeitaria quatro barras por margem numérica.

   O parâmetro `ignorar` continua disponível para o caso de um horizonte novo trazer
   divergência documentada — as excluídas seguem no relatório, marcadas:

       selo = S.validar_completo(niveis, limite=1.0, ignorar=(...))

3. VALIDAR UM CASO NOVO É OBRIGATÓRIO

   O parser lê o FORMATO, não um caso específico. Um tipo de registro que não apareça no
   caso de referência é ignorado em silêncio: o número sai, e sai errado. Antes de usar
   um caso que você não conferiu:

       python examples/validar_caso.py CASO.ANA RELATORIO.LST
       S.conciliar(z1_ref, z0_ref)      # Z1 e Z0 barra a barra

   Erro DISPERSO e pequeno é quantização do relatório. Erro CONCENTRADO numa classe de
   barras (todas de uma tensão, ou todas com certo equipamento) é regra de leitura errada.

4. LIMITAÇÕES CONHECIDAS DO MODO COMPLETO

   a) Não convergência. Cerca de 0,5% das barras esgotam as iterações e levantam
      RuntimeError em vez de devolver valor. É proposital: valor derivado de iteração
      não convergida não deve entrar em estudo.

   b) Nenhum resíduo material conhecido no caso de referência, nos quatro tipos de
      defeito. Trifásica e bifásica-terra: 100,000% das barras que convergem abaixo de 1%.
      Monofásica: 100,000% das barras com corrente acima de 0,5 kA, mediana 0,012%.

      Ao avaliar a monofásica em barra de parque, filtre por corrente com significado
      físico: 91% dessas barras têm corrente de referência abaixo de 0,05 kA, porque o
      transformador do parque é delta e a sequência zero não passa. Sobre 40 A, uma
      diferença de 5 A aparece como "12% de erro" em estatística agregada.

   c) Capacitância de linha (charging). Existe como opção, `Solver(M, charging=True)`,
      mas fica DESLIGADA por padrão: o gabarito de impedância de barra do ANAFAS não a
      inclui, e ligá-la derruba Z1 de 100,000% para 50,4%. O cálculo de falta com
      terminal aberto do ANAFAS, esse sim, a inclui — daí `line_end_open` errar 4,11% em
      falta trifásica contra 0,41% na monofásica. Conservador para sensibilidade, não
      conservador para dimensionamento. Ligar a opção NÃO corrige esse desvio, porque a
      função remove a linha e a capacitância dela sai junto: a correção pede modelar o
      trecho como stub pendurado, e está pendente.

   c) Faltas desequilibradas no modo completo usam a tensão equivalente do estado
      convergido. O conversor contribui só em sequência positiva (manual, item 2.8.3).

5. LIMITAÇÕES GERAIS

   - Falta interna rigorosa de enrolamento exige distribuição de espiras do fabricante.
     `winding_ground_fault` é triagem: a FORMA da curva é confiável, os absolutos não.
   - Falta intermediária em linha com acoplamento mútuo é aproximada; o retorno traz
     `mutua_aprox`.
   - A base não tem relação de TC, ajuste de IED nem placa. As correntes saem em kA
     PRIMÁRIOS; com TC, a corrente de base do estudo é a nominal primária do TC.
   - Elos HVDC back-to-back são bloqueados: não há caminho de curto entre os dois lados.
   - Inrush não sai da base — é transitório de energização, vem de guia normativo e placa.

6. MODELO DE INJEÇÃO (para quem for auditar)

   Curva do conversor conforme ONS, Procedimentos de Rede, Submódulo 2.10, item 5.8 e
   Figura 14: corrente reativa adicional abaixo de 85% da tensão de sequência positiva,
   saturando no ajuste padrão V1 = 0,5 pu. Coincide com VP1 e VP2 do registro DEOL.
   `Imax` é POR UNIDADE, multiplicado por NOP (manual: "3600 A x 25 unidades = 90 kA"),
   e é ELE que dá a escala absoluta da injeção: a curva é normalizada (ΔIq/In de 0 a 1
   entre VP2 e VP1) mas o valor injetado é `frac × Imax`. Onde o campo MVA está
   preenchido, In = MVA/(√3·kV) fica ABAIXO de Imax — razão 1,50 no caso de referência —
   e escalar por In subestima a injeção em exatamente Imax/In. Onde MVA está ausente o
   manual manda tomar In = Imax e as duas leituras coincidem, o que explica o desvio
   aparecer só nas poucas barras com MVA declarado.
   Solução por Newton com o conversor linearizado como equivalente Norton (Haddadi,
   Farantatos & Kocar, arXiv:2411.12006) — a iteração de ponto fixo com fonte de corrente
   ideal cai em ciclo limite e não converge.

   REFERÊNCIA DE ÂNGULO, DECIDIDA POR FONTE. Cada gerador resolve com o ângulo da PRÓPRIA
   tensão convergida quando essa equação tem solução, e usa a tensão PRÉ-FALTA só quando
   não tem — condição que ocorre com a fonte eletricamente colada ao ponto de falta, onde
   Vth ≈ 0 e a equação exigiria ang(Zjj) = 90°. O ANAFAS declara qual usou no rótulo da
   fonte, em relatório de contribuições: 'FON.CORRENTE' contra 'FON.COR.Vpre'. Aplicar o
   fallback ao CONJUNTO, e não à fonte que precisa dele, produz erro de +29% nas barras
   de complexo com reatância negativa encadeada.
"""


def orientacao(imprimir=True):
    """Guia de uso: os dois modos, como escolher a tolerância e o que são as limitações.

    Escrito para quem não acompanhou o desenvolvimento — inclusive agentes de IA operando
    o motor a partir do código. Devolve o texto; com `imprimir=False`, apenas retorna.
    """
    if imprimir:
        print(_ORIENTACAO)
    return _ORIENTACAO


# ===================== submódulos como espaços de nome =====================
import types as _types
curvas = _types.SimpleNamespace(CURVAS=CURVAS, CURVA_PADRAO=CURVA_PADRAO, NORMA_PADRAO=NORMA_PADRAO, constantes=constantes, curva_do_ied=curva_do_ied, descreve=descreve, tempo=tempo, tms_para_tempo=tms_para_tempo)
sm211 = _types.SimpleNamespace(FUNCOES=FUNCOES, TEMPOS=TEMPOS, exige_stub=exige_stub, funcoes_exigidas=funcoes_exigidas, tempo_maximo=tempo_maximo, verificar_escopo=verificar_escopo)
dados_externos = _types.SimpleNamespace(CATALOGO=CATALOGO, EXIGIDOS=EXIGIDOS, RELATORIO=RELATORIO, da_base=da_base, faltantes=faltantes)
fluxo = _types.SimpleNamespace(SEM_LIMITE=SEM_LIMITE, aplicar_despacho=aplicar_despacho, balanco=balanco, carga_maxima=carga_maxima, carregamento=carregamento, corrente_nominal=corrente_nominal, curto_por_cenario=curto_por_cenario, envelope_cenarios=envelope_cenarios, fluxos=fluxos, tensao_barra=tensao_barra)

__all__ = ['# parsers     "AnaModel', 'PwfModel', 'conciliar_bases', 'ler_relatorio', 'niveis_kA', 'impedancias_pu', '# motor de curto-circuito     "Solver', 'branches_at', '# motor de proteção     "recomposicao_87b', 'envelope_contribuicoes', 'tabela_envelope', 'impacto_entrada', 'relatorio_curto', 'relatorio_protecao', 'ajuste_sobrecorrente', 'CRITERIOS_SOBRECORRENTE', 'estudo_barra', 'CRITERIOS_BARRA', 'SLOPE_87B_POR_FABRICANTE', 'estudo_distancia', 'para_secundario', 'estudo_87L', 'quantizar', '# motor de fluxo de potência     "fluxo', '# apoio     "curvas', 'tempo', 'tms_para_tempo', 'CURVAS', 'dados_externos', 'sm211', 'orientacao', 'SB', 'num', 'zfin', 'zn3']
