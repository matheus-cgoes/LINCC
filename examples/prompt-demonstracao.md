# Exemplo de uso

O protocolo de trabalho está no próprio código, então o pedido pode ser curto. Anexe
`lincc_bundle.py` e o caso `.ANA`, e descreva só o estudo.

---

## O pedido

```
Anexei o lincc_bundle.py e a base BR2612PJ.ANA.

ESTUDO: entrada em operação da LT 500 kV Curral Novo do Piauí (6640) –
São João do Piauí 2 (45019), circuito 1.

Parte 1 — Verifique onde a contribuição de curto-circuito varia acima de 10%.

Parte 2 — Relatório de proteção da barra 6640 e da LT, com o empreendimento em
operação. Relacione para que serve cada grandeza no ajuste.
```

## O que sai

### Parte 1 — impacto da entrada

| Barra | Nome | kV | Antes | Depois | Variação | Governou |
|---|---|---|---|---|---|---|
| 6640 | CURRAL-PI500 | 500 | 17,211 kA | 20,067 kA | +16,6% | 3F |
| 45019 | SJ.PI2-PI500 | 500 | 17,531 kA | 19,975 kA | +13,9% | 2FT |

Duas barras ultrapassam o gatilho de 10%, e são os terminais da linha nova — os estudos de
proteção dessas duas precisam de revisão.

Repare que em 45019 quem governa é a bifásica-terra, não a trifásica. É por isso que os
quatro tipos são varridos sempre.

### Parte 2 — relatório de proteção

**Da linha:** impedâncias Z₁ e Z₀, fator k₀, potência nominal lida da base, correntes nos
dois terminais, varredura da falta com terminal remoto aberto — de close-in à ponta — e os
cenários N-1 no terminal local.

**Da barra:** envelope por bay nos nove elementos, com a maior e a menor corrente de fase e
de terra em cada vão e o cenário de cada extremo, mais a corrente mínima de recomposição
para o diferencial de barra.

Em ambos, as funções que o Submódulo 2.11 exige e a lista do que falta para parametrizar —
relação de TC, placa, carga máxima — que o agente reporta em vez de estimar.

### Para que serve cada grandeza

| Grandeza | Uso no ajuste |
|---|---|
| Máximo de fase | suportabilidade de disjuntor, esforços, saturação de TC |
| Mínimo de fase | sensibilidade, pickup de 51, alcance de zonas |
| 3I₀ | funções de terra: 67N, 51N, 50/51R |
| Corrente mínima de recomposição | limite inferior do 87B |
| Z₁, Z₀ e k₀ | alcance das zonas de distância e compensação de sequência zero |
| Terminal remoto aberto | abertura sequencial de disjuntor, que dimensiona alcance |

---

## Em código

Se preferir chamar direto:

```python
from lincc import AnaModel, impacto_entrada, relatorio_protecao, tabela_envelope

M = AnaModel("BR2612PJ.ANA")

impacto_entrada(M, [(6640, 45019, '1')])
relatorio_protecao(M, 'linha', (6640, 45019, '1'))
relatorio_protecao(M, 'barra', 6640)
```

As funções aceitam ajustes de escopo — limiar, tensão mínima, modo, tipos de defeito — e os
métodos do `Solver` continuam disponíveis para o que sair do padrão. Guia completo em
[`docs/uso.md`](../docs/uso.md) ou chamando `lincc.orientacao()`.

## Três pontos de atenção

**O sentido da comparação depende da base.** Se o equipamento já está representado, o
cenário "antes" é o contrafactual e os ramos são removidos. Se ainda não está, é preciso um
caso de horizonte que o contenha.

**Banco de três enrolamentos** é modelado com nó-estrela: para retirá-lo de um cenário,
todas as pernas entram na lista.

**O identificador de circuito é texto**, `'1'` e não `1`.
