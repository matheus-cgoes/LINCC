# Acoplamento mútuo de sequência zero

O obstáculo central da sequência zero. Linhas paralelas acoplam-se em **trechos parciais**: o registro
declara o intervalo de acoplamento em porcentagem do comprimento de cada linha. Tratar par a par nos
extremos do trecho é incorreto quando há sobreposição de trechos distintos.

## Modelagem adotada — matriz primitiva de grupo

1. **Segmentar.** Cada linha é fatiada nos pontos de corte declarados por todas as mútuas que a tocam.
2. **Distribuir.** O acoplamento entre dois segmentos vale `Mab = Zm · fa · fb`, com `fa` e `fb` as
   frações de comprimento (hipótese de acoplamento uniformemente distribuído).
3. **Agrupar.** Segmentos mutuamente acoplados formam grupos por união-busca.
4. **Estampar.** Por grupo, monta-se `Zprim` (diagonal: impedância própria do segmento; fora da
   diagonal: `Mab` com sinal pela orientação canônica), inverte-se e soma-se à Ybus:

```
ΔY = Zprim⁻¹ − diag(1/Zi)
```

## A armadilha que trava o resultado

**A identidade de cada segmento precisa incluir o número do circuito**, não apenas o par de barras.

Com chave formada só pelos nós, dois circuitos paralelos entre as mesmas barras colapsam na mesma
entrada, e **todas as mútuas entre eles são silenciosamente descartadas** — sem exceção, sem aviso,
apenas resultado errado. Corrigir isso levou a sequência zero de 84,5% para 98,3% das barras abaixo
de 1%, e dissolveu de uma vez dez casos que estavam classificados como "divergência de dado".

## Cuidados numéricos

- Arredondar as porcentagens de corte (`round(·, 6)`) antes de comparar: `7.0` e `0.07·100` divergem
  no último bit e geram segmentos espúrios de comprimento ~1e-15, cuja admitância (~1e17) contamina
  a matriz por cancelamento catastrófico. Segmentos com fração abaixo de `1e-9` são descartados.
- Registros com `%I > %F` existem na prática e são aceitos pela ferramenta de referência: normalizar
  para `(min, max)` **sem** inverter o sinal da mútua.
- Dado que viola passividade (`|Zm| > √(Z1·Z2)`) ocorre em casos reais. A ferramenta de referência
  aplica o dado como está e produz impedância de sequência zero capacitiva com ângulo fora de faixa;
  o motor reproduz o mesmo comportamento. Não é erro do solver.

## Verificação analítica

Grupo de quatro circuitos idênticos entre as mesmas barras, todos acoplados dois a dois:
`Zeq = (Z + 3M)/4`. Confere com o valor obtido pela estampagem — é o teste mais simples que valida a
construção da matriz primitiva.
