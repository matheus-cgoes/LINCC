# Como contribuir

## Regra que não se negocia

Nenhuma alteração de modelagem entra sem **teste A/B global**. Reporte, no pull request, o percentual
de barras com erro individual abaixo de 1% em ambas as sequências, antes e depois da mudança, sobre um
caso completo. Melhoria local com degradação do conjunto é rejeitada — mesmo quando a teoria parece
favorecer a mudança.

Exemplo de rejeição real: usar `1·Zn` em vez de `3·Zn` no aterramento de reator de linha corrige uma
barra específica e derruba o resultado global de 98,9% para 98,0%. A hipótese foi descartada.

## Fluxo esperado para corrigir uma divergência

1. **Localize fisicamente.** Calcule `I_terra = rowsum(Y0) · V` para a falta na barra suspeita. Os nós
   de maior corrente apontam o elemento responsável.
2. **Confirme no registro cru.** Imprima `repr(linha[a:b])` do arquivo e mostre, no PR, o registro que
   justifica a interpretação. Colunas se medem no arquivo, não se assumem.
3. **Meça globalmente.** Reconstrua com e sem a correção e informe os dois números.
4. **Cubra com teste.** Se a regra for expressável em caso pequeno, acrescente um caso sintético em
   `tests/cases/` com resultado deduzido analiticamente.

## O que não entra

- Casos de rede reais, relatórios de ferramentas licenciadas, dados de instalação ou qualquer material
  de terceiro. Testes usam casos sintéticos.
- Trechos de manual, documentação ou código de outros programas.
- Ajuste empírico barra a barra sem mecanismo físico identificado. Se não sabe *por que* funciona, não
  está pronto.

## Estilo

Português nos comentários e na documentação. Nomes de variáveis podem seguir a notação da engenharia
(`Z0`, `Y1`, `zth`) — clareza para o engenheiro tem precedência sobre convenção genérica de código.
Sem dependência nova sem justificativa: hoje são apenas `numpy` e `scipy`.
