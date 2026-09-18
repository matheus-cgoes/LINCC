# LINCC — prompt de demonstração

Exemplo completo para quem está usando o LINCC pela primeira vez. Cobre os dois pedidos mais
comuns: **impacto da entrada de um equipamento** e **relatório de curto-circuito de uma
barra** com as correntes que a proteção usa.

## Como usar

Anexe dois arquivos na conversa:

- `lincc_bundle.py` — o motor inteiro em um arquivo, sem instalação (está na raiz do
  repositório)
- `BR2612PJ.ANA` — ou o caso do horizonte do seu estudo

E cole o prompt abaixo. Substitua as barras e a linha pelo seu caso.

---

## O prompt

```
Anexei o lincc_bundle.py (motor de curto-circuito validado contra o ANAFAS) e a base
BR2612PJ.ANA.

O motor é a fonte de verdade: importe e use, não recrie de memória, não reescreva a
modelagem. Nenhum número deve vir de você — todos saem do motor.

    import sys; sys.path.insert(0, '.')
    from lincc import AnaModel, Solver, envelope_contribuicoes, tabela_envelope, branches_at
    M = AnaModel("BR2612PJ.ANA")
    S = Solver(M); S.factor()

Correntes saem em kA primários. Chame lincc.orientacao() se precisar do guia de modos,
tolerância e limitações.

ESTUDO: entrada em operação da LT 500 kV Curral Novo do Piauí (6640) – São João do
Piauí 2 (45019), circuito 1.

Parte 1 — IMPACTO NA EVOLUÇÃO DE CURTO-CIRCUITO

A LT já está representada nesta base. Portanto o cenário SEM o empreendimento é o
contrafactual: remova a LT e compare.

    S_com = Solver(M); S_com.factor()
    S_sem = Solver(M, drop_branches=[(6640, 45019, '1')]); S_sem.factor()

Varra todas as barras de 69 kV para cima e liste as que têm variação de corrente de
curto-circuito ACIMA DE 10%, em qualquer tipo de defeito (3F, 1FT, 2F, 2FT). Para cada
uma, informe: número, nome, tensão, corrente antes, corrente depois, variação percentual e
qual tipo de defeito governou.

Ordene pela maior variação. Ignore barras com corrente abaixo de 0,1 kA, onde o percentual
perde significado.

Diga explicitamente se alguma barra ultrapassa 10%, porque esse é o gatilho de revisão dos
estudos de proteção existentes.

Parte 2 — RELATÓRIO DE CURTO-CIRCUITO DA BARRA 6640

Com o empreendimento em operação. Monte duas tabelas.

(a) Proteção da LT 6640–45019

Para os quatro tipos de defeito, a corrente que o TC do vão de 6640 vê:

    - falta na barra local 6640;
    - falta na barra remota 45019;
    - falta close-in, terminal remoto aberto: S.line_end_open(6640, 45019, '1', 6640, kind, p=0.0);
    - falta na ponta, terminal remoto aberto: mesmo comando com p=1.0;
    - varredura da posição da falta: S.varredura_line_end_open(6640, 45019, '1', 6640).

Acrescente a impedância da linha (Z1 e Z0) e o fator k0 = (Z0L − Z1L)/(3·Z1L), que são os
insumos de alcance das zonas de distância.

(b) Proteção da barra 6640

    - envelope por bay, com o cenário de cada extremo:
      envelope_contribuicoes(M, 6640, solver=S_com), formatado com tabela_envelope();
    - corrente mínima de recomposição, para o 87B:
      recomposicao_87b(M, 6640).

Explique em uma linha para que serve cada grandeza no ajuste — máximo de fase para
suportabilidade e esforços, mínimo para sensibilidade, 3I0 para as funções de terra,
recomposição para o limite inferior do 87B.

REGRAS

- Não invente dado que não está na base. Se faltar relação de TC, ajuste de IED, placa de
  equipamento ou capacidade de interrupção, diga o que falta em vez de estimar.
- Declare qual modo foi usado. O padrão ('completo') inclui a contribuição de eólicas e
  fotovoltaicas conectadas por conversor e exige validar_completo(); para o Thévenin puro
  use modo='sincronas'. Não misture os dois num mesmo critério.
- Responda em português técnico, direto, com as tabelas e uma síntese ao final.
```

---

## O que esperar

Rodando na base `BR2612PJ`, o impacto sai assim:

| Barra | Nome | kV | Sem a LT | Com a LT | Variação |
|---|---|---|---|---|---|
| 6640 | CURRAL-PI500 | 500 | 17,211 kA | 20,067 kA | **+16,6%** |
| 45019 | SJ.PI2-PI500 | 500 | 18,953 kA | 21,549 kA | **+13,7%** |

Só os dois terminais ultrapassam 10% — as duas barras cujos estudos de proteção precisam
ser revisados. A barra 6640 tem 9 elementos incidentes, que é o que o envelope percorre.

---

## Três coisas que travam quem começa

**O sentido da comparação depende da base.** Se a LT **já está** na base (caso do
`BR2612PJ`), o cenário sem o empreendimento é o contrafactual — removem-se os ramos. Se
**ainda não está** (caso do `BR2812PI`, onde a barra 45019 nem existe), é preciso inserir a
LT ou usar um caso de horizonte que a contenha. Confira antes:

```python
45019 in M.bus_kv
[b for b in M.branches if {b['bf'], b['bt']} == {6640, 45019}]
```

**Banco de três enrolamentos não se remove por um ramo.** O transformador é modelado com nó
estrela fictício; para retirá-lo do cenário é preciso remover **todas** as pernas:

```python
Solver(M, drop_branches=[(AT, NO_ESTRELA, '3'), (BT, NO_ESTRELA, '3')])
```

**O identificador de circuito é string.** `'1'`, não `1`.

---

## Depois de rodar

Com o relatório em mãos, os pedidos que seguem naturalmente:

- ajuste das zonas de distância, a partir de Z1, k0 e das menores impedâncias adjacentes;
- pickup e temporização do 51 e do 67N, com as curvas de `lincc.curvas`;
- verificação do escopo de proteção contra o Submódulo 2.11, com `lincc.sm211`;
- varredura N-1, que o `envelope_contribuicoes` já faz para a barra e pode ser estendida.

Para os critérios que dependem de carregamento — pickup do 87B acima da corrente de carga,
SOTF acima do carregamento máximo — é preciso a base de fluxo de potência (`.PWF`), lida por
`PwfModel`.
