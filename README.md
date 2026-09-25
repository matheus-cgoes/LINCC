# LINCC — Linguagem Natural em Curto-Circuito

Cálculo de curto-circuito e apoio a estudos de proteção para sistemas de transmissão,
operado por conversa. Você descreve o estudo em português para um agente de IA, e ele
conduz o cálculo num motor determinístico validado contra o ANAFAS.

Não é preciso programar. O trabalho que a ferramenta dispensa é a montagem repetitiva de
cenários e a transcrição de resultados; o esforço humano fica onde importa, na revisão
técnica e no refinamento do ajuste.

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

Abra uma conversa com um agente de IA e anexe três coisas:

| Anexo | O que é |
|---|---|
| **`lincc_bundle.py`** | A ferramenta, em arquivo único. Baixe da raiz deste repositório |
| **O seu caso** | O arquivo `.ANA` do horizonte do estudo |
| **Os relatórios do ANAFAS** | Do mesmo caso. Servem para conferir o cálculo antes de emitir corrente |
| **Os casos do ANAREDE** *(opcional)* | Os arquivos `.PWF` dos cenários de carga do mesmo horizonte. Trazem carregamento, capacidade dos circuitos e o despacho de cada cenário |

Depois descreva o estudo, como faria para um colega. Não é necessário dizer quais tipos de
defeito considerar, quais contingências montar nem em que formato apresentar: isso já está
definido dentro da ferramenta.

```
Anexei o lincc_bundle.py, a base BR2612PJ.ANA e os relatórios do ANAFAS desse caso.

ESTUDO: entrada em operação da LT 500 kV Curral Novo do Piauí (6640) –
São João do Piauí 2 (45019), circuito 1.

Parte 1 — Verifique onde a contribuição de curto-circuito varia acima de 10%.

Parte 2 — Relatório de proteção da barra 6640 e da LT, com o empreendimento em
operação. Relacione para que serve cada grandeza no ajuste.
```

O que esse pedido produz está em
[`examples/prompt-demonstracao.md`](examples/prompt-demonstracao.md).

---

## Sobre os relatórios do ANAFAS

As bases do ONS trazem centenas de eólicas e fotovoltaicas conectadas por conversor. Perto
delas, considerar ou não a contribuição dessas usinas muda a corrente em mais de 40%, e é o
valor **com** essa contribuição que responde pelo número de interesse regulatório.

Para emitir esse valor com segurança, a ferramenta confere o próprio cálculo contra o
relatório do caso antes de apresentar resultados. A razão é que ela lê o formato do arquivo,
não um caso específico: um tipo de registro incomum poderia ser interpretado de forma
errada sem que nada acusasse. A conferência fecha essa lacuna.

**Quais exportar do ANAFAS:** o relatório de **níveis de curto-circuito** e, se possível, o
de **impedâncias de barra**. O primeiro é o que permite a conferência; o segundo dá uma
verificação mais precisa.

**Se você não tiver os relatórios**, diga isso ao agente. Ele vai explicar as alternativas
e perguntar como prosseguir — há como seguir sem eles, e o estudo registra essa condição.

---

## O que dá para pedir

**Evolução de curto-circuito** pela entrada de um transformador ou de uma linha, com as
barras que ultrapassam o gatilho de revisão e o tipo de defeito responsável.

**Relatório de proteção** de qualquer equipamento — linha, transformador, barra, reator ou
capacitor — com as grandezas do tipo, os cenários de contingência, as funções que o
Submódulo 2.11 exige e a lista do que ainda falta para parametrizar.

**Estudo de proteção de barra** completo a partir de um pedido como "proteção da barra X":
pickup da diferencial, checkzone, alarme de TC aberto, falha de disjuntor e proteção de zona
morta, com a menor corrente de curto buscada entre rede normal, contingências, recomposição
da barra por cada alimentação e cenários de operação. Os critérios usados vêm declarados, e
quando a faixa de ajuste não existe, o relatório diz qual critério prevaleceu e por quê.

**Estudo de distância** de um terminal de linha: impedância vista pelo relé em cada laço,
em rede normal e em contingência, e os limites que cada zona precisa respeitar para cobrir a
linha sem alcançar além das adjacentes. Circuito paralelo, acoplamento mútuo e capacitor
série vêm sinalizados. Se você informar os alcances, o relatório traz as margens.

**Diferencial de linha**: faixa do ajuste entre a corrente capacitiva da linha e a menor
falta interna, com a maior corrente passante para falta externa como referência de
estabilidade.

**Envelope por vão** de uma subestação: maior e menor corrente de fase e de terra em cada
vão, varrendo os quatro tipos de defeito, sistema completo e contingência simples, retirada
de equipamento e terminal remoto aberto — com o cenário em que cada extremo ocorreu.

**Faixas de ajuste de sobrecorrente**, com a verificação de viabilidade de cada função —
temporizada, instantânea, fechamento sob falta, proteção de trecho e direcional de terra —
e o limite que governa. Quando uma função não tem faixa possível, o relatório diz por quê.
Se a falta no terminal oposto não alcança o ajuste temporizado, a sobrecorrente com
restrição de tensão é dimensionada, com a verificação de que a tensão no relé cai o
suficiente para sensibilizá-la.

Todo ajuste que pode limitar a transmissão é referido à **capacidade** do equipamento, e não
ao carregamento de um cenário: a proteção é do equipamento.

**Insumos de ajuste** de proteção: impedâncias e fator de compensação para distância,
corrente passante para diferencial de transformador, corrente mínima de recomposição para
diferencial de barra, curvas de tempo inverso IEC e IEEE.

**Curto-circuito por cenário de operação**, quando os casos do ANAREDE são anexados. O
ANAFAS representa a rede sempre completa, com todas as usinas gerando; os cenários de carga
leve, média e pesada, diurnos e noturnos, retiram as que estão paradas. O menor curto — que
dimensiona a sensibilidade da proteção — costuma cair bem abaixo do valor da rede completa,
sobretudo à noite, quando as usinas solares saem. O relatório diz em qual cenário cada
extremo ocorreu.

**Carga máxima dos circuitos** a partir das capacidades declaradas no ANAREDE, usada nos
critérios de proteção em vez de ser pedida a você.

Dados que nenhuma base contém — relação de TC, ajuste de relés vizinhos, placa de
equipamento — são solicitados quando fazem falta, em vez de estimados. E todo resultado vem
acompanhado das premissas que o produziram: critérios de ajuste, origem de cada dado,
hipóteses de cálculo.

---

## Instalação

Para uso por agente, nada a instalar: basta o arquivo `lincc_bundle.py`.

Para trabalhar sobre o código:

```bash
git clone https://github.com/matheus-cgoes/LINCC.git
cd LINCC
pip install -e ".[dev]"
pytest -q
```

Python 3.10+, com `numpy` e `scipy`.

## Documentação

| | Para quem |
|---|---|
| [`examples/prompt-demonstracao.md`](examples/prompt-demonstracao.md) | Quem vai usar: exemplo completo |
| [`docs/metodologia-protecao.md`](docs/metodologia-protecao.md) | Critérios de ajuste de cada função e suas fontes |
| [`docs/uso.md`](docs/uso.md) | Quem vai programar: operação, modos, limitações e API |
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
