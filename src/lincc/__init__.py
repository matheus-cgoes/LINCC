"""LINCC — Linguagem Natural em Curto-Circuito.

Motor de curto-circuito para sistemas de transmissão: lê casos em formato .ANA, monta as
redes de sequência positiva e zero e calcula equivalentes de Thévenin e correntes de falta
por fatoração LU esparsa.

NÃO substitui ferramenta homologada. Ver README para isenção de responsabilidade.

═══════════════════════════════════════════════════════════════════════════════════════
LEIA ANTES DE USAR — dois modos, e a escolha muda o resultado
═══════════════════════════════════════════════════════════════════════════════════════

    M = AnaModel("caso.ANA");  S = Solver(M);  S.factor()

    S.fault(bus, kind)                     modo 'sincronas' (padrão)
    S.fault(bus, kind, modo='completo')    inclui geradores de conversor pleno

`sincronas` é Thévenin puro da Ybus e NÃO inclui eólicas e fotovoltaicas conectadas por
conversor (bloco DEOL). `completo` inclui. Perto dessas usinas a diferença passa de 40% —
não é refinamento, é outra resposta.

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

O modo `completo` vem BLOQUEADO. Libere validando contra o próprio caso:

    selo = S.validar_completo(niveis_kA, limite=1.0)     # {barra: corrente_kA}

Chame `lincc.orientacao()` para o guia completo de tolerância e limitações conhecidas.
"""

from ._base import SB, num, zfin, zn3
from .model import AnaModel
from .solver import Solver, branches_at, recomposicao_87b

__version__ = "0.2.0"
__all__ = ["AnaModel", "Solver", "branches_at", "recomposicao_87b",
           "orientacao", "SB", "num", "zfin", "zn3"]

_ORIENTACAO = """
═══════════════════════════════════════════════════════════════════════════════════════
LINCC — guia de modos, tolerância e limitações conhecidas
═══════════════════════════════════════════════════════════════════════════════════════

1. OS DOIS MODOS

   S.fault(bus, kind)                    'sincronas': Thévenin puro, SEM conversores.
   S.fault(bus, kind, modo='completo')   inclui as injeções do bloco DEOL.

   Validar cada um contra a seção certa do relatório do ANAFAS:
       sincronas -> 'RELATORIO DE DADOS DE CURTO-CIRCUITO'   (MVA)
       completo  -> 'RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO'  (kA)
   Comparar `fault` com a seção de níveis reprova função correta: a seção de níveis
   inclui os conversores e o Thévenin não.

2. COMO ESCOLHER A TOLERÂNCIA

   `validar_completo(niveis, limite=X)` só libera o modo se o erro máximo ficar dentro
   de X%. No caso de referência (BR2812PI, 828 barras com conversor próximo):

       tolerância    dentro     fora
          0,5%       98,16%      15
          1,0%       98,53%      12     <- recomendado
          3,0%       99,39%       5
          5,0%       99,51%       4
         20,0%       99,51%       4     <- não muda: são sempre as mesmas 4
         30,0%      100,00%       0

   Mediana 0,020%, p90 0,055%. Entre 5% e 20% o número não muda porque restam as mesmas
   quatro barras de um cluster conhecido (item 4). Afrouxar até 30% para acomodá-las
   troca um bloqueio honesto por um número sem valor nas outras 813.

   O caminho correto é manter o critério e excluir explicitamente o que é divergência
   documentada — as excluídas continuam no relatório, marcadas:

       selo = S.validar_completo(niveis, limite=1.0,
                                 ignorar=(7785, 46047, 7786, 46050))

   Por aplicação: 3% com essas quatro excluídas é defensável para suportabilidade de
   disjuntor e esforços, onde o erro é conservador e a margem de placa é maior. Para
   sensibilidade, ICC_MIN e pickup de 51N, mantenha 1% — e nas barras excluídas use o
   modo `sincronas`, declarando isso no estudo.

3. VALIDAR UM CASO NOVO É OBRIGATÓRIO

   O parser lê o FORMATO, não um caso específico. Um tipo de registro que não apareça no
   caso de referência é ignorado em silêncio: o número sai, e sai errado. Antes de usar
   um caso que você não conferiu:

       python examples/validar_caso.py CASO.ANA RELATORIO.LST
       S.conciliar(z1_ref, z0_ref)      # Z1 e Z0 barra a barra

   Erro DISPERSO e pequeno é quantização do relatório. Erro CONCENTRADO numa classe de
   barras (todas de uma tensão, ou todas com certo equipamento) é regra de leitura errada.

4. LIMITAÇÕES CONHECIDAS DO MODO COMPLETO

   a) Cluster de conversor com fator de distribuição próximo de 1. Quatro barras de
      manobra interna de um complexo fotovoltaico em 34,5 kV (7785, 46047, 7786, 46050
      no caso de referência) divergem +20% a +29%. A injeção está certa — módulo, ângulo
      e curva conferem com o ANAFAS até a quarta casa — mas a rede local tem três
      reatâncias negativas encadeadas e a impedância de transferência supera a de
      Thévenin. Cinco hipóteses foram testadas e refutadas por teste A/B global. Nessas
      barras, use `sincronas` e declare.

   b) Não convergência. Cerca de 0,5% das barras esgotam as iterações e levantam
      RuntimeError em vez de devolver valor. É proposital: valor derivado de iteração
      não convergida não deve entrar em estudo.

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
   `Imax` é POR UNIDADE, multiplicado por NOP (manual: "3600 A x 25 unidades = 90 kA").
   Solução por Newton com o conversor linearizado como equivalente Norton (Haddadi,
   Farantatos & Kocar, arXiv:2411.12006) — a iteração de ponto fixo com fonte de corrente
   ideal cai em ciclo limite e não converge.
"""


def orientacao(imprimir=True):
    """Guia de uso: os dois modos, como escolher a tolerância e o que são as limitações.

    Escrito para quem não acompanhou o desenvolvimento — inclusive agentes de IA operando
    o motor a partir do código. Devolve o texto; com `imprimir=False`, apenas retorna.
    """
    if imprimir:
        print(_ORIENTACAO)
    return _ORIENTACAO
