# LINCC — Linguagem Natural em Curto-Circuito

Motor de curto-circuito para sistemas de transmissão, em Python. Lê casos em formato `.ANA`,
monta as redes de sequência positiva e zero e calcula equivalentes de Thévenin, correntes de
falta e grandezas de apoio a estudos de proteção por fatoração LU esparsa.

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

---

## Exemplos

### Corrente de falta

```python
from lincc import AnaModel, Solver

M = AnaModel("caso.ANA")
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

### Insumos de proteção

```python
S.contribution(BARRA, "3F")                      # passa-através por elemento (87T)
S.branch_current(FBUS, BF, BT, NC, "3F")         # corrente em qualquer ramo
S.line_end_open(BF, BT, NC, FECHADO, "3F")       # terminal fechado, remoto aberto
S.fault_on_branch(BF, BT, NC, 0.8, "1FT")        # falta a 80% da linha
recomposicao_87b(M, BARRA)                       # ICC_MIN por elemento energizante
```

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
