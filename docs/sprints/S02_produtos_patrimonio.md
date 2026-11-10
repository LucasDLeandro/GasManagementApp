# Sprint 02: Produtos, telas de Patrimônio

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 5.4 de `docs/GUIA_MODULOS_BAROS.md`, a seção "Sprint 8A" de `docs/DECISOES_PENDENTES.md` e o relatório `RELATORIO_SPRINT_*` mais recente que fale de patrimônio, se houver.
**Branch:** `sprint-02/produtos-patrimonio` a partir de `sprint-01b/paineis`.

## Objetivo
Dar tela ao backend de patrimônio da Sprint 8A, que hoje só existe na API: fabricantes, classes de ativo, lotes de aquisição, ativos imobilizados e tabela de indenização.

## O que já existe
- APIs (todas com `RequiresModulePatrimonio`): `/produtos/api/patrimonio/fabricantes/`, `/classes/`, `/lotes/`, `/ativos/`, `/indenizacoes/`. Veja os ViewSets a partir de `FabricanteCilindroViewSet` em `produtos/views.py` e os serializers correspondentes em `produtos/serializers.py`.
- Serviço `produtos/services/indenizacao.py::calcular_indenizacao`.
- `ClasseAtivo` tem contas contábeis (`conta_imobilizado`, `conta_depreciacao_acumulada`, `conta_despesa_depreciacao`) que apontam para `financeiro.PlanoContas`.
- **Problema conhecido:** hoje qualquer membro da empresa cria e edita esses cadastros, porque os ViewSets não checam papel.

## Tarefas

### 02.1 Permissões
- Escrita (POST, PUT, PATCH, DELETE) em fabricantes, classes, lotes de aquisição, ativos e indenizações: só `ADMIN` e `GERENTE`. Reaproveite a classe `SomenteGestaoAltera` de `produtos/views.py` (criada para o catálogo).
- Exclusão de registro em uso responde 400 com mensagem clara (veja `CatalogoBaseViewSet.destroy`).

### 02.2 Página "Patrimônio"
- Nova página `/produtos/patrimonio/` (template `produtos/templates/produtos/patrimonio/index.html` + parciais + `produtos/static/produtos/js/patrimonio.js`). Link no menu lateral em `templates/base_dashboard.html`, logo abaixo de "Ativos 360°", visível só com o módulo patrimônio.
- Abas: **Ativos imobilizados** | **Lotes de aquisição** | **Classes de ativo** | **Fabricantes** | **Indenização**.
- **Ativos imobilizados**: tabela com valor de aquisição, depreciação acumulada, valor contábil líquido e status (`EM_USO`, `BAIXADO`, `VENDIDO`); filtro por classe e por status; cartões de valor total, depreciação acumulada e líquido.
- **Lotes de aquisição**: stepper Nota fiscal (chave NF-e com validação de 44 dígitos, fornecedor, data) → Valores (quantidade, valor unitário, classe) → Revisão. Mostrar quantos cilindros foram vinculados a cada lote.
- **Classes de ativo**: modal com seções (dados, vida útil e residual, contas contábeis). Os selects de conta listam o plano de contas do Financeiro, só contas **analíticas**. Se o módulo financeiro estiver desligado, o campo fica opcional e um aviso explica o motivo.
- **Fabricantes**: CRUD simples (modal curto).
- **Indenização**: tabela modelo × gás → valor, edição em linha e, no topo, um simulador que chama `calcular_indenizacao` (crie `GET /produtos/api/patrimonio/indenizacoes/simular/?cilindro_id=` se não existir).

### 02.3 Integração com o cadastro de cilindro
- No `_modal_cadastro_cilindro.html`, etapa "Propriedade": acrescentar o select "Lote de aquisição" (opcional). O model `Cilindro.save` já herda valor, data, classe e NF do lote; mostre essa herança na Revisão.

## Critérios de aceite
- Todas as abas no padrão do Design System, com estados de carregando, vazio e erro, sem estilo inline e sem `alert`.
- Um usuário `VENDEDOR` vê as listas, mas não vê os botões de criar, editar e excluir, e o backend responde 403 se ele tentar.
- Suíte verde.

## Testes obrigatórios
- Permissão de escrita por papel em cada endpoint (ADMIN e GERENTE permitidos; OPERADOR_PATIO e VENDEDOR recebem 403).
- Exclusão de fabricante ou classe em uso responde 400.
- O simulador de indenização devolve o valor esperado.
- A página renderiza para GERENTE e contém os IDs das abas.

## Fora do escopo
Retestes e baixa (Sprint 03); depreciação mensal e lançamentos contábeis (Financeiro, Sprint 10).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_02.md`.
