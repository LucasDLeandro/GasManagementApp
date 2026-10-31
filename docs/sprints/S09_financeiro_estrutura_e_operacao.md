# Sprint 09: Financeiro, dividir o painel e redesenhar a operação diária

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 8 de `docs/GUIA_MODULOS_BAROS.md`, a "FASE 5" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md` e as seções 9A, 9B e 9C de `docs/DECISOES_PENDENTES.md`.
**Branch:** `sprint-09/financeiro-estrutura` a partir de `sprint-08/logistica-frota`.

## Objetivo
`templates/financeiro/dashboard.html` (cerca de 1.570 linhas, 25 `alert`/`confirm`) concentra 14 abas. Esta sprint o divide em páginas com submenu e redesenha as telas que **já existem**: contas, títulos, baixas, aprovação, despesas de campo, faturas de posto, caixa de rota, plano de contas, balancete, razão, saldo de abertura, pendências e períodos. As telas **novas** são das Sprints 10 e 11.

## O que já existe
- Páginas: `/financeiro/` (`FinanceiroDashboardView`), `/financeiro/conciliacao/` e `/financeiro/fechamento-caixa/<pk>/`. Templates em `templates/financeiro/`.
- Cerca de 39 recursos no router `/financeiro/api/` e APIs avulsas (balancete, DRE, relatórios, conciliação, cobrança, projeção de caixa, painel de bloqueios). Veja `financeiro/urls.py`.
- Serviços em `financeiro/services/` (títulos, baixas, conta, caixa_rota, despesas_campo, fatura_posto, periodo, razao, saldo_abertura etc.).

## Tarefas

### 09.1 Divisão em páginas (só mover, sem mudar comportamento)
Submenu Financeiro com as páginas:
- **Visão geral** (`/financeiro/`);
- **Receber** (`/financeiro/receber/`) e **Pagar** (`/financeiro/pagar/`), incluindo a fila de aprovação;
- **Bancos e contas** (`/financeiro/contas/`), com contas, transferências e o link para a conciliação;
- **Operação de campo** (`/financeiro/campo/`): despesas de campo, faturas de posto e caixas de rota;
- **Contabilidade** (`/financeiro/contabilidade/`): plano de contas, balancete, razão, saldo de abertura, pendências e períodos;
- **Cadastros de apoio** (`/financeiro/cadastros/`): centros de custo, fornecedores e condições de pagamento.

Cada página com template e JS próprios. Faça commit depois de mover e conferir; só então redesenhe.

### 09.2 Redesign do que existe
- **Título a receber ou a pagar em etapas:** Dados (cliente ou fornecedor, conta gerencial, competência, valor) → Parcelas (condição de pagamento gera as parcelas e permite editá-las) → Rateio e retenções (centro de custo e veículo; ISS, IRRF, PIS, COFINS, CSLL, INSS) → Revisão. Status por `transicionar` em `financeiro/services/titulos.py`; status `read_only` no serializer.
- **Baixa de parcela** (individual e em lote) com juros e multa calculados ao vivo (`calcular_encargos`), conta de destino e estorno com motivo.
- **Fila de aprovação** (alçadas): aprovar ou rejeitar com motivo; só quem `pode_aprovar`.
- **Transferência entre contas** (modal) e extrato da conta.
- **Despesas de campo:** conferência em lote (aprovar ou rejeitar com motivo) e a pré-visualização da foto do comprovante.
- **Faturas de posto:** importar CSV → conciliar com os pré-lançamentos (mostrar os não casados) → aprovar.
- **Caixa de rota** (`fechamento_caixa_detalhe.html`): contagem cega pelo motorista, conferência, quebra (sobra ou falta) e cheques.
- **Plano de contas** em árvore (sintética e analítica, com a linha da DRE).
- **Saldo de abertura:** simular → ver o lançamento gerado → confirmar; estorno com motivo.
- **Períodos:** fechar e reabrir (motivo obrigatório na reabertura; só ADMIN).
- **Conciliação bancária** (`conciliacao.html`, 20 `alert`): redesign com extrato à esquerda, sugestões no meio e ações (conciliar, dividir, ignorar, lançamento direto, desfazer).

## Critérios de aceite
- Nenhum template de financeiro com mais de cerca de 800 linhas; zero `alert`/`confirm`/`prompt` e zero estilos inline nas páginas desta sprint.
- Todo valor monetário exibido em pt-BR e enviado como string decimal.
- Suíte verde (os testes `financeiro/tests/test_sprint9*` e `test_sprint10a*` devem continuar passando).

## Testes obrigatórios
- Cada página renderiza para ADMIN e respeita `CanViewDRE` e o módulo financeiro.
- PATCH de `status` de título é ignorado ou recusado.
- Baixa em lote é idempotente (não baixa duas vezes).

## Fora do escopo
Telas novas de cobrança, crédito, fluxo de caixa, DRE, orçamento, PDD, depreciação e lançamentos manuais (Sprints 10 e 11).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_09.md`.
