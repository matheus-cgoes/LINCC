# Validação

## Critério

**Erro individual por barra abaixo de 1%**, em sequência positiva e zero. Não erro médio, não faixa de
5%. A média geral baixa é fácil de obter e não sustenta uso em estudo de proteção: basta que a barra
errada seja justamente a do vão em análise.

## Referência

Comparação contra o relatório da ferramenta oficial, barra a barra, sobre todas as barras do caso — não
por amostragem.

Uma observação de método que muda conclusões: relatórios costumam ter uma seção resumida, com poucos
dígitos, e uma seção de impedâncias de barra com precisão maior. Quando a impedância é pequena, o
arredondamento da seção resumida produz erro relativo aparente elevado. **Todo aparente desvio acima do
critério deve ser reavaliado na seção de alta precisão** antes de ser tratado como erro do solver. No
caso de referência, 139 aparentes desvios em sequência zero resultaram em zero desvios reais.

## Diagnóstico por corrente de terra nodal

Quando uma barra excede o critério, a pergunta é física, não estatística: por onde a corrente homopolar
está escoando indevidamente?

    V = Y0⁻¹ · e_k
    I_terra = rowsum(Y0) · V

Ordenando por `|I_terra|`, os primeiros nós apontam o elemento responsável — shunt contado duas vezes,
reator que deveria estar desligado, caminho de terra criado por erro de leitura de coluna, aterramento
ausente. Cada divergência numérica vira, assim, uma hipótese verificável no registro cru do arquivo.

Passo obrigatório: confirmar a hipótese **no registro**, imprimindo `repr(linha[a:b])`. Colunas se
medem no arquivo; não se assumem por analogia com outro bloco.

## Teste A/B global

Toda hipótese é aplicada, o modelo reconstruído, e o resultado medido pelo percentual de barras abaixo
de 1% em **toda** a rede — nunca na barra que motivou a investigação.

Correção que melhora uma barra e degrada centenas é rejeitada, ainda que a teoria pareça favorecê-la.
Exemplo real: usar `1·Zn` em vez de `3·Zn` no aterramento de reator de linha corrige uma barra
específica e derruba o global de 98,9% para 98,0%. Hipótese descartada.

Sem essa regra, cada ajuste individual é sobreajuste ao caso de teste: o motor acerta o gabarito e erra
o próximo caso. Com ela, cada correção aceita é uma regra do formato, que vale em geral.

## Histórico de correções estruturais

Cada salto abaixo é uma regra do formato descoberta por diagnóstico físico. Nenhum é ajuste de
parâmetro.

| Correção | Sequência zero, barras < 1% |
|---|---|
| Ponto de partida | 67% |
| Mútuas por matriz primitiva de grupo, com réguas de coluna corretas | 85% |
| Identidade de segmento incluindo o número do circuito | 98,3% |
| Unidades operativas de bancos e transformadores; normalização de `%I > %F` | 98,6% |
| Famílias de shunt (sem dupla contagem de neutro) e estados de reator de linha | 98,8% |

Em sequência positiva, o ganho decisivo veio de remover barras marcadas como desligadas com seus
equipamentos (97,4% → 99,4%) e, na precisão numérica, de aplicar a regularização apenas a componentes
conexos flutuantes em vez de uniformemente na diagonal — o que deixou as barras de 500 kV com erro
mediano da ordem de 10⁻⁹ % contra a seção de alta precisão.

## Resíduo conhecido

- **Barras de fronteira internacional**: o valor depende do equivalente de rede externo, não da
  modelagem interna.
- **Erro relativo alto sobre valor absoluto ínfimo**: quantização do relatório de referência.
- **Dado que viola passividade** em mútuas: a ferramenta de referência aplica o dado como está e produz
  sequência zero capacitiva; o motor reproduz o mesmo resultado. Não é erro.
