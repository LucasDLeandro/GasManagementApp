# Sprint 11: Financeiro, fechamento contábil e gestão (DRE, orçamento, PDD, depreciação)

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, as seções 8.1 e 8.5 de `docs/GUIA_MODULOS_BAROS.md` e a seção 10B de `docs/DECISOES_PENDENTES.md` (presunção de lucro, faixas de PDD, alçada de lançamento manual).
**Branch:** `sprint-11/financeiro-contabil` a partir de `sprint-10/financeiro-cobranca-credito`.

## Objetivo
Dar tela ao fechamento contábil e à gestão, e corrigir três problemas de modelagem conhecidos.

## O que já existe (backend)
- `dre_service.py` (`api/dre/`), `orcamento_service.py` (`orcamentos`), `pdd_service.py` (`parametros-pdd`), `depreciacao_service.py` (`depreciacao`, `revisoes-vida-util`), `lancamento_manual_service.py` (`lancamentos-manuais`), `tributario_service.py` (`parametros-tributarios`), `snapshot_service.py` (`saldos-mensais`), `exportacao_service.py` (`api/exportacao-contabil/`), `parametros-gestao`.
- Permissão `CanViewDRE` em `core/permissions.py`.

## Tarefas

### 11.1 DRE (`/financeiro/dre/`)
- DRE por competência (mês, trimestre e ano), com as 12 linhas, comparação com o orçamento (realizado × orçado × variação) e com o período anterior; filtros por centro de custo, veículo e gás; exportação CSV. Só quem tem `CanViewDRE`.

### 11.2 Orçamento (`/financeiro/orcamento/`)
- Grade mês × conta (editável em linha, com totais por linha e coluna), importação CSV com pré-visualização de erros e aprovação (RASCUNHO → APROVADO; aprovado não se edita).

### 11.3 Fechamento do mês (`/financeiro/fechamento/`)
- Página com um checklist em etapas: rodar a **depreciação** do mês → calcular a **PDD** (com o detalhamento por faixa de atraso) → **provisão tributária** (IRPJ/CSLL) → conferir **pendências de contabilização** → **fechar o período**.
- Cada etapa mostra o resultado e os lançamentos gerados e permite estornar.

### 11.4 Lançamentos manuais
- Criar lançamento de partidas dobradas (débito = crédito validado ao vivo), aprovação por alçada (10B.3), rejeição com motivo e importação de provisões CSV.

### 11.5 Parâmetros (`/financeiro/configuracoes/`)
- Uma página com abas: financeiros, tributários, de gestão, de PDD e de crédito (este último reaproveitando o da Sprint 10). Só ADMIN.

### 11.6 Correções de modelagem
1. **Dois fornecedores:** `financeiro.Fornecedor` e `logistica.Fornecedor` (oficinas). Unifique em `financeiro.Fornecedor` com o campo `tipo` (incluindo `OFICINA`), com migração de dados que preserva os vínculos de `OrdemServico`, `PlanoManutencao` e `FaturaConsolidadaPosto`. A migração precisa ser reversível. Ajuste as telas de logística e financeiro.
2. **Dois preços de combustível:** `financeiro.PrecoReferenciaCombustivel` e `logistica.PrecoCombustivelReferencia`. Mantenha um só (o de logística, que tem a importação ANP), migre os dados e ajuste o antifraude de despesas de campo para usá-lo.
3. **Compra de imobilizado sem lançamento:** `financeiro/contabilizacao.py` tem o handler `compra_imobilizado`, mas **nenhum fluxo publica o evento**. Publique-o (`core.eventos.publicar`) quando um cilindro próprio com `valor_aquisicao` for cadastrado (`produtos/services/cadastro_cilindro.py`) ou um `LoteAquisicaoCilindros` for criado, **sem contabilizar duas vezes** (lote × cilindros do lote; a contabilização já é idempotente por `origem_id`, então use uma origem consistente).

## Critérios de aceite
- O fechamento de um mês completo é possível pela tela.
- As migrações dos itens 1 e 2 são idempotentes e reversíveis, e as telas continuam funcionando.
- Suíte verde (incluindo `financeiro/tests/test_sprint10b*`).

## Testes obrigatórios
- DRE bloqueada sem `CanViewDRE`.
- Lançamento manual desbalanceado responde 400; aprovação por alçada.
- Unificação de fornecedor: migração preserva os FKs (teste de migração com `MigrationExecutor` ou dados criados antes da migração).
- `compra_imobilizado` publicado uma única vez por aquisição.

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_11.md`.
