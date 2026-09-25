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
| 51 | sem padrão universal: o múltiplo da nominal é critério da filosofia do agente e do perfil de carga do transformador, informado no pedido; sem ele o resultado sai como dados faltantes |
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

### O que os guias dos fabricantes estabelecem

| Ponto | SEL-487B | Siemens 7SS85 | ABB/Hitachi REB670 | Classificação |
|---|---|---|---|---|
| Pickup da diferencial | O87P ajustável | Idiff de 0,20 a 4,00 × In do objeto [6] | em A primários; acima da carga máxima se a falta mínima permitir; abaixo de 80% da menor falta; típico 50% a 150% de In do maior TC [7] | **consenso** com o critério adotado |
| Característica | duas inclinações, SLP1 60% e SLP2 80%, a segunda comutada pela detecção de falta externa [5] | fator k de 0,10 a 0,80 [6] | slope fixo em 53% [7] | **divergência**: parâmetro do IED |
| Checkzone | — | independente de seccionadoras [6] | independente de seccionadoras; detecção de TC aberto dispensa checkzone adicional [7] | consenso quanto à independência; o nível segue o critério adotado |

A consequência para o slope é direta: os percentuais **não são transferíveis** entre
fabricantes. O LINCC não calcula slope e informa a referência de cada fabricante.

### Critérios aplicados

| Função | Critério | Origem |
|---|---|---|
| 87B | capacidade de emergência < pickup < curto mínimo; sugerido 67% do curto mínimo; sem faixa, prevalece o curto | critério do usuário, compatível com [7] |
| 87B, teto | pickup ≤ 80% do curto mínimo | [7] |
| 87B, faixa típica | 50% a 150% de In do maior TC, verificada quando o TC é informado | [7] |
| Checkzone | faixa própria: acima do piso de medição e abaixo do teto de sensibilidade para toda falta interna; sem escala fixa em relação ao 87B | critério de sensibilidade |
| Alarme de TC aberto | abaixo da menor corrente REAL conduzida pelos vãos nos cenários do ANAREDE — é ela que aparece como diferencial quando um TC abre; limite inferior e temporização dependem dos TCs | critério de detecção |
| 50BF | capacidade nominal < pickup < falta na extremidade oposta com remoto aberto, na alimentação local mais fraca; prevalece a sensibilidade | critério do usuário, alinhado a [8] |
| 50BF, disparos sem corrente de falta | lógica por contato do disjuntor | [9][10] |
| EFP | abaixo da falta junto ao disjuntor aberto, nas duas posições de TC; sem piso de carga | critério do usuário |
| Todas | ≥ 5% de In do TC de referência, ou o ajuste mínimo do relé | critério do usuário |
| Slope | não calculado: parâmetro do IED | [5][6][7] |

Sobre o 50BF, o guia da SEL registra o mesmo equilíbrio do critério adotado: idealmente o
detector fica acima da carga máxima, mas pode ficar abaixo quando a sensibilidade exigir [8].
A iniciação só por comando de disparo evita a operação indevida nesse caso. O guia da ABB
prevê a detecção por corrente ou pelo sinal de disparo remanescente, e o redisparo [9].

### Não verificado nesta revisão

GE MiCOM P74x (barra) e os tempos de redisparo e de falha de disjuntor. Os tempos seguem o
limite de 250 ms do Submódulo 2.11 até a revisão específica.

## Distância (21/21N)

O LINCC não aprova alcance percentual. Mede a impedância aparente vista pelo relé, laço a
laço, em rede completa e em contingência simples em torno dos dois terminais, e devolve os
limites que qualquer ajuste precisa respeitar:

| Zona | Limite calculado |
|---|---|
| 1 | abaixo da impedância da linha |
| 2 | acima da impedância da linha e abaixo da menor impedância aparente para falta no fim das linhas adjacentes, com infeed |
| 3 | referência de retaguarda: maior impedância aparente para falta no fim das adjacentes |
| Carga | menor impedância de carga, pela capacidade de emergência e tensão mínima |

Laços: AG para monofásica, BC para bifásica, BC/BG/CG para bifásica-terra, AB para
trifásica. Compensação residual com k0 complexo; Kr e Kx são informados à parte, porque não
são as partes de k0. Circuito paralelo e acoplamento mútuo são sinalizados, e o fim do
paralelo — a própria barra local — não entra como falta adjacente. Capacitor série na linha
ou nas adjacentes gera alerta para avaliação com inserção, bypass e estudo transitório.

Com os alcances informados no pedido, o resultado traz a margem de cada zona e a conversão
ao secundário (relações de TC e TP). A comparação é por módulo na direção da linha; a região
real depende da característica do IED, que não está modelada.

## Critérios do usuário e exportação

Os critérios de filosofia do agente — múltiplos de carga, escalas entre funções, margens —
não são padrão do código: são informados no pedido e entram pelo parâmetro `criterios` de
cada função. Sem eles, a função devolve a faixa admissível e marca o critério como faltante.

Curvas de tempo inverso seguem a forma padronizada, sem fator de normalização de
fabricante. O ajuste de um IED específico usa a curva documentada no manual dele,
registrada com fonte, seção e revisão.

Um resultado só pode ser exportado como ajuste de relé com o perfil do IED documentado —
cada regra com fonte, seção, revisão, base, unidade, resolução e classe de evidência — e
com todas as funções em `calculavel_verificada`. Exemplo de manual não vira requisito.
Fora disso, o resultado é insumo de estudo.

SIR é indicador de desempenho da proteção de distância, não critério de proibição: a
viabilidade depende da característica, da polarização e do desempenho transitório do IED e
do TP capacitivo, comprovados à parte.

## Referências

[1] Siemens, *7SR210 Argus — Application Manual*, seção "Voltage Dependent Overcurrent (51V)".
[2] GE / Schneider, *MiCOM P14x — Technical Manual*, "Voltage Dependent Overcurrent",
exemplo de cálculo do fator k.
[3] ABB / Hitachi Energy, *Relion 615/630/640 — PHPVOC* e *Relion 670 — VRPVOC*, manuais
técnicos.
[4] SEL, *Implementing a 51V Voltage-Restrained Inverse-Time Overcurrent Element in the
SEL-487E Relay*, nota de aplicação.
[5] SEL, *SEL-487B Single-Phase Testing of the Differential Element*, guia de aplicação —
valores padrão O87P, SLP1 e SLP2 e comutação para alta segurança.
[6] Siemens, *SIPROTEC 5 7SS85 — Manual*, dados técnicos da proteção diferencial de barra.
[7] ABB, *REB670 — Application Manual* e *Product Guide*, proteção diferencial de barra.
[8] SEL, *Application Considerations for Local and Remote Breaker Failure Protection*.
[9] ABB, *RET670 — Application Manual*, proteção de falha de disjuntor CCRBRF (50BF).
[10] IEEE Std C37.119, *Guide for Breaker Failure Protection of Power Circuit Breakers*.
