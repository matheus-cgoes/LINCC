# Metodologia de ajuste das funções de proteção

Critérios aplicados pelo LINCC, com a origem de cada um. Todos são parametrizáveis
(`CRITERIOS_SOBRECORRENTE`, `CRITERIOS_BARRA`) e aparecem nas `premissas` de cada resultado.

## Princípio de carga

Ajuste que pode limitar a capacidade de transmissão é referido à **capacidade do equipamento**
— de emergência, quando declarada — e **nunca** ao carregamento de um cenário de fluxo de
potência. A proteção é do equipamento: ajuste abaixo da capacidade limita o equipamento e
pode atuar indevidamente quando uma contingência altera a topologia. O fluxo calculado a
partir do ANAREDE é informativo e não entra em nenhum ajuste.

## Sobrecorrente de linha

| Função | Critério |
|---|---|
| 51 | pickup em 120% da capacidade de emergência; tempo de 400 ms (zona 2) no defeito mais severo |
| 50 | habilitado só se superar em 20% a falta na barra remota |
| SOTF | acima da capacidade de emergência e abaixo de 80% do curto mínimo remoto |
| STUB | até 50% do curto da barra |
| 67NT | entre 10% de In do TC e 70% da monofásica remota; curva muito inversa |

## Sobrecorrente de transformador

| Função | Critério |
|---|---|
| 51 | pickup em 150% da corrente nominal |
| 50 | acima de 120% do maior entre passa-através (falta na barra do outro lado) e inrush; abaixo da falta na barra local |

## 51V — sobrecorrente com dependência de tensão

**Quando aplicar.** Sempre que a menor falta remota que o 51 deve enxergar — trifásica ou
bifásica no terminal oposto, inclusive com o terminal remoto aberto — fica abaixo do pickup
do 51. É o caso típico de entrada de transformador e de linha longa, em que a impedância do
equipamento limita a corrente de falta a níveis próximos da carga e só a tensão distingue as
duas situações [1]. Também é indicada quando o SOTF fica sem faixa.

**Ajuste.**

| Parâmetro | Critério |
|---|---|
| Pickup normal | o do 51, acima da carga |
| Tensão de partida | 0,80 pu da tensão fase-fase nominal |
| Fator de redução k | k·I> ≤ falta remota mínima / 1,2 — a margem segue o exemplo do guia MiCOM [2] |
| Supervisão | bloqueio por falha de fusível do TP [3] |

**Verificação obrigatória.** A tensão fase-fase no relé durante a falta remota mínima precisa
ficar abaixo da tensão de partida. Se não ficar, a 51V não se sensibiliza e o relatório
avisa. A tensão é calculada no modo do estudo: no modo completo as fontes de conversor
sustentam a tensão durante a falta, e calcular sem elas superestimaria a sensibilidade.

**Modos.** Os fabricantes oferecem a característica controlada por tensão (degrau: o pickup
cai para k·I> abaixo da partida) e a restringida por tensão (rampa: o pickup acompanha a
tensão) [2][3][4]. O LINCC dimensiona pelo ponto de partida e pelo fator k, que valem para
os dois; a escolha do modo e a curva de restrição seguem o manual do IED.

## Proteção de barra

| Função | Critério |
|---|---|
| 87B | capacidade de emergência < pickup < curto mínimo; sugerido 67% do curto mínimo; sem faixa, prevalece o curto |
| Checkzone | 80% do pickup do 87B |
| Alarme | 15% do pickup do 87B, abaixo da menor capacidade nominal dos vãos — detecta TC aberto sem disparo |
| 50BF | capacidade nominal < pickup < falta na extremidade oposta com remoto aberto, na alimentação local mais fraca |
| EFP | abaixo da falta junto ao disjuntor aberto, nas duas posições de TC; sem piso de carga |
| Todas | ≥ 5% de In do TC de referência (maior relação da zona), ou o ajuste mínimo do relé |
| Slope | valores de partida 50% e 80%, inflexão em 2 a 3 × In de referência — não calculados |

## Referências

[1] Siemens, *7SR210 Argus — Application Manual*, seção "Voltage Dependent Overcurrent (51V)".
[2] GE / Schneider, *MiCOM P14x — Technical Manual*, "Voltage Dependent Overcurrent",
exemplo de cálculo do fator k.
[3] ABB / Hitachi Energy, *Relion 615/630/640 — PHPVOC* e *Relion 670 — VRPVOC*, manuais
técnicos.
[4] SEL, *Implementing a 51V Voltage-Restrained Inverse-Time Overcurrent Element in the
SEL-487E Relay*, nota de aplicação.
