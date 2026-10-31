# Sprint 05: Produtos, aposentar o modelo legado `Produto` em favor de `SkuRecarga`

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), a seção 5.1 de `docs/GUIA_MODULOS_BAROS.md` e o item 2.4 da "FASE 2" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.
**Branch:** `sprint-05/produtos-legado-sku` a partir de `sprint-04/produtos-granel`.

## Objetivo
O que se vende é o `SkuRecarga` (gás × modelo de cilindro, com dados fiscais). O modelo `produtos.Produto` (legado) continua referenciado em vários lugares e confunde o catálogo, o estoque e o fiscal. Esta sprint migra todos os usos para `SkuRecarga` **sem perder histórico**, e deixa `Produto` como somente leitura.

## Onde `Produto` ainda aparece (confirme com `grep -rn "Produto\b" --include=*.py`)
- `vendas/models.py` (`ItemVenda.produto`, ao lado de `ItemVenda.sku`), `vendas/serializers.py`, `vendas/services/status.py`.
- `logistica/models.py` (`ValidacaoCarga.produto`, `SinistroItemCarga.produto`), `logistica/services/validacao_carga.py`, `logistica/services/seguros_sinistros.py`, `logistica/views.py`, `logistica/services/anp.py` (verifique se é outro "produto", de combustível; nesse caso, não mexa).
- `financeiro/models.py` e `financeiro/contabilizacao.py`.
- `produtos/services/estoque_produto.py` (aceita `sku` **ou** `produto`).
- API `/produtos/api/` (`ProdutoViewSet`): nenhuma tela usa mais, pois o catálogo foi refeito sobre `/produtos/api/catalogo/skus/`.

## Tarefas

### 05.1 Inventário (antes de mudar código)
- Liste no relatório cada uso de `Produto`, dizendo o que ele significa ali e qual o substituto. Se algum uso **não** tiver equivalente em `SkuRecarga`, pare e documente sem migrar.

### 05.2 Migração de dados
- Migração de dados (`RunPython`) que, para cada `Produto` existente, encontra ou cria o `SkuRecarga` correspondente (casando nome, capacidade e unidade) e preenche `sku` onde só havia `produto` (`ItemVenda`, `ValidacaoCarga`, `SinistroItemCarga`, movimentos de estoque). Ela precisa ser **idempotente** e **reversível**, e não pode apagar `Produto`.
- Casos que não casarem vão para um relatório em `docs/migracao_produto_para_sku.csv`. Grave o arquivo **só se houver pendências** e nunca durante os testes (veja o que foi feito na migração `produtos/0014`).

### 05.3 Código
- Todo código novo e as telas passam a usar `sku`. Os serializers de escrita deixam de aceitar `produto` (devolvem 400 com a mensagem "use sku").
- Os serializers de leitura continuam expondo `produto` como somente leitura, para histórico.
- `ProdutoViewSet` passa a ser `ReadOnlyModelViewSet`.
- No admin do Django, marque `Produto` como "(legado)".

### 05.4 Vendas e logística
- O modal de nova venda (`vendas/templates/vendas/index.html` e `vendas/static/vendas/js/index.js`) e a validação de carga, se escolherem item por `Produto`, passam a listar SKUs (`/produtos/api/catalogo/skus/?ativo=1`). Faça **só a troca da fonte de dados**: o redesign dessas telas é das Sprints 06 e 07.

## Critérios de aceite
- `grep` por `produto=` em código de escrita (fora de migrações e testes de histórico) não encontra criação nova de `Produto`.
- Vendas, faturamento (baixa de estoque e CPV) e contabilização continuam funcionando com SKU.
- Suíte verde.

## Testes obrigatórios
- A migração de dados: idempotente (rodar duas vezes não duplica) e reversível.
- Criar venda com `produto` responde 400; com `sku` responde 201.
- Faturar uma venda com SKU baixa o estoque uma única vez (o teste existente em `vendas/tests.py` deve continuar passando).

## Fora do escopo
Redesign de Vendas (Sprint 06).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_05.md`.
