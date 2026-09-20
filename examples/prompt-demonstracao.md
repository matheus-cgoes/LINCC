# Exemplo de uso

Como fica um estudo do começo ao fim, sem escrever uma linha de código.

---

## O que anexar

O arquivo `lincc_bundle.py` (está na raiz deste repositório), o seu caso `.ANA` e os
relatórios do ANAFAS desse mesmo caso.

## O pedido

```
Anexei o lincc_bundle.py, a base BR2612PJ.ANA e os relatórios do ANAFAS desse caso.

ESTUDO: entrada em operação da LT 500 kV Curral Novo do Piauí (6640) –
São João do Piauí 2 (45019), circuito 1.

Parte 1 — Verifique onde a contribuição de curto-circuito varia acima de 10%.

Parte 2 — Relatório de proteção da barra 6640 e da LT, com o empreendimento em
operação. Relacione para que serve cada grandeza no ajuste.
```

Não é preciso dizer quais tipos de defeito considerar, quais contingências montar nem em
que formato responder. Isso já está definido dentro da ferramenta.

---

## O que sai

### Parte 1 — impacto da entrada

| Barra | Nome | kV | Antes | Depois | Variação | Defeito |
|---|---|---|---|---|---|---|
| 6640 | CURRAL-PI500 | 500 | 17,211 kA | 20,067 kA | +16,6% | trifásico |
| 45019 | SJ.PI2-PI500 | 500 | 17,531 kA | 19,975 kA | +13,9% | bifásico-terra |

Duas barras ultrapassam o gatilho de 10%, e são os terminais da linha nova — os estudos de
proteção dessas duas precisam de revisão.

Repare que em 45019 quem governa é a falta bifásica-terra, não a trifásica. Por isso os
quatro tipos são varridos sempre, mesmo quando o pedido não menciona.

### Parte 2 — relatório de proteção

**Da linha:** impedâncias de sequência positiva e zero, fator de compensação de terra,
potência nominal lida da base, correntes nos dois terminais, varredura da falta com o
terminal remoto aberto — do defeito junto ao disjuntor até a ponta oposta — e os cenários
de contingência simples no terminal local.

**Da barra:** para cada um dos nove vãos, a maior e a menor corrente de fase e de terra,
com o cenário em que cada extremo ocorreu, mais a corrente mínima de recomposição para o
diferencial de barra.

Em ambos, as funções que o Submódulo 2.11 exige para o equipamento e a lista do que falta
para parametrizar — relação de TC, placa, carga máxima — que o agente pede em vez de
estimar.

### Para que serve cada grandeza

| Grandeza | Uso no ajuste |
|---|---|
| Máximo de fase | suportabilidade de disjuntor, esforços, saturação de TC |
| Mínimo de fase | sensibilidade, pickup das unidades temporizadas, alcance de zonas |
| Corrente de terra (3I₀) | funções direcionais e de sobrecorrente de neutro |
| Corrente mínima de recomposição | limite inferior do diferencial de barra |
| Impedâncias e fator de compensação | alcance das zonas de distância |
| Terminal remoto aberto | abertura sequencial de disjuntor, que dimensiona alcance |

---

## Pedidos seguintes

A conversa continua: com o relatório em mãos, dá para pedir o ajuste das zonas de distância,
o pickup e a temporização das unidades de sobrecorrente, a verificação do escopo de proteção
contra o Submódulo 2.11, ou a varredura de contingências em outras barras.

Se faltar algum dado que nenhuma base contém, o agente informa qual é e para que serve, em
vez de adotar um valor por conta própria.

## Três pontos de atenção

**O sentido da comparação depende da base.** Se o equipamento novo já está representado no
caso, o cenário "antes" é obtido retirando-o. Se ainda não está, é preciso um caso de
horizonte que o contenha — vale conferir antes de pedir o estudo.

**Bancos de transformadores** são representados com um ponto interno adicional; retirá-los
de um cenário exige remover todas as conexões, e o agente cuida disso.

**Identificação de circuito** acompanha o número do caso: informe o circuito como aparece no
diagrama ou no arquivo.
