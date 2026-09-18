# Arquitetura

Dois parsers e três motores, em arquivos separados. A separação é estrutural: foi feita sem
alterar nenhum resultado — 45 grandezas de referência, incluindo a conciliação completa das
15.627 barras, conferidas idênticas até 1e-12 antes e depois.

```
src/lincc/
├── _base.py            helpers numéricos e constantes (SB, num, zfin, zn3)
│
├── parser_anafas.py    base de CURTO-CIRCUITO (.ANA)  -> AnaModel
├── parser_anarede.py   base de FLUXO DE POTÊNCIA (.PWF) -> PwfModel, conciliar_bases
│
├── solver.py           MOTOR DE CURTO-CIRCUITO
├── protecao.py         MOTOR DE PROTEÇÃO
├── fluxo.py            MOTOR DE FLUXO DE POTÊNCIA
│
├── curvas.py           curvas de tempo inverso IEC e IEEE
├── sm211.py            escopo funcional e tempos do Submódulo 2.11
├── dados_externos.py   catálogo do que as bases não contêm
│
├── model.py            shim de compatibilidade (reexporta parser_anafas)
└── __init__.py          API pública
```

## Direção das dependências

```
parser_anafas ──► solver ──► protecao
parser_anarede ──► fluxo ──┘
```

**O solver não conhece o motor de proteção.** Há teste que verifica isso lendo o próprio
arquivo. A razão é concreta: o cálculo de curto-circuito é validado barra a barra contra o
ANAFAS, com 100,000% das barras dentro de 1% em sequência positiva. Um critério de proteção
que mudasse não pode ter como alterar esse número, e manter os dois no mesmo arquivo convida
exatamente a isso.

Pelo mesmo motivo o motor de fluxo não resolve fluxo de potência: lê o caso já convergido
publicado pelo ONS. Recalcular seria refazer o que o ANAREDE fez, com risco de divergir do
caso oficial que o estudo cita.

## Por que dois parsers

As bases não são intercambiáveis e nenhuma contém o que a outra tem.

| | ANAFAS (`.ANA`) | ANAREDE (`.PWF`) |
|---|---|---|
| Rede | sempre completa | varia por cenário |
| Despacho | fixo na configuração | carga leve/média/pesada, diurno/noturno, verão/inverno |
| Capacidade | só potência nominal (campo MVA) | normal, emergência e equipamento |
| Regime permanente | não tem | tensão, ângulo, carregamento, carga |
| Sequência zero | completa, com mútuas | não representada |

O casamento entre elas é por número de barra, com verificação por nome — 85,9% das barras
do `.PWF` têm o mesmo número no `.ANA`, e 97,6% dos nomes coincidem. As exclusivas têm
padrão e não são erro: o `.ANA` detalha nós-estrela fictícios e terminais de gerador que o
fluxo agrega. Use `conciliar_bases()` antes de qualquer uso conjunto e registre o resultado
no estudo — se um bay receber carregamento da barra errada, o pickup sai errado sem nada
acusar.

## Bundle

`lincc_bundle.py` continua sendo o motor inteiro em um arquivo, com **todos** os módulos —
os dois parsers, os três motores e o apoio. A modularização vale para os fontes; o bundle
segue único, para anexar em sessão de chat sem instalação.

```bash
python ferramentas/gerar_bundle.py
```

O CI verifica que o bundle está sincronizado com os fontes e reprova se divergir.

## Compatibilidade

`from lincc.model import AnaModel` continua funcionando, por um shim. A API pública de
`lincc` não perdeu nada: o que era exportado continua exportado, e há teste que verifica.
