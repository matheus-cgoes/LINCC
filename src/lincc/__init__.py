"""LINCC — Linguagem Natural em Curto-Circuito.

Motor de curto-circuito para sistemas de transmissão: lê casos em formato .ANA, monta as
redes de sequência positiva e zero e calcula equivalentes de Thévenin e correntes de falta
por fatoração LU esparsa.

NÃO substitui ferramenta homologada. Ver README para isenção de responsabilidade.

═══════════════════════════════════════════════════════════════════════════════════════
LEIA ANTES DE USAR — dois modos, e a escolha muda o resultado
═══════════════════════════════════════════════════════════════════════════════════════

    M = AnaModel("caso.ANA");  S = Solver(M);  S.factor()

    S.fault(bus, kind)                     modo 'completo' (PADRÃO)
    S.fault(bus, kind, modo='sincronas')   Thévenin puro, sem conversores

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

   b) Nenhum resíduo material conhecido no caso de referência: todas as barras que
      convergem ficam abaixo de 1%, com máximo de 0,92%.

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
