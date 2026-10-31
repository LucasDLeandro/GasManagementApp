# Sprint 12: Fiscal, telas completas e unificação do app Faturamento

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, as seções 9 e 10 de `docs/GUIA_MODULOS_BAROS.md`, a "FASE 6" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md`, as seções 11A e 11B de `docs/DECISOES_PENDENTES.md` e `docs/adr/ADR-042-emissao-fiscal.md`.
**Branch:** `sprint-12/fiscal` a partir de `sprint-11/financeiro-contabil`.

> ⚠️ **Decisão do dono do projeto antes de começar:** qual gateway fiscal (ex.: Focus NFe) e qual PSP serão usados em produção (`DECISOES_PENDENTES` 10A.1 e 11A.1). Se não estiver decidido, **implemente contra o adaptador já existente** (`obter_emissor_fiscal` em `fiscal/services/nfe_venda_service.py`) em modo homologação, sem credencial real, e registre no relatório.

## Objetivo
1. Ter **uma única fonte de verdade** para NF-e (`fiscal.DocumentoFiscal`) e para cobrança (cobrança do Financeiro), aposentando o app `faturamento` (Sprint 7 antiga).
2. Dar tela a todo o Fiscal (hoje `templates/fiscal/index.html` só lista e cancela NF-e).

## O que já existe
- **fiscal:** 9 recursos no router (`configuracoes`, `regras-tributarias`, `documentos`, `inutilizacoes`, `movimentos-comodato`, `configuracoes-mdfe`, `documentos-entrada`, `apuracoes`, `ordens-recarga`) e serviços em `fiscal/services/` (motor tributário, numeração, NF-e de venda, eventos, comodato, locação, transporte, entrada XML, apuração, recarga de terceiros, certificado).
- **faturamento:** `NotaFiscal`, `FaturaCobranca`, `ConfiguracaoFiscalTenant`, webhooks `webhooks/gateway/` e `webhooks/nfe/`, link público `cobranca/<uuid>/`. `financeiro.MovimentoConta.baixa` aponta para `faturamento.FaturaCobranca`.
- **Rotas duplicadas:** `config/urls.py` inclui `fiscal.urls` em `api/fiscal/` e em `fiscal/`, e o próprio `fiscal/urls.py` inclui o router duas vezes (`api/` e `''`). O menu usa o namespace `fiscal:`.

## Tarefas

### 12.1 Rotas
- Fiscal fica com as páginas em `/fiscal/...` e a API em `/fiscal/api/...`. Remova os includes duplicados e atualize todos os `fetch`/`{% url %}` (procure `/api/fiscal/` em JS e templates). Os testes existentes devem continuar passando (ajuste só as URLs neles, se precisar).

### 12.2 Unificação (com migração de dados reversível)
- `faturamento.NotaFiscal` → `fiscal.DocumentoFiscal` (histórico migrado; o modelo antigo fica somente leitura).
- `faturamento.FaturaCobranca` → cobrança do Financeiro por parcela. Ajuste `MovimentoConta.baixa` e o link público de cobrança (mantenha a URL antiga redirecionando).
- Os webhooks passam a ser tratados pelo Fiscal (NF-e) e pelo Financeiro (cobrança), **mantendo** a validação HMAC com `hmac.compare_digest`.
- Ao final, o app `faturamento` só guarda os modelos legados de leitura e as migrações. Documente no relatório o que falta para removê-lo de vez.

### 12.3 Telas do Fiscal (submenu)
- **Configuração por filial:** upload do certificado A1 (senha *write-only*, cifrada; mostrar validade e alerta de vencimento), série e ambiente.
- **Regras tributárias:** lista, editor por especificidade (UF, NCM, operação, CFOP...) e simulador "qual regra se aplica a este item".
- **Documentos emitidos:** filtros, detalhe (itens, tributos, eventos), DANFE/XML, cancelar (dentro do prazo de 11A.2) e carta de correção.
- **Emitir NF-e a partir da venda:** botão no drawer da venda (Sprint 06), fila de rejeitadas com o motivo e reenvio. **Bloqueio de gás medicinal sem laudo de CQ liberado** (11B.5) visível na tela.
- **Comodato fiscal:** remessas e retornos e o relatório de divergências.
- **MDF-e/CT-e:** emitir, encerrar e alerta de MDF-e aberto.
- **Notas de entrada:** importar XML → conferir → gerar título a pagar.
- **Apuração mensal** (ABERTO → FECHADO → GUIA_GERADA).
- **Recarga de terceiros** em kanban (RECEBIDO → EM_ENVASE → ENVASADO → DEVOLVIDO → FATURADO).
- **Numeração/inutilização** e **lote de XMLs para o contador**.

## Critérios de aceite
- Uma única tabela de NF-e e um único fluxo de cobrança em uso; nenhum código novo importa modelos de `faturamento` para escrita.
- Nenhum segredo (senha do certificado, token do gateway) sai em API ou HTML.
- Suíte verde (incluindo `fiscal/tests/*` e `faturamento/tests/*`).

## Testes obrigatórios
- Migração de `NotaFiscal` e `FaturaCobranca`: idempotente e reversível.
- Webhook com assinatura inválida responde 401/403; com assinatura válida atualiza o documento ou a parcela.
- Emissão de gás medicinal sem laudo liberado é bloqueada.
- Renderização das páginas.

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_12.md`.
