# Sprint 06: Clientes (ajustes) e Vendas

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, as seções 4 e 6 de `docs/GUIA_MODULOS_BAROS.md`, a "FASE 3" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md` e a seção "Sprint 11C" de `docs/DECISOES_PENDENTES.md` (crédito, bloqueio e regra assistencial para gás medicinal).
**Branch:** `sprint-06/clientes-vendas` a partir de `sprint-05/produtos-legado-sku`.

## Objetivo
Fechar o módulo comercial: a tela de Vendas inteira no padrão novo, o estorno de venda faturada (hoje bloqueado) e os ajustes que faltam em Clientes.

## O que já existe
- **Clientes** (`clientes/templates/clientes/index.html`, `clientes/static/clientes/js/index.js`) é a tela de referência do redesign. Já tem cadastro em etapas, contratos, radar e o stepper de fechamento de estadia (simular → drill-down → fechar). APIs em `clientes/urls.py` e `clientes/views.py`: `api/` (clientes), `api/contratos/`, `api/faturas-estadia/` (`simular-drill-down`, `drill-down`, `fechar`, `espelho-pdf`, `espelho-csv`, `exportacao-canonica`) e `api/extravios/` (`alertas`, `radar-carencia`, `declarar`).
- **Vendas** (`vendas/templates/vendas/index.html`, `vendas/static/vendas/js/index.js`): tela antiga, com 92 estilos inline.
  - Máquina de estados já pronta em `vendas/services/status.py` (`TRANSICOES_VENDA`, `transicionar_venda`, papéis).
  - Baixa de estoque idempotente em `produtos/services/estoque_produto.py::baixar_estoque_venda_faturada`.
  - Liberação de bloqueio em `vendas/services/liberacao_service.py`.
  - Crédito avaliado em `financeiro/services/credito_service.py::avaliar_credito` (chamado no serializer de venda).
- **Limitação deixada na Fase 0:** cancelar uma venda **já faturada** é recusado com a mensagem "exige estorno, ainda não disponível".

## Tarefas

### 06.1 Estorno de faturamento (backend)
- Serviço `vendas/services/estorno.py::estornar_faturamento(venda, usuario, motivo)`:
  - devolve o estoque com movimentos `ENTRADA` de estorno ligados à mesma origem (não apague os de saída);
  - publica o evento contábil de estorno (veja como `financeiro/contabilizacao.py` trata `venda_faturada`; crie `venda_faturamento_estornado` e estorne o lançamento com `razao.estornar`; nunca apague);
  - se existir NF-e autorizada (`fiscal`), recuse com a mensagem "cancele a NF-e no Fiscal antes";
  - motivo de pelo menos 10 caracteres; só ADMIN e GERENTE; registre em `LogAuditoriaDados`.
- Em `TRANSICOES_VENDA`, "Cancelada" a partir de um estado faturado passa a chamar o estorno (em vez de recusar).

### 06.2 Tela de Vendas (redesign completo)
- Cabeçalho, cartões (faturamento do mês, pedidos em aberto, bloqueados por crédito, ticket médio), abas **Fila ativa | Bloqueados | Concluídas | Canceladas | Painel**.
- **Nova venda em etapas:** Cliente (busca; mostra o crédito disponível e alertas, e avisa na hora se vai bloquear) → Itens (SKUs ativos de `/produtos/api/catalogo/skus/?ativo=1`, com quantidade, preço sugerido pelo `preco_base`, desconto e total) → Entrega (retirada ou entrega, data) → Pagamento (condição) → Revisão.
- **Detalhe da venda em drawer:** itens, linha do tempo de status, entrega vinculada, NF-e (quando houver) e cobrança.
- Os botões de status mostram **só as transições permitidas** (leia de `TRANSICOES_VENDA`; exponha-as na API, por exemplo com o campo `transicoes_permitidas` no serializer).
- **Pedido bloqueado:** banner com o motivo do bloqueio e o botão "Liberar" (ADMIN e GERENTE, com motivo; `liberar_bloqueio_venda`).
- Cancelamento de pedido faturado chama o estorno de 06.1, com `Baros.confirmar({motivo: 10, perigo: true})`.
- Recibo de venda imprimível sem estilos inline.
- **Alertas comerciais** (`/vendas/api/alertas/`): lista na aba Painel, com a ação "resolver".

### 06.3 Clientes (ajustes)
- Remover os estilos inline restantes de `clientes/index.html` (eram 136).
- **Usuários do portal B2B** no detalhe do cliente: listar, convidar, mudar o papel (`COMPRADOR`, `FINANCEIRO`, `LEITOR`) e revogar. Antes, localize as APIs do lado da distribuidora em `portal_b2b/urls.py` e `portal_b2b/views.py`; se não existirem, crie-as em `clientes` (ADMIN e GERENTE), usando `UsuarioClienteB2B` e `ConviteB2B`.
- **Crédito do cliente** no detalhe (somente leitura): limite, exposição atual e promessas de pagamento ativas (`financeiro/services/credito_service.py`).

## Critérios de aceite
- Vender, faturar, entregar e finalizar pela tela nova; cancelar uma venda faturada estorna o estoque e a contabilidade.
- O vendedor não vê "Liberar bloqueio", e o backend responde 403 se ele tentar.
- Suíte verde.

## Testes obrigatórios
- Estorno: estoque devolvido uma vez (idempotente), lançamento estornado e auditoria registrada; recusado com NF-e autorizada; recusado para VENDEDOR.
- `transicoes_permitidas` correto por status.
- Endpoints de usuários B2B: papel, isolamento entre empresas, revogação.
- Renderização da tela de Vendas sem `alert(`.

## Fora do escopo
Emissão de NF-e pela tela de vendas (Sprint 12).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_06.md`.
