# LINCC — prompt de demonstração

O protocolo de trabalho está **no próprio código** (docstring de `lincc`, e embutido nas
funções de alto nível). O pedido pode ser curto.

Anexe `lincc_bundle.py` e o caso `.ANA`, e escreva só o estudo.

---

## Exemplo

```
Anexei o lincc_bundle.py e a base BR2612PJ.ANA.

ESTUDO: entrada em operação da LT 500 kV Curral Novo do Piauí (6640) –
São João do Piauí 2 (45019), circuito 1.

Parte 1 — Verifique onde a contribuição de curto-circuito varia acima de 10%.

Parte 2 — Relatório de proteção da barra 6640 e da LT, com o empreendimento em
operação. Relacione para que serve cada grandeza no ajuste.
```

É isso. As funções de alto nível resolvem o resto:

```python
from lincc import AnaModel, impacto_entrada, relatorio_protecao, tabela_envelope

M = AnaModel("BR2612PJ.ANA")
impacto_entrada(M, [(6640, 45019, '1')])          # Parte 1
relatorio_protecao(M, 'barra', 6640)              # Parte 2
relatorio_protecao(M, 'linha', (6640, 45019, '1'))
```

## O que sai

**Parte 1** — as barras acima de 10%, com o tipo de defeito que governou:

| Barra | Nome | kV | Antes | Depois | Variação | Governou |
|---|---|---|---|---|---|---|
| 6640 | CURRAL-PI500 | 500 | 17,211 kA | 20,067 kA | **+16,6%** | 3F |
| 45019 | SJ.PI2-PI500 | 500 | 17,531 kA | 19,975 kA | **+13,9%** | 2FT |

Repare que em 45019 quem governa é a **bifásica-terra**, não a trifásica — motivo pelo qual
os quatro tipos são varridos sempre, e não só o 3F.

**Parte 2, linha** — Z₁, Z₀, `k0` (1,1900 − j0,3231), MVA nominal lido da base (2.568 MVA),
correntes nos dois terminais, varredura da falta com terminal remoto aberto (de close-in à
ponta), 8 cenários N-1 no terminal local, as 7 funções que o Submódulo 2.11 exige para
linha, e os 6 dados externos que faltam.

**Parte 2, barra** — envelope por bay nos 9 elementos, com o cenário de cada extremo, e
ICC_MIN de recomposição para o 87B (1,064 kA em 3F; 1,201 kA em 1FT).

## Para que serve cada grandeza

| Grandeza | Uso no ajuste |
|---|---|
| Máximo de fase | suportabilidade de disjuntor, esforços eletrodinâmicos, saturação de TC |
| Mínimo de fase | sensibilidade, pickup de 51, alcance de zonas |
| 3I₀ | funções de terra — 67N, 51N, 50/51R |
| ICC_MIN de recomposição | limite inferior do 87B, com a barra energizada por um só elemento |
| Z₁, Z₀, k0 | alcance das zonas de distância e compensação de sequência zero |
| Terminal remoto aberto | abertura sequencial de disjuntor; é a condição que dimensiona alcance |

## Se precisar de mais controle

As funções aceitam `limiar`, `kv_min`, `modo`, `kinds`, `n1` e `dados` (os valores externos
que você já tem). E os métodos do `Solver` continuam disponíveis para o que sair do padrão.
Guia completo: `lincc.orientacao()`.
