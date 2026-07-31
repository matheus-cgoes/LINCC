# Casos sintéticos de referência

Redes pequenas, sem qualquer dado proprietário, com resultado **deduzido analiticamente**. Servem para
demonstrar a correção do motor de forma reproduzível por qualquer pessoa. Base 100 MVA, resistências
nulas para que a conferência à mão seja imediata.

## `caso1_radial.ANA` — radial com trafo YN-D

```
  (0)──G──[1]────LT1────[2]────TR1────[3]
       X1=10%       X1=10%       X1=8%      13,8 kV
       X0=5%        X0=30%       X0=8%      (delta)
       YN                        YN-D
```

Sequência positiva na barra 2 — gerador e linha em série:

    Z1 = j0,10 + j0,10 = j0,20 pu

Sequência zero na barra 2 — dois caminhos em paralelo: pela linha até o aterramento do gerador, e pelo
aterramento do enrolamento YN do transformador (o delta interrompe a sequência zero, criando derivação
à terra no lado YN):

    Z0 = (j0,30 + j0,05) ∥ j0,08 = j0,35 · j0,08 / j0,43 = j0,0651163 pu

Com I_base = 100/(√3 · 138) = 0,418369 kA:

| Grandeza | Barra 1 | Barra 2 |
|---|---|---|
| Z1 [pu] | j0,1000000 | j0,2000000 |
| Z0 [pu] | j0,0441860 | j0,0651163 |
| Icc 3F [kA] | 4,18370 | 2,09185 |
| Icc 1FT [kA] | 5,13997 | 2,69848 |

    Icc_3F  = I_base / |Z1|
    Icc_1FT = 3 · I_base / |2·Z1 + Z0|

Na barra 1: Z0 = j0,05 ∥ (j0,30 + j0,08) = j0,0441860 pu.

## `caso2_mutuas.ANA` — linhas paralelas acopladas

Dois circuitos idênticos entre as mesmas barras, acoplados em 100% do trecho — o teste mínimo da
matriz primitiva de grupo e da identidade de segmento por circuito.

```
  (0)──G──[1]══LT1 (X0=60%)══[2]
       X1=10%   ║ Zm = j20% ║
       X0=10%   ══LT2 (X0=60%)══
       YN
```

Positiva: os circuitos não se acoplam, logo `j0,20 ∥ j0,20 = j0,10`.

Zero: para dois circuitos idênticos e acoplados, a impedância equivalente do paralelo é

    Zeq = (Z0 + Zm)/2 = (j0,60 + j0,20)/2 = j0,40 pu

| Grandeza | Barra 2 |
|---|---|
| Z1 [pu] | j0,2000000 |
| Z0 [pu] | j0,5000000 |
| Icc 3F [kA] | 2,09185 |
| Icc 1FT [kA] | 1,39457 |

**Por que este caso importa.** Se a identidade do segmento acoplado não incluir o número do circuito,
os dois circuitos colapsam na mesma chave, a mútua é descartada e Z0 na barra 2 cai para
`j0,10 + j0,30 = j0,40` em vez de `j0,50`. O erro é de 20% e não gera nenhuma exceção — só resultado
errado. Este teste falha imediatamente nessa condição.

Extensão útil para quem for contribuir: quatro circuitos idênticos, todos acoplados dois a dois, dão
`Zeq = (Z + 3M)/4`.
