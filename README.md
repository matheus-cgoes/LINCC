# LINCC — Linguagem Natural em Curto-Circuito

Ferramenta de cálculo para estudos de transmissão, em Python. Três motores independentes
sobre dois parsers:

| Módulo | Papel |
|---|---|
| `parser_anafas` | lê a base de curto-circuito (`.ANA`) |
| `parser_anarede` | lê a base de fluxo de potência (`.PWF`) |
| `solver` | **motor de curto-circuito** — redes de sequência, Thévenin e correntes de falta por LU esparsa |
| `protecao` | **motor de proteção** — envelopes por bay, recomposição, critérios de ajuste |
| `fluxo` | **motor de fluxo de potência** — carregamento, capacidades, tensão, despacho por cenário |
| `curvas`, `sm211`, `dados_externos` | apoio: curvas IEC/IEEE, escopo do Submódulo 2.11, dados externos |

Os motores são separados de propósito, e a dependência corre numa direção só: proteção usa
o solver, o solver não conhece proteção. O cálculo de curto-circuito é validado barra a
barra contra o ANAFAS e não deve mudar porque um critério de proteção mudou.

Validado barra a barra contra o ANAFAS, com critério de erro **individual** por barra abaixo
de 1% — não erro médio.

| Métrica (caso de referência, 15.627 barras) | Resultado |
|---|---|
| Sequência positiva, erro por barra < 1% | 100,000% (mediana 0,0000%) |
| Sequência zero, erro por barra < 1% | 99,992% (mediana 0,0000%) |
| Níveis com geração por conversor, 828 barras | 100,000% < 1% (mediana 0,019%) |

> **Não substitui ferramenta homologada.** Serve como segundo caminho de cálculo — útil
> justamente por ter origem independente — e como base de automação. Resultados de
> curto-circuito têm consequência sobre dimensionamento e ajuste de proteção: qualquer uso
> real exige verificação por profissional habilitado. Ver [`docs/uso.md`](docs/uso.md).

---

## Uso com agente de IA

O LINCC foi feito para ser operado por conversa: você anexa o motor e o caso, descreve o
estudo em português, e o agente escreve o código que chama a API. Nada é calculado pelo
modelo de linguagem — todo número sai do motor.

**Anexe dois arquivos** e cole o prompt abaixo:

- `lincc_bundle.py` — o motor inteiro em um arquivo, sem instalação (está na raiz deste
  repositório; regenere com `python ferramentas/gerar_bundle.py`)
- o seu caso `.ANA`

Para validar um caso ainda não conferido, anexe também os relatórios do ANAFAS: o de
**impedâncias de barra** e o de **níveis de curto-circuito**.

```
Anexei o lincc_bundle.py (motor de curto-circuito validado contra o ANAFAS) e um caso .ANA.

O motor é a fonte de verdade: importe e use, não recrie de memória, não reescreva a
modelagem.

    import sys; sys.path.insert(0, '.')
    from lincc import AnaModel, Solver, branches_at, recomposicao_87b
    M = AnaModel("CASO.ANA");  S = Solver(M);  S.factor()

Correntes saem em kA primários. Chame lincc.orientacao() para o guia de modos, tolerância
e limitações, e consulte as docstrings para a API completa.

Se faltar dado (relação de TC, ajuste de IED, placa, capacidade de interrupção), diga o
que falta em vez de estimar.

O que eu preciso: <descreva o estudo>
```

O motor avisa sozinho, ao fatorar, quando o caso tem geração por conversor e o que fazer
a respeito. Detalhes de operação, validação de caso novo e escolha de tolerância estão em
[`docs/uso.md`](docs/uso.md).

**Primeira vez?** [`examples/prompt-demonstracao.md`](examples/prompt-demonstracao.md) traz
um prompt completo e comentado: impacto da entrada de uma LT, barras com variação acima de
10%, e o relatório de curto-circuito de uma barra com as correntes que a proteção usa.

---

## Exemplos

### Corrente de falta

```python
from lincc import AnaModel, Solver

M = AnaModel("caso.ANA")          # base de curto-circuito
S = Solver(M); S.factor()

S.fault(BARRA, "3F")      # trifásica, em kA primários
S.fault(BARRA, "1FT")     # fase-terra
S.zth(BARRA)              # (Z1, Z2, Z0) em pu, base 100 MVA
```

O modo padrão inclui a contribuição de eólicas e fotovoltaicas conectadas por conversor.
Num caso que as tenha, libere-o antes conferindo contra o próprio caso:

```python
S.validar_completo(niveis_kA, limite=1.0)     # {barra: corrente_kA} do relatório
```

Para o Thévenin puro, sem essas fontes: `S.fault(BARRA, "3F", modo="sincronas")`.

### Evolução de curto pela entrada de um equipamento

```python
# banco de três enrolamentos: remover as duas pernas do nó-estrela
S_sem = Solver(M, drop_branches=[(BARRA_AT, NO_ESTRELA, "3"),
                                 (BARRA_BT, NO_ESTRELA, "3")])
S_sem.factor()

delta = (S.fault(BARRA, "3F") - S_sem.fault(BARRA, "3F")) / S_sem.fault(BARRA, "3F")
```

### Estudo de barra completo

```python
from lincc import envelope_contribuicoes, tabela_envelope
print(tabela_envelope(envelope_contribuicoes(M, BARRA, solver=S)))
```

Quatro tipos de defeito, sistema completo e N-1, contingência por retirada e por terminal
oposto aberto, defeito na barra e close-in — devolvendo a maior e a menor corrente de fase e
de 3I0 por bay, com o cenário de cada extremo.

### Insumos de proteção

```python
S.contribution(BARRA, "3F")                      # passa-através por elemento (87T)
S.branch_current(FBUS, BF, BT, NC, "3F")         # corrente em qualquer ramo
S.line_end_open(BF, BT, NC, FECHADO, "3F")       # terminal fechado, remoto aberto
S.fault_on_branch(BF, BT, NC, 0.8, "1FT")        # falta a 80% da linha
recomposicao_87b(M, BARRA)                       # ICC_MIN por elemento energizante
```

### Fluxo de potência e envelope entre cenários

```python
from lincc import PwfModel, conciliar_bases
from lincc.fluxo import carregamento, tensao_barra, envelope_cenarios

P = PwfModel("cenario.PWF")
carregamento(P, BF, BT, NC)       # capacidade normal, de emergência e de equipamento
tensao_barra(P, BARRA)            # tensão e ângulo em regime

conciliar_bases(M, P)             # casa as duas bases e relata as diferenças
```

A base de fluxo fornece o que a de curto não tem: carregamento e capacidade por circuito em
três níveis, tensão e ângulo em regime, e o despacho de cada cenário. Vários critérios
dependem dela — pickup do 87B acima da corrente de carga, SOTF acima do carregamento
máximo, load encroachment.

```python
env = envelope_cenarios({nome: PwfModel(arq) for nome, arq in cenarios.items()},
                        lambda P: alguma_grandeza(P))
env['min'], env['max']            # cada extremo vem com o nome do cenário
```

Nos casos de referência do ONS a variação dominante é **diurno contra noturno** (~2.200
barras despachadas de diferença, efeito solar), não máxima contra mínima carga (~30).
Varrer só níveis de carga perde quase toda a variação.

### Validar um caso novo

```bash
python examples/validar_caso.py CASO.ANA RELATORIO.LST
```

Compara barra a barra contra o relatório do ANAFAS e lista o que passa do critério.
Retorna 0 se todas as comparações decisivas passam.

---

## Instalação

```bash
git clone https://github.com/matheus-cgoes/LINCC.git
cd LINCC
pip install -e ".[dev]"
pytest -q
```

Python 3.10+. Dependências: `numpy`, `scipy`.

## Documentação

| Documento | Conteúdo |
|---|---|
| [`docs/uso.md`](docs/uso.md) | Operação, modos, tolerância, limitações e API completa |
| [`docs/arquitetura.md`](docs/arquitetura.md) | Os três motores, os dois parsers e por que estão separados |
| [`docs/formato-ana.md`](docs/formato-ana.md) | Réguas de coluna e convenções do formato `.ANA` |
| [`docs/mutuas.md`](docs/mutuas.md) | Acoplamento mútuo de sequência zero |
| [`docs/validacao.md`](docs/validacao.md) | Metodologia de validação e histórico de correções |
| [`docs/scripts.md`](docs/scripts.md) | Os dois scripts auxiliares |

## Licença

Apache License 2.0 — veja [LICENSE](LICENSE). `ANAFAS` é programa e marca do CEPEL, citado
de forma nominativa apenas para identificar o formato lido e a referência de validação.
Este projeto não é afiliado, patrocinado nem endossado pelo CEPEL, e não contém, utiliza
ou deriva de código daquele programa.

Projeto pessoal, desenvolvido fora da jornada de trabalho e com recursos próprios do autor.
