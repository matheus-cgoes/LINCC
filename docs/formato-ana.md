# Formato `.ANA` — o que o parser lê

Arquivo de texto com **colunas fixas**, codificação `cp1252`, quebra de linha `CRLF`. Organizado em
blocos, cada um aberto por uma linha com o nome do bloco. Linhas iniciadas por `(` são comentário.

A leitura aqui documentada foi obtida por engenharia reversa a partir de casos reais e validada contra o
relatório da ferramenta de referência. **Não é especificação oficial** — é o que se verificou funcionar,
com as réguas medidas no próprio arquivo.

## Blocos

| Bloco | Conteúdo | Obrigatório |
|---|---|---|
| `DBAR` | Barras: número, estado, nome, tensão base | **sim** |
| `DCIR` | Ramos e equipamentos (ver tipos abaixo) | **sim** |
| `DMUT` | Acoplamento mútuo de sequência zero entre trechos parciais de linhas | não |
| `DMOV` | (não utilizado pelo motor) | não |
| `DSHL` | Reator / shunt de linha, com estado e número de unidades | não |
| `DEOL` | Geração via inversor — fonte de corrente, fora da Ybus | não |
| `DARE` | Áreas | não |

O fim de um bloco é o início do próximo que **existir** no arquivo, ou o fim do arquivo. Um caso que não
declare `DMUT`, `DSHL` ou `DEOL` é legítimo e é lido normalmente (coberto por
`tests/cases/caso3_minimo.ANA`).

## Escala numérica — a regra que mais causa erro

Campos de impedância e susceptância seguem duas convenções no **mesmo** arquivo:

- Campo **com** ponto decimal: vale o que está escrito. `" 10.00"` → 10,00%.
- Campo **sem** ponto decimal: vale `valor/100`, isto é, percentual com duas casas implícitas.
  `"  1000"` → 10,00%.

Ler um campo sem ponto como valor direto erra por fator 100 e produz resultado plausível mas errado.

Sentinelas de infinito: `999999` (em qualquer posição do campo) e notação científica como `1E7`
significam impedância infinita — ramo aberto. Sem esse tratamento, entram `NaN` na matriz e a fatoração
falha ou devolve resultado sem sentido.

## `DBAR` — barras

| Campo | Colunas (0-based) | Observação |
|---|---|---|
| Número | `[0:5]` | `99999` é **sentinela de fim de bloco**, não é barra elétrica |
| Estado | `[6:7]` | `D` / `d` = barra desligada: o motor a remove do caso, com seus equipamentos |
| Nome | `[9:21]` | |
| Tensão base | `[31:36]` | kV |

## `DCIR` — ramos e equipamentos

| Campo | Colunas | Observação |
|---|---|---|
| Barra "de" | `[0:5]` | |
| Estado (`CE`) | `[6:7]` | `D` / `d` = equipamento fora de serviço, ignorado |
| Barra "para" | `[7:12]` | `0` quando o equipamento é shunt (gerador, reator, zigzag) |
| Circuito (`NC`) | `[14:16]` | **string**, não inteiro: `"1"`, `"2"`, `"A"` |
| Tipo | `[16:17]` | ver tabela seguinte |
| `R1` `X1` `R0` `X0` | `[17:23]` `[23:29]` `[29:35]` `[35:41]` | % na base do caso |
| Nome | `[41:47]` | |
| `S1` `S0` | `[47:52]` `[52:57]` | susceptância (não entra em nenhuma sequência — modelagem sem tensão pré-falta) |
| Conexão lado "de" (`CD`) | `[80:82]` | `YN` aterrada, `Y` **isolada**, `D` delta |
| Neutro lado "de" | `[82:88]` `[88:94]` | `RNDE` / `XNDE`, entram como `3·Zn` |
| Conexão lado "para" (`CP`) | `[94:96]` | |
| Neutro lado "para" | `[96:102]` `[102:108]` | `RNPA` / `XNPA` |
| Unidades | `[115:121]` | declara instaladas e operativas; usa-se a **última** (operativas) |

Tipos tratados:

| Tipo | Elemento | Entra em |
|---|---|---|
| `L` | Linha de transmissão | seq. positiva e zero |
| `T` | Transformador | seq. positiva e zero, topologia conforme conexão |
| `G` | Gerador síncrono | as duas sequências, admitância × unidades operativas |
| `H` | Shunt de barra (reator, filtro, resistor de aterramento) | seq. zero (`R0 + jX0` já é a homopolar **completa**) |
| `S` | Capacitor série | as duas sequências |
| `Z` | Transformador de aterramento / zigzag | seq. zero |
| `E` | Compensador estático | conforme conexão e aterramento |

Tipos não reconhecidos são ignorados silenciosamente — se o seu caso tem um tipo ausente desta lista, o
elemento não é modelado.

### Detalhes que não são óbvios

- **`Y` no campo de conexão significa estrela ISOLADA**, não aterrada. Determinação empírica, validada
  contra o gabarito; contraria a leitura intuitiva. Campo em branco é tratado como `YN`.
- **O lado do registro decide qual conexão e aterramento valem.** Equipamento declarado com a barra no
  campo "de" (e `0` no "para") usa `CD` / `RNDE` / `XNDE`; com a barra no campo "para", usa
  `CP` / `RNPA` / `XNPA`. Ler o lado errado perde o resistor de neutro.
- **Famílias de shunt têm semânticas distintas.** No registro `H`, `R0 + jX0` já é a impedância
  homopolar completa: somar `3·Zn` outra vez duplica o aterramento. Já em `E` e no `DSHL`, o
  aterramento entra separado.
- **Filtro de conversora tem `X1` infinito** e simplesmente não existe na rede de sequência positiva.
- **Equivalente de distribuição permanece na sequência zero e é excluído da positiva** — é carga a
  jusante, não fonte.
- Bancos de transformadores de três enrolamentos aparecem como duas ou três pernas ligadas a um
  **nó-estrela fictício**, com tensão base 0. Remover o banco em contingência exige remover todas as
  pernas.

## `DMUT` — acoplamento mútuo de sequência zero

| Campo | Colunas |
|---|---|
| Linha 1: `BF1` `BT1` `N1` | `[0:5]` `[5:12]` `[12:16]` |
| Linha 2: `BF2` `BT2` `N2` | `[16:21]` `[21:28]` `[28:32]` |
| `RM` `XM` | `[32:38]` `[38:44]` |
| `%I1` `%F1` `%I2` `%F2` | `[45:51]` `[51:57]` `[57:63]` `[63:69]` |

As porcentagens delimitam o **trecho parcial** acoplado de cada linha. Registros com `%I > %F` existem
na prática e são aceitos pela ferramenta de referência: normalizam-se para `(min, max)` **sem** inverter
o sinal da mútua. A modelagem por matriz primitiva de grupo está em [`mutuas.md`](mutuas.md).

## `DSHL` — reator / shunt de linha

| Campo | Colunas | Observação |
|---|---|---|
| `BF` `BT` | `[0:5]` `[7:12]` | |
| Estado (`CE`) | `[5:7]` | `D` = reator desligado, ignorado |
| Terminal | `[16:17]` | a qual extremidade o reator pertence |
| Potência | `[19:26]` | Mvar |
| `Rn` `Xn` | `[28:34]` `[34:40]` | percentual **direto**, sem duas casas implícitas; entram como `3·Zn` |
| Unidades | `[47:57]` | usa-se a última (operativas) |

## Este parser serve para outros casos?

**Sim, com ressalvas honestas.** O parser lê o *formato*, não um caso específico. O que generaliza e o
que não:

**Generaliza.** As réguas de coluna são do formato e são estáveis entre versões da ferramenta; as regras
de escala, sentinelas, estados e unidades operativas também. Casos de outros horizontes, outras
configurações ou outros subsistemas são lidos sem alteração de código. A ausência de blocos opcionais é
tratada.

**Não está garantido.** A validação barra a barra foi feita contra **um** caso. Portanto:

1. **Tipos de registro ausentes daquele caso não foram exercitados.** Se o seu caso traz um tipo de
   elemento que não aparece na tabela acima, ele é ignorado em silêncio — o resultado sai, e sai errado.
2. **Variantes de layout entre versões da ferramenta são possíveis.** Um campo novo ou deslocado passa
   despercebido: nada quebra, o número muda.
3. **Convenções determinadas empiricamente** (como `Y` = estrela isolada) foram inferidas de um conjunto
   de dados; um caso construído de outro modo pode contrariá-las.

Por isso o procedimento correto ao usar um caso novo **não é confiar** — é revalidar. Compare barra a
barra contra o relatório da ferramenta de referência para aquele caso, com o critério de erro individual,
antes de usar o resultado em qualquer estudo. O método de diagnóstico está em
[`validacao.md`](validacao.md), e há um script pronto em `examples/validar_caso.py`.

Um sinal prático de layout divergente: erro concentrado e sistemático em uma classe de barras (todas as
de uma tensão, ou todas que têm certo equipamento), em vez de disperso. Erro disperso e pequeno é
quantização do relatório; erro em bloco é regra de leitura errada.
