# LINCC — Linguagem Natural em Curto-Circuito

Motor de curto-circuito para sistemas de transmissão, em Python. Lê casos em formato `.ANA`, monta as
redes de sequência positiva e zero e calcula equivalentes de Thévenin, correntes de falta e grandezas
de apoio a estudos de proteção por fatoração LU esparsa.

O projeto nasceu de um experimento de método: **o motor foi construído e depurado inteiramente por
diálogo em linguagem natural com um agente de IA**, sob uma regra fixa — nenhum número vem do modelo de
linguagem. Todo valor sai de álgebra linear determinística e auditável; o agente decide o que calcular,
diagnostica divergências e propõe correções, que só são aceitas após validação contra a referência
oficial do setor. A validação final foi barra a barra, nas 15,6 mil barras de um caso real de
planejamento, com critério de erro individual — não erro médio.

> **Não substitui ferramenta homologada.** O papel normativo dos programas oficiais do setor permanece
> integralmente. Este motor serve como segundo caminho de cálculo — útil justamente porque tem origem
> independente — e como base de automação. Leia a
> [isenção de responsabilidade](#isenção-de-responsabilidade) antes de qualquer uso.

---

## Estado da validação

| Métrica (caso de referência, 15.627 barras) | Resultado |
|---|---|
| Sequência positiva, erro individual por barra < 1% | **99,4%** das barras (mediana 0,021%) |
| Sequência zero, erro individual por barra < 1% | **98,8%** das barras (mediana 0,019%) |
| Barras de 500 kV, contra seção de alta precisão do relatório | 100% < 1% em ambas as sequências |

O critério de aceitação é **erro individual por barra**. A média geral baixa é fácil de obter e não
serve: basta que a barra errada seja justamente a do vão em estudo.

Resíduo conhecido: barras de fronteira internacional, cujo valor depende do equivalente de rede
externo, e erros relativos elevados sobre valores absolutos ínfimos — que são quantização do relatório
de referência, não do solver.

## Instalação

```bash
git clone https://github.com/<usuario>/lincc.git
cd lincc
pip install -e .
```

Python 3.10+. Dependências: `numpy`, `scipy`. Para rodar os testes: `pip install -e ".[dev]"`.

---

## Componentes

Quatro módulos, cada um correspondendo a um estágio do pipeline.

```
      arquivo .ANA
           |
           v
   +------------------+
   |  _base.py        |  escala numerica, sentinelas de infinito, 3*Zn
   |  helpers         |
   +--------+---------+
            v
   +------------------+
   |  model.py        |  AnaModel: colunas fixas -> objetos de rede
   |  parser          |  (barras, ramos, geradores, shunts, mutuas, reatores)
   +--------+---------+
            v
   +------------------+
   |  solver.py       |  Solver: Ybus seq+ e seq0 -> LU -> Zbus sob demanda
   |  Ybus + LU       |  faltas, contingencia, grandezas de protecao
   +--------+---------+
            v
   +------------------+
   |  __init__.py     |  API publica
   +------------------+
```

### `_base.py` — helpers de leitura e conversão

Regras numéricas do formato, isoladas para poderem ser testadas sozinhas.

| Função | O que faz |
|---|---|
| `num(s)` | Campo do arquivo para float. **Campo com ponto decimal vale direto; sem ponto, vale valor/100** (percentual com duas casas implícitas). `999999` e notação científica representam infinito |
| `zfin(r, x)` | Impedância complexa, retornando `None` quando qualquer parte é infinita (ramo aberto) |
| `zn3(rn, xn)` | Impedância de aterramento de neutro referida à sequência zero: `3·Zn` |
| `_nunop(s)` (interno) | Número de unidades **operativas**, de um campo que declara instaladas e operativas |
| `SB` | Potência base, 100 MVA |

### `model.py` — `AnaModel`, o parser

Lê o arquivo de colunas fixas e produz as coleções de rede. Não faz cálculo elétrico.

```python
M = AnaModel("caso.ANA")

M.bus_kv      # {barra: tensão base}          M.bus_name  # {barra: nome}
M.bus_off     # barras marcadas como desligadas (removidas do caso)
M.branches    # ramos: L linha, T trafo, S cap. série (com conexões e aterramentos)
M.gens        # geradores síncronos           M.eol   # geração por inversor
M.shunts      # shunts de barra               M.zig   # transformadores de aterramento
M.svc         # compensadores estáticos       M.shl   # reatores / shunts de linha
M.mutuas      # acoplamentos de sequência zero entre trechos parciais
M.caps        # capacitores série
```

Pontos do formato que o parser trata e que costumam passar despercebidos: sentinela de fim de bloco
(`99999`, que não é barra elétrica), estado de equipamento (`CE = D` significa fora de serviço), número
de unidades operativas, e dependência do **lado** do registro para conexão e aterramento. Detalhe em
[`docs/formato-ana.md`](docs/formato-ana.md).

### `solver.py` — `Solver`, a Ybus e o cálculo

Monta as duas redes de sequência, fatora e responde consultas.

```python
S = Solver(M)
S.factor()          # fatoração LU — obrigatório antes de qualquer consulta
```

Atributos úteis após `factor()`: `S.YP` e `S.Y0` (matrizes esparsas), `S.IDXP` e `S.I0P`
(barra para índice), `S.luP` e `S.lu0` (fatorações).

### `__init__.py` — API pública

```python
from lincc import AnaModel, Solver, branches_at, recomposicao_87b
```

### `examples/validar_caso.py` — validação de um caso novo

Script de linha de comando, o passo obrigatório antes de usar um caso que ainda não foi validado:

```bash
python examples/validar_caso.py CASO.ANA RELATORIO.LST
```

Compara barra a barra contra o relatório da ferramenta de referência para o mesmo caso e lista as barras
acima do critério. Aceita `--limite`, `--piores` e `--secao`; retorna 0 se todas as barras passam.

### `ferramentas/gerar_bundle.py` — versão de arquivo único

Concatena o pacote em um `lincc_bundle.py` autocontido, para rodar sem instalar nada ou anexar em uma
sessão de trabalho:

```bash
python ferramentas/gerar_bundle.py
python -c "from lincc_bundle import AnaModel, Solver; print('ok')"
```

Sempre corrija no pacote e regenere — nunca o contrário.

### Árvore

```
src/lincc/        _base.py  model.py  solver.py  __init__.py
tests/            test_casos_sinteticos.py + cases/ (3 casos sintéticos + ESPERADO.md)
examples/         validar_caso.py
ferramentas/      gerar_bundle.py
docs/             formato-ana.md  mutuas.md  validacao.md
```

---

## Uso

### Inicialização em agentes de IA
Incluir arquivos lincc_bundle.py, caso .ANA e os relatórios de níveis e dados de curto-circuito anexados ao prompt. Abaixo prompt de referência:

```
Anexei o lincc_bundle.py (motor de curto-circuito validado), o caso .ANA e o relatório da ferramenta
de referência para o mesmo caso.

O motor é a FONTE DE VERDADE: não o recrie de memória. Meta: erro INDIVIDUAL por barra < 1% em Z1 e
Z0 — não erro médio, não faixa de 5%.

Passos, nesta ordem:
1. Rode o motor sobre o .ANA e fatore.
2. Extraia o gabarito da seção 'RELATORIO DE DADOS DE CURTO-CIRCUITO' do relatório, ANCORANDO na
   seção (começa no cabeçalho, termina no próximo 'RELATORIO DE'). Régua 0-based da linha de dados:
   NUM[1:7], Z1MOD[21:29], Z1ANG[30:38], Z0MOD[39:47], Z0ANG[48:56].
   Sem a âncora, linhas das seções de matriz Zbarra casam com o mesmo padrão e contaminam o gabarito.
3. Compare POR BARRA. Reporte %<1%, %<5%, mediana e estratificação por classe de tensão
   (500+, 230-345, 69-138, <69, kV=0).
4. Só então investigue as barras acima de 1%, uma a uma, pelo método abaixo.
5. Nas solicitações de cálculo de curto-circuito, sempre insira as contribuições de fontes conectadas por conversor (UFV, EOL, HVDC).

Não declare sucesso antes de bater contra o gabarito deste caso.
Anexei o lincc_bundle.py (motor de curto-circuito validado), o caso .ANA e o relatório da ferramenta
de referência para o mesmo caso.

O motor é a FONTE DE VERDADE: não o recrie de memória. Meta: erro INDIVIDUAL por barra < 1% em Z1 e
Z0 — não erro médio, não faixa de 5%. 

Passos, nesta ordem:
1. Rode o motor sobre o .ANA e fatore.
2. Extraia o gabarito da seção 'RELATORIO DE DADOS DE CURTO-CIRCUITO' do relatório, ANCORANDO na
   seção (começa no cabeçalho, termina no próximo 'RELATORIO DE'). Régua 0-based da linha de dados:
   NUM[1:7], Z1MOD[21:29], Z1ANG[30:38], Z0MOD[39:47], Z0ANG[48:56].
   Sem a âncora, linhas das seções de matriz Zbarra casam com o mesmo padrão e contaminam o gabarito.
3. Compare POR BARRA. Reporte %<1%, %<5%, mediana e estratificação por classe de tensão
   (500+, 230-345, 69-138, <69, kV=0).
4. Só então investigue as barras acima de 1%, uma a uma, pelo método abaixo.

Não declare sucesso antes de bater contra o gabarito deste caso.
```
Após essa inicialização, o chat estará pronto para solicitações.
Complementação adicional pode ser fornecida, por exemplo, introdução de aplicação para a qual será utilizado.

### Grandezas básicas

```python
from lincc import AnaModel, Solver

M = AnaModel("caso.ANA")
S = Solver(M); S.factor()

S.fault(BARRA, "3F")     # corrente de falta em kA primários, na base de tensão da barra
S.zth(BARRA)             # (Z1, Z2, Z0) em pu, base 100 MVA
```

`kind` aceita `"3F"` (trifásica), `"1FT"` (fase-terra), `"2F"` (bifásica) e `"2FT"`.

### Contingência: remoção de equipamento

Um banco de transformadores de três enrolamentos é modelado por nó-estrela fictício, então removê-lo
significa remover as **duas** pernas:

```python
S = Solver(M, drop_branches=[(BARRA_AT, NO_ESTRELA, "3"),
                             (BARRA_BT, NO_ESTRELA, "3")])
S.factor()
```

O identificador de circuito (`nc`) é **string**. Para geradores: `drop_gens=[barra, ...]`.
`branches_at(M, barra)` lista os ramos incidentes, útil para montar varreduras N-1.

Comparar o caso com e sem um equipamento novo dá a evolução de curto que dispara revisão de estudos de
proteção — envelope máximo em N-0 e mínimo sob N-1.

### Grandezas de apoio a estudos de proteção

| Método | Para que serve |
|---|---|
| `contribution(barra, kind)` | Passa-através por elemento incidente (87T), direto e reverso. A soma fecha por KCL com a corrente total |
| `branch_current(fbus, bf, bt, nc, kind)` | Corrente em **qualquer** ramo para falta em qualquer barra — incidente, remoto ou linha arbitrária |
| `bus_voltage(fbus, obus, kind)` | Tensões no relé, para impedância aparente de distância. Mútuas e capacitor série já estão na Ybus, logo sub e sobrealcance aparecem no resultado |
| `line_end_open(bf, bt, nc, closed, kind)` | Corrente no terminal fechado com o remoto aberto (abertura sequencial de disjuntor) |
| `fault_on_branch(bf, bt, nc, p, kind)` | Falta intermediária a fração `p` de um ramo série, por nó de falta paramétrico. Retorna a corrente na falta e em cada terminal |
| `fault_on_shunt(barra, p, kind)` | Falta intermediária em reator shunt — sensibilidade do diferencial do reator |
| `winding_ground_fault(barra, Zw, n)` | Curva de triagem de falta à terra em enrolamento (87REF) |
| `recomposicao_87b(M, barra)` | Corrente mínima com a barra energizada por um só elemento, para cada elemento energizante — o piso de sensibilidade do 87B |

Exemplo, falta na barra de baixa e o que o banco enxerga:

```python
S.fault(BARRA_BT, "1FT")                                       # corrente total na barra
S.contribution(BARRA_BT, "1FT")                                # parcela de cada elemento
S.branch_current(BARRA_BT, BARRA_BT, NO_ESTRELA, "3", "1FT")   # passa-através do banco
```

Exemplo, piso do 87B na recomposição:

```python
tabela, icc_min = recomposicao_87b(M, BARRA)
# tabela: corrente por elemento energizante; icc_min: o governante, por tipo de falta
```

### Limites de cada método

Estão nas docstrings, e dois merecem destaque aqui:

- **Falta intermediária em linha com acoplamento mútuo é aproximada** — a mútua não é resegmentada. O
  retorno traz `mutua_aprox` sinalizando a condição.
- **`winding_ground_fault` assume enrolamento uniforme** (FEM proporcional a `x`, impedância da seção
  proporcional a `x²`). A **forma** da curva é confiável e localiza a região crítica de sensibilidade;
  os valores absolutos dependem da impedância de placa e da hipótese. Ancore ao terminal rigoroso via
  `fault(barra, "1FT")`. Falta interna rigorosa exige a distribuição de espiras do fabricante.

Sem relação de TC, todas as correntes são **primárias**. Ao dispor dos TCs, refira ao secundário pela
relação e adote como corrente de base do estudo a nominal primária do TC — não a nominal do equipamento
protegido.

---

## Metodologia de validação

Duas regras, e a segunda é a que evita autoengano. Detalhe em
[`docs/validacao.md`](docs/validacao.md).

**Diagnóstico por corrente de terra nodal.** Quando uma barra excede o critério, a pergunta é física,
não estatística: por onde a corrente homopolar está escoando indevidamente?

```
V = Y0^-1 · e_k
I_terra = rowsum(Y0) · V
```

Os nós de maior magnitude apontam o elemento espúrio — shunt contado duas vezes, reator que deveria
estar desligado, caminho de terra criado por erro de leitura de coluna. Cada divergência numérica vira
uma hipótese verificável no registro cru do arquivo.

**Teste A/B global.** Toda hipótese é aplicada, o modelo reconstruído e o resultado medido pelo
percentual de barras abaixo de 1% em **toda** a rede — nunca na barra que motivou a investigação.
Correção que melhora uma barra e degrada centenas é rejeitada, ainda que a teoria pareça favorecê-la.
Sem essa regra, cada ajuste individual é sobreajuste ao caso de teste: o motor acerta o gabarito e erra
o próximo caso.

### Por que LU esparsa e não a inversa

O equivalente de Thévenin de cada barra é a diagonal de `Zbus = Y^-1`. Para 15,6 mil barras, `Y^-1` é
densa — da ordem de 2,4×10⁸ elementos complexos — enquanto `Y` tem cerca de 1,3×10⁵ não nulos.
Fatora-se `Y` uma vez, com ordenação que preserva esparsidade, e obtém-se cada coluna sob demanda
resolvendo dois sistemas triangulares para o vetor canônico:

```
Z_th,k = ek^T · Y^-1 · ek
```

O custo por barra é proporcional aos não nulos dos fatores, não a `n²`. É o método de vetores esparsos
(Tinney, Brandwajn e Chan, 1985), o mesmo fundamento das ferramentas do setor. A fatoração também é a
base natural das correntes de falta e da análise de contingências.

## Testes

```bash
pytest -q
```

Os testes usam **casos sintéticos** — redes pequenas, sem qualquer dado de terceiro, com resultado
deduzido analiticamente em [`tests/cases/ESPERADO.md`](tests/cases/ESPERADO.md):

- `caso1_radial.ANA` — gerador aterrado, linha e transformador YN-D. Verifica a topologia de sequência
  zero criada pelo delta: `Z0 = (0,30 + 0,05) ∥ 0,08 = j0,0651163 pu`.
- `caso2_mutuas.ANA` — duas linhas paralelas acopladas. Verifica a matriz primitiva de grupo
  (`Zeq = (Z0 + Zm)/2`) e funciona como **teste de regressão** do erro de identidade de segmento: se a
  chave do segmento ignorar o número do circuito, a mútua é descartada e `Z0` cai 20% sem lançar
  exceção alguma.

## Dados

**Este repositório não contém casos de rede reais.** Bases de planejamento, relatórios de ferramentas
licenciadas e dados operativos de instalações não são redistribuídos aqui. Se você tem acesso legítimo
a um caso real, valide localmente — mas não o inclua em pull request. O `.gitignore` bloqueia as
extensões correspondentes.

## Isenção de responsabilidade

Software distribuído "no estado em que se encontra", sem garantias, nos termos da licença. Resultados de
curto-circuito têm consequência direta sobre dimensionamento de equipamento, ajuste de proteção e
segurança de pessoas e instalações. Qualquer uso em aplicação real exige verificação independente por
profissional habilitado, contra ferramenta reconhecida e contra os dados de placa do projeto. Os autores
e contribuidores não respondem por decisões de engenharia tomadas a partir destas saídas.

## Marcas e interoperabilidade

`ANAFAS` é programa e marca de terceiro (CEPEL), citado aqui de forma nominativa apenas para identificar
o formato de arquivo lido e a referência utilizada em validação. Este projeto não é afiliado,
patrocinado nem endossado pelo CEPEL. Nenhum código daquele programa foi utilizado, inspecionado ou
descompilado: o motor foi escrito a partir da teoria clássica de componentes simétricas e análise nodal,
e a leitura do formato tem finalidade exclusiva de interoperabilidade.

## Titularidade e independência

Projeto pessoal, desenvolvido fora da jornada de trabalho, com recursos próprios do autor e sem
utilização de infraestrutura, dados ou informação de qualquer empregador — hipótese do art. 4º, §2º, da
Lei 9.609/98, em que a titularidade é exclusiva do desenvolvedor. O projeto não representa a posição de
nenhuma instituição nem foi produzido no âmbito de atividade funcional.

## Licença

Apache License 2.0 — veja [LICENSE](LICENSE).

## Citação

```bibtex
@software{lincc,
  title  = {LINCC: motor de curto-circuito construído por linguagem natural,
            com validação barra a barra},
  author = {Góes, Matheus Cassiano de},
  year   = {2026},
  url    = {https://github.com/<usuario>/lincc}
}
```
