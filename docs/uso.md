# Uso do LINCC

Operação dos motores, escolha de modo, tolerância de validação, limitações conhecidas e API.
Para instalação e exemplos rápidos, veja o [README](../README.md); para a organização dos
módulos, [`arquitetura.md`](arquitetura.md).

---

## Os dois modos

```python
S.fault(bus, kind)                       # 'completo' — padrão
S.fault(bus, kind, modo='sincronas')     # Thévenin puro
```

**`completo`** inclui a contribuição de eólicas e fotovoltaicas conectadas por conversor
(bloco `DEOL`). É o número regulatório, e por isso é o padrão.

**`sincronas`** é o Thévenin puro da Ybus e exclui essas fontes.

Perto dessas usinas a diferença passa de 40% — não é refinamento, é outra resposta.

Cada modo tem uma âncora de validação distinta no relatório do ANAFAS. Confundi-las é o
erro mais comum e reprova função que está correta:

| Modo | Seção do relatório |
|---|---|
| `sincronas` | `RELATORIO DE DADOS DE CURTO-CIRCUITO` (MVA; exclui conversores) |
| `completo` | `RELATÓRIO DE NÍVEIS DE CURTO-CIRCUITO` (kA; inclui conversores) |

**Não misture modos dentro de um mesmo critério.** O envelope de TC combina ICC_MAX de um
cenário com ICC_MIN de outro: usar `sincronas` de um lado e `completo` do outro produz
margem fictícia.

### Qual usar

| Aplicação | Modo |
|---|---|
| Capacidade de interrupção, saturação de TC, esforços eletrodinâmicos, limite superior de DiffOperLevel | `completo` |
| Sensibilidade, ICC_MIN, pickup de 51/51N, alcance de zonas | ambos |

No segundo grupo, avalie os dois: conversor pleno não é fonte confiável em curto
sustentado, e o mínimo com inversores pode ser maior ou menor conforme o afundamento.
Assumir só um lado é que é erro.

### Liberar o modo completo

Num caso **com** registros DEOL, o modo completo exige validação contra o próprio caso
antes de responder — emitir injeção não conferida é pior do que não emitir:

```python
niveis = {barra: corrente_kA, ...}       # da seção de níveis do MESMO caso
selo = S.validar_completo(niveis, limite=1.0)
selo['liberado']      # True libera; o selo traz erro máximo, mediana e a pior barra
```

Num caso **sem** DEOL os dois modos coincidem e nada precisa ser validado.

---

## Escolha da tolerância

`validar_completo(niveis, limite=X)` só libera se o erro máximo ficar dentro de X%.
No caso de referência (828 barras com conversor próximo, 817 convergindo):

| tolerância | dentro | fora |
|---|---|---|
| 0,1% | 96,2% | 31 |
| 0,5% | 99,5% | 4 |
| **1,0%** | **100,0%** | **0** |

Mediana 0,019%, p95 0,067%, máximo 0,920%.

**Mantenha 1%.** É o critério que o caso de referência atende sem exclusões, e apertar
para 0,5% rejeitaria quatro barras por margem numérica, não por erro de modelo.

Se um horizonte novo trouxer divergência documentada, exclua explicitamente em vez de
afrouxar o critério — as excluídas continuam no relatório, marcadas:

```python
selo = S.validar_completo(niveis, limite=1.0, ignorar=(barra1, barra2))
```

---

## Validar um caso novo é obrigatório

O parser lê o **formato**, não um caso específico. Um tipo de registro que não apareça no
caso de referência é ignorado em silêncio: o número sai, e sai errado.

```bash
python examples/validar_caso.py CASO.ANA RELATORIO.LST
```

ou, na API:

```python
S.conciliar(z1_ref, z0_ref)          # Z1 e Z0 barra a barra
```

Quais relatórios exportar do ANAFAS, em ordem de importância:

| Relatório | Papel |
|---|---|
| **Impedâncias de barra** | Indispensável. Z₁, Z₀ e (Z₀+Z₂) com 10 decimais — o gabarito de verdade |
| **Níveis de curto-circuito** | Indispensável para liberar o modo completo: é o único que inclui os conversores |
| Dados de curto-circuito | Dispensável. Repete Z com 4 decimais e traz MVA já derivável |

Exporte sempre o de impedâncias, mesmo quando o estudo pedir só níveis: é ele que separa
erro de cálculo de arredondamento de relatório.

### Interpretando divergência

- **Erro disperso e pequeno** é quantização do relatório. Reavalie na seção de alta precisão.
- **Erro concentrado numa classe de barras** — todas de uma tensão, ou todas com certo
  equipamento — é regra de leitura errada. Essa é a assinatura que interessa.
- Para localizar o elemento responsável: `I_terra = rowsum(Y0)·V`, com `V = Y0⁻¹·e_k`.
  Os nós de maior magnitude apontam o culpado.
- Valide qualquer correção medindo o percentual abaixo do critério sobre **toda** a rede,
  nunca sobre a barra que motivou a investigação.

---

## API

### Grandezas básicas

| Chamada | Devolve |
|---|---|
| `S.fault(bus, kind)` | Corrente de falta em kA primários. `kind`: `'3F'`, `'1FT'`, `'2F'`, `'2FT'` |
| `S.zth(bus)` | `(Z1, Z2, Z0)` em pu, base 100 MVA |
| `S.fault_fc(bus, kind)` | Corrente com conversores, direto (o que o modo completo chama) |
| `S.fault(bus, kind, Zf=...)` | Falta através de impedância, em pu. Suportada nos **dois** modos |

### Contingência

```python
S = Solver(M, drop_branches=[(bf, bt, nc)], drop_gens=[bus])
S.factor()
```

O identificador de circuito (`nc`) é **string**. Um banco de três enrolamentos é modelado
por nó-estrela fictício: para removê-lo, remova **todas** as pernas.
`branches_at(M, bus)` lista os ramos incidentes, útil para montar varreduras N-1.

### Apoio a estudos de proteção

| Método | Para que serve |
|---|---|
| `contribution(bus, kind)` | Passa-através por elemento incidente (87T), direto e reverso. A soma fecha por KCL |
| `branch_current(fbus, bf, bt, nc, kind)` | Corrente em **qualquer** ramo para falta em qualquer barra |
| `bus_voltage(fbus, obus, kind)` | Tensões no relé → impedância aparente de distância. Mútuas e capacitor série já estão na Ybus |
| `line_end_open(bf, bt, nc, fechado, kind)` | Corrente no terminal fechado com o remoto aberto |
| `fault_on_branch(bf, bt, nc, p, kind)` | Falta intermediária a fração `p` de um ramo série |
| `line_end_open(bf, bt, nc, fechado, kind, p)` | Terminal remoto aberto, em qualquer posição: `p=0` close-in, `p=1` ponta |
| `fault_on_shunt(bus, p, kind)` | Falta intermediária em reator shunt |
| `winding_ground_fault(bus, Zw, n)` | Curva de triagem de falta à terra em enrolamento (87REF) |
| `recomposicao_87b(M, bus)` | Corrente mínima com a barra energizada por um só elemento |
| `envelope_contribuicoes(M, bus)` | O estudo de barra completo numa chamada — ver abaixo |
| `varredura_line_end_open(bf, bt, nc, fechado)` | Série de correntes com o terminal remoto aberto, varrendo a posição |
| `corrente_seq0_ramo(V0, br, bus)` | 3I0 em bay de transformador, que `branch_current` não cobre |

Sem relação de TC, todas as correntes são **primárias**. Ao dispor dos TCs, refira ao
secundário pela relação e adote como corrente de base do estudo a nominal primária do TC —
não a nominal do equipamento protegido.

---

## O estudo de barra numa chamada

```python
from lincc import envelope_contribuicoes, tabela_envelope
print(tabela_envelope(envelope_contribuicoes(M, BARRA, solver=S)))
```

Executa implicitamente o conjunto que um estudo de barra pede: os quatro tipos de defeito,
sistema completo e N-1 até uma barra vizinha, contingência por retirada **e** por terminal
oposto aberto, defeito na barra e close-in em cada equipamento. Devolve, por bay, a maior e
a menor corrente do loop fase-fase e do loop de terra (3I0), **com o cenário de cada
extremo**. Só a barra do estudo precisa ser informada.

## Curvas de tempo inverso

```python
from lincc import tempo, tms_para_tempo
tempo(I=2000, Is=400, tms=0.2)                 # IEC muito inversa (padrão)
tempo(I=2000, Is=400, tms=5.0, norma='IEEE')   # IEEE C37.112
tms_para_tempo(I=2000, Is=400, t_alvo=0.4)     # inverso: ajusta ao tempo exigido
```

IEC 60255-151 é o padrão (`NI`, `MI`, `EI`, `LTI`); IEEE C37.112 disponível (`MODINV`,
`MI`, `EI`).

**A IEEE traz o fator 1/7 da norma**, e parte dos fabricantes implementa sem ele — o que
multiplica o tempo por sete. Em I/Is = 5 na muito inversa, a IEC dá 3,375·TMS e a IEEE
0,187·TD: comparar TMS com TD sem converter é erro comum.

## Escopo de proteção — Submódulo 2.11

```python
from lincc.sm211 import funcoes_exigidas, tempo_maximo, verificar_escopo, exige_stub
funcoes_exigidas('reator')                  # o que o 2.11 exige, com o item de cada
tempo_maximo(500)                           # 70 ms acima de 230 kV; 90 ms em 230 kV
verificar_escopo('reator', ['87', '50/51']) # o que o estudo não contempla
```

O Submódulo 2.11 define **quais** funções devem existir e os tempos máximos; **não** define
critérios de ajuste. Esses vêm das filosofias do ONS citadas nas suas referências e da
especificação do agente.

## Dados que as bases não trazem

```python
from lincc.dados_externos import faltantes, da_base, RELATORIO
print(RELATORIO(faltantes('linha', fornecidos, model=M, elemento=(bf, bt, nc)), 'linha'))
```

Cobrado **apenas** na parametrização — cálculo de curto-circuito não depende disso. O `.ANA`
traz a potência nominal no campo MVA do DCIR; atenção que é nominal, **não** carga máxima
operativa, que o critério do 51 de linha pede. A carga máxima vem do ANAREDE.

## Capacitância de linha

```python
S = Solver(M, charging=True)      # carimba S1 e S0 em modelo π
```

**Desligada por padrão**: o gabarito de impedância de barra do ANAFAS não a inclui, e ligada
Z₁ cai de 100,000% para 50,4% das barras dentro de 1%, nas duas bases. O cálculo de falta
com terminal aberto do ANAFAS, esse sim, a inclui — as duas coisas convivem.

Nunca ligue para conciliar contra o relatório de impedâncias. E ligá-la **não** corrige o
desvio do `line_end_open`, porque a função remove a linha e a capacitância sai junto.

---

## Limitações conhecidas

### Do modo completo

- **Não convergência.** Cerca de 0,5% das barras esgotam as iterações e levantam
  `RuntimeError` em vez de devolver valor. É proposital: resultado de iteração não
  convergida não deve entrar em estudo.
- **Faltas desequilibradas** usam a tensão equivalente do estado convergido. O conversor
  contribui só em sequência positiva (manual do ANAFAS, item 2.8.3), o que o relatório de
  falta monofásica confirma.

### Do `line_end_open`

Erro conhecido contra o ANAFAS no caso de referência: **−4,11% em falta trifásica** e −0,41%
em monofásica. A função remove a linha para simular o terminal aberto; o ANAFAS mantém o
trecho pendurado e representa sua capacitância, que reduz a impedância vista. Conservador
para sensibilidade e **não** conservador para dimensionamento.

### Gerais

- **Falta interna de enrolamento** exige distribuição de espiras do fabricante.
  `winding_ground_fault` é triagem: a **forma** da curva é confiável, os absolutos não.
- **Falta intermediária em linha com acoplamento mútuo** é aproximada; o retorno traz
  `mutua_aprox`.
- **A base não tem** relação de TC, ajuste de IED nem placa de equipamento.
- **Elos HVDC back-to-back** são bloqueados: não há caminho de curto entre os dois lados.
- **Inrush** não sai da base — é transitório de energização, vem de guia normativo e placa.

---

## Modelo de injeção, para quem for auditar

Curva do conversor conforme ONS, Procedimentos de Rede, **Submódulo 2.10, item 5.8 e
Figura 14**: corrente reativa adicional abaixo de 85% da tensão de sequência positiva,
saturando no ajuste padrão V1 = 0,5 pu. Coincide com os campos `VP1` e `VP2` do registro.

Três regras foram determinadas experimentalmente contra o ANAFAS e são o que faz o modelo
fechar:

**1. `Imax` é por unidade, multiplicado por NOP.** O manual é explícito no exemplo:
"3600 A x 25 unidades = 90 kA".

**2. A escala absoluta da injeção é `Imax`, não `In`.** A curva é normalizada (ΔIq/In de 0
a 1 entre VP2 e VP1), mas o valor injetado é `frac × Imax`. Onde o campo MVA está
preenchido, `In = MVA/(√3·kV)` fica abaixo de `Imax` — razão 1,50 no caso de referência —
e escalar por `In` subestima a injeção em exatamente `Imax/In`. Onde MVA está ausente o
manual manda tomar `In = Imax` e as duas leituras coincidem, o que explica o desvio
aparecer só nas poucas barras com MVA declarado.

**3. A referência de ângulo é decidida por fonte.** Cada gerador resolve com o ângulo da
**própria** tensão convergida quando essa equação tem solução, e usa a tensão **pré-falta**
só quando não tem. A condição é local: com a fonte colada ao ponto de falta, `Vth ≈ 0` e a
equação exigiria `ang(Zjj) = 90°`. O ANAFAS declara qual referência usou no rótulo da
fonte, em relatório de contribuições: `FON.CORRENTE` contra `FON.COR.Vpre`. Aplicar o
fallback ao **conjunto**, e não à fonte que precisa dele, produz erro de +29% nas barras de
complexo com reatância negativa encadeada.

Solução por Newton com o conversor linearizado como equivalente Norton (Haddadi, Farantatos
e Kocar, [arXiv:2411.12006](https://arxiv.org/abs/2411.12006)) — a iteração de ponto fixo
com fonte de corrente ideal cai em ciclo limite e não converge.

---

## Isenção de responsabilidade

Software distribuído "no estado em que se encontra", sem garantias, nos termos da licença.
Resultados de curto-circuito têm consequência direta sobre dimensionamento de equipamento,
ajuste de proteção e segurança de pessoas e instalações. Qualquer uso em aplicação real
exige verificação independente por profissional habilitado, contra ferramenta reconhecida e
contra os dados de placa do projeto. Os autores e contribuidores não respondem por decisões
de engenharia tomadas a partir destas saídas.
