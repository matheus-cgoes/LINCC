# LINCC — Linguagem Natural em Curto-Circuito

Cálculo de curto-circuito e apoio a estudos de proteção para sistemas de transmissão,
operado por conversa. Você descreve o estudo em português, o agente de IA traduz em
chamadas, e todo número sai de um motor determinístico validado contra o ANAFAS.

O trabalho que o LINCC dispensa é a montagem repetitiva de cenários e a transcrição de
resultados. O esforço humano fica onde importa: a revisão técnica e o refinamento do ajuste.

| Validação, caso de referência de 15.627 barras | |
|---|---|
| Sequência positiva, erro por barra < 1% | 100,000% |
| Sequência zero, erro por barra < 1% | 99,992% |
| Níveis com geração por conversor | 100,000% < 1% |

O critério é erro **individual por barra**, não erro médio.

> **Não substitui ferramenta homologada.** Serve como segundo caminho de cálculo — útil por
> ter origem independente — e como base de automação. Resultados de curto-circuito têm
> consequência sobre dimensionamento e ajuste de proteção: qualquer uso real exige
> verificação por profissional habilitado.

---

## Começando

Anexe dois arquivos na conversa com o agente:

- **`lincc_bundle.py`** — o motor inteiro em um arquivo, sem instalação (está na raiz deste
  repositório)
- **o seu caso `.ANA`**

E descreva o estudo. Não é preciso enumerar tipos de defeito, contingências ou formato de
saída: o protocolo está embutido no próprio código.

```
Anexei o lincc_bundle.py e a base BR2612PJ.ANA.

ESTUDO: entrada em operação da LT 500 kV Curral Novo do Piauí (6640) –
São João do Piauí 2 (45019), circuito 1.

Parte 1 — Verifique onde a contribuição de curto-circuito varia acima de 10%.

Parte 2 — Relatório de proteção da barra 6640 e da LT, com o empreendimento em
operação. Relacione para que serve cada grandeza no ajuste.
```

O resultado desse pedido, comentado, está em
[`examples/prompt-demonstracao.md`](examples/prompt-demonstracao.md).

---

## O que dá para pedir

**Evolução de curto-circuito** pela entrada de um transformador ou de uma linha, com as
barras que ultrapassam o gatilho de revisão e o tipo de defeito que governou.

**Relatório de proteção** de qualquer equipamento — linha, transformador, barra, reator ou
capacitor — com as grandezas do tipo, os cenários de contingência, as funções que o
Submódulo 2.11 exige e o que falta para parametrizar.

**Envelope por bay** de uma subestação: maior e menor corrente de fase e de terra em cada
vão, varrendo os quatro tipos de defeito, sistema completo e N-1, retirada de equipamento e
terminal remoto aberto — com o cenário em que cada extremo ocorreu.

**Insumos de ajuste**: impedâncias e fator k₀ para distância, passa-através para diferencial
de transformador, corrente mínima de recomposição para diferencial de barra, curvas de tempo
inverso IEC e IEEE.

**Grandezas de regime permanente**, lendo também a base de fluxo de potência do ANAREDE:
carregamento e capacidade por circuito, tensão de barra e o despacho de cada cenário.

---

## Em código

```python
from lincc import AnaModel, Solver, impacto_entrada, relatorio_protecao, tabela_envelope

M = AnaModel("caso.ANA")
S = Solver(M); S.factor()

S.fault(BARRA, "3F")                          # corrente de falta, em kA primários
impacto_entrada(M, [(BF, BT, NC)])            # evolução pela entrada de um equipamento
relatorio_protecao(M, 'linha', (BF, BT, NC))  # relatório do equipamento
```

Um caso com geração por conversor exige liberar o modo antes, conferindo contra o relatório
do próprio caso — o motor avisa como ao fatorar.

---

## Instalação

```bash
git clone https://github.com/matheus-cgoes/LINCC.git
cd LINCC
pip install -e ".[dev]"
pytest -q
```

Python 3.10+, com `numpy` e `scipy`.

## Documentação

| | |
|---|---|
| [`examples/prompt-demonstracao.md`](examples/prompt-demonstracao.md) | Exemplo completo, comentado |
| [`docs/uso.md`](docs/uso.md) | Operação, modos, tolerância, limitações e API |
| [`docs/arquitetura.md`](docs/arquitetura.md) | Organização dos módulos |
| [`docs/formato-ana.md`](docs/formato-ana.md) | Convenções do formato `.ANA` |
| [`docs/mutuas.md`](docs/mutuas.md) | Acoplamento mútuo de sequência zero |
| [`docs/validacao.md`](docs/validacao.md) | Metodologia de validação |
| [`docs/scripts.md`](docs/scripts.md) | Scripts auxiliares |

## Licença

Apache License 2.0 — veja [LICENSE](LICENSE). `ANAFAS` e `ANAREDE` são programas e marcas do
CEPEL, citados de forma nominativa apenas para identificar os formatos lidos e a referência
de validação. Este projeto não é afiliado, patrocinado nem endossado pelo CEPEL, e não
contém, utiliza ou deriva de código daqueles programas.

Projeto pessoal, desenvolvido fora da jornada de trabalho e com recursos próprios do autor.
