# Scripts

Dois scripts acompanham o pacote. Nenhum deles é necessário para usar a biblioteca — `validar_caso.py`
é o procedimento de aceitação de um caso novo, e `gerar_bundle.py` produz a versão de arquivo único.

---

## `examples/validar_caso.py`

Compara o motor contra os relatórios do ANAFAS, barra a barra. É o passo obrigatório antes de usar um
caso que você ainda não conferiu: o parser lê o formato, não um caso específico, e um tipo de registro
que não apareça no caso de referência é ignorado em silêncio — o número sai, e sai errado.

### Uso

```bash
python examples/validar_caso.py CASO.ANA RELATORIO.LST [OUTRO.LST ...]
```

| Argumento | Padrão | Efeito |
|---|---|---|
| `caso` | — | Arquivo `.ANA` |
| `relatorios` | — | Um ou mais relatórios. As seções são procuradas em todos |
| `--limite` | `1.0` | Critério de erro individual por barra, em % |
| `--piores` | `20` | Quantas barras acima do critério listar por grandeza |
| `--com-deol` | desligado | Compara os níveis em kA via `fault_fc`, incluindo geradores conectados por conversor |

Código de retorno: `0` se todas as comparações decisivas passam, `1` caso contrário, `2` se nenhuma
seção conhecida foi encontrada. Serve em pipeline.

### Quais relatórios exportar do ANAFAS

| Relatório | Papel |
|---|---|
| **Impedâncias de barra** | Indispensável. Z₁, Z₀ e (Z₀+Z₂) com 10 decimais — o gabarito de verdade. Dele se derivam os três níveis |
| **Níveis de curto-circuito** | Indispensável para validar `fault_fc`: é o único que inclui a contribuição dos conversores |
| Dados de curto-circuito | Dispensável. Repete Z com 4 decimais e traz MVA já derivável dos outros |

As três seções podem estar no mesmo arquivo ou em arquivos separados. Exporte sempre o de impedâncias
de barra, mesmo quando o estudo pedir só níveis: é ele que permite separar erro de cálculo de
arredondamento de relatório.

### O que o script compara

1. **Impedância de Thévenin** — Z₁ e Z₀ contra a seção de alta precisão e contra a de 4 decimais.
2. **Níveis em kA** — contra o relatório de níveis, via `fault` ou `fault_fc`.
3. **Níveis em MVA** — trifásico, monofásico e bifásico-terra, calculados a partir de Z.
4. **Coerência Z₂ = Z₁** — extraindo Z₂ de (Z₀+Z₂) − Z₀ em complexo.

Para cada um: percentual abaixo do critério, percentual abaixo de 5%, mediana, máximo, e
estratificação por classe de tensão.

### Veredito

Só as comparações **decisivas** definem o código de retorno:

- Z₁ e Z₀ na seção de alta precisão;
- níveis em MVA;
- níveis em kA, somente com `--com-deol`.

As demais aparecem marcadas como informativas. A razão é concreta: a seção de 4 decimais em pu tem
quantização que, sozinha, já excede 1% em barras de impedância baixa — incluí-la no veredito faria o
script reprovar sempre, mesmo com o motor exato. E os níveis em kA via `fault` divergem por construção
onde há gerador conectado por conversor, porque o relatório os inclui e `fault` não.

Sem a seção de impedâncias no relatório, a de 4 decimais assume o papel de gabarito e o script avisa
que o julgamento perdeu resolução.

### Duas armadilhas de leitura que o script trata

Ambas foram encontradas por divergência numérica, não por documentação, e ambas produzem número
plausível e errado:

**Cabeçalho acentuado.** O relatório de níveis é anunciado como `RELATÓRIO DE NÍVEIS`, com acento.
Delimitar seção procurando só por `RELATORIO` faz a leitura de uma seção atravessar para dentro dele e
capturar linhas alheias — foi assim que 15.627 barras viraram 16.516 num teste.

**Estouro de campo.** Valor mais largo que a coluna invade o campo anterior:

```
...2847100000.0445903836
```

O valor é `100000,0445903836`, mas a leitura por coluna fixa devolve `00000,0445903836` — perde o
dígito inicial e erra por ordens de grandeza. Por isso cada campo é lido da borda direita do campo
anterior até a sua própria borda direita, e não por posição absoluta.

### Interpretando o resultado

Divergência acima do critério não é automaticamente erro do solver. Antes de tratar como tal:

- **Erro disperso e pequeno** é quantização do relatório. Reavalie na seção de alta precisão.
- **Erro concentrado numa classe de barras** — todas de uma tensão, ou todas com certo equipamento —
  é regra de leitura errada. Essa é a assinatura que interessa.
- Para localizar o elemento responsável, calcule a corrente de terra nodal
  `I_terra = rowsum(Y0)·V`, com `V = Y0⁻¹·e_k`. Os nós de maior magnitude apontam o culpado.
- Valide qualquer correção medindo o percentual abaixo do critério sobre **toda** a rede, nunca sobre
  a barra que motivou a investigação.

Detalhe do método em [`validacao.md`](validacao.md).

### Exemplo de saída

```
Lendo caso.ANA ...
  barras=15627 ramos=19318 geradores=2377 shunts=1866 mútuas=3901 reatores de linha=704
Montando as redes de sequência e fatorando ...
  Y1 (15627, 15627) nnz=51965 | Y0 (18739, 18739) nnz=131033
Gabarito: impedâncias=15627 barras | níveis em kA=15627 | dados de curto=15627

IMPEDÂNCIA DE THÉVENIN — erro individual por barra
  Z1 (alta precisão)       n= 15627  <1%=100.000%  <5%=100.000%  mediana=0.0000%  máx=0.000%
  Z0 (alta precisão)       n= 13193  <1%= 99.992%  <5%= 99.992%  mediana=0.0000%  máx=0.010%
...
VEREDITO: aprovado nas comparações decisivas.
```

---

## `ferramentas/gerar_bundle.py`

Concatena os quatro módulos do pacote em um único arquivo autocontido, `lincc_bundle.py`. Serve para
rodar sem instalar nada, ou para anexar o motor inteiro numa sessão de trabalho com agente de IA.

```bash
python ferramentas/gerar_bundle.py
python ferramentas/gerar_bundle.py -o /caminho/lincc_bundle.py
```

Conferência rápida depois de gerar:

```bash
python -c "from lincc_bundle import AnaModel, Solver; print('ok')"
```

O bundle é a mesma lógica do pacote: docstring de módulo e imports internos são removidos de cada
arquivo, e um cabeçalho comum é adicionado. A API exportada é idêntica.

**Corrija sempre no pacote e regenere.** Editar o bundle e esquecer o pacote é o jeito mais direto de
perder a correção na próxima geração. Pelo mesmo motivo, o bundle **não** deve ser versionado dentro
de `src/lincc/`: ele duplicaria o código do próprio pacote e seria instalado como módulo. O lugar dele
é a raiz do repositório (ignorada pelo git) ou os releases.

---

## Como os testes se relacionam com os scripts

`pytest` cobre o motor com três casos sintéticos, pequenos o bastante para conferência manual e com
resultado deduzido analiticamente em [`../tests/cases/ESPERADO.md`](../tests/cases/ESPERADO.md).
Não substituem `validar_caso.py`: os testes provam que o motor calcula certo o que sabe calcular; a
validação contra o ANAFAS prova que ele leu o **seu** caso corretamente.

```bash
pytest -q          # 11 testes, segundos
```
