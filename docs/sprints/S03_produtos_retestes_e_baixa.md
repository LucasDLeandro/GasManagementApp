# Sprint 03: Produtos, retestes hidrostáticos e baixa patrimonial

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 5.4 de `docs/GUIA_MODULOS_BAROS.md` e a seção "Sprint 8B" de `docs/DECISOES_PENDENTES.md` (expansão permanente, periodicidade, variação de tara de 5% e política contábil).
**Branch:** `sprint-03/produtos-retestes-baixa` a partir de `sprint-02/produtos-patrimonio`.

## Objetivo
Dar tela ao fluxo completo de requalificação e de baixa patrimonial da Sprint 8B: envio de cilindros em lote para a requalificadora, retorno com laudo (expansão permanente e tara), retificação, calendário de vencimentos e baixa com estorno.

## O que já existe
- APIs: `/produtos/api/patrimonio/envios-reteste/` (create em lote → `enviar_cilindros_para_reteste`), `/produtos/api/patrimonio/retestes/` (com a action `retificar`), `/produtos/api/patrimonio/baixas/` (create → `baixar_cilindro_patrimonial`; action `estornar`). Há ainda a action de cilindro `registrar-retorno-reteste-completo` (procure `registrar_retorno_reteste_completo` em `produtos/views.py`).
- Serviços: `produtos/services/reteste.py` (`enviar_cilindros_para_reteste`, `registrar_retorno_reteste`, `retificar_reteste`) e `produtos/services/baixa.py` (`baixar_cilindro_patrimonial`, `estornar_baixa`, `registrar_extravio`).
- O drawer do cilindro já tem um "retorno de reteste" **simples** (endpoint `retorno-reteste`, que usa o serviço legado `retornar_de_reteste`). Esta sprint cria o fluxo **completo**.

## Tarefas

### 03.1 Página "Retestes" (`/produtos/retestes/`)
- Cartões: vencidos, vencendo em 30, 60 e 90 dias, e em requalificação agora.
- Aba **Vencimentos**: lista de cilindros por data do próximo reteste, com filtros (gás, modelo, situação) e seleção múltipla para "Enviar para reteste".
- Aba **Envios**: lista de `EnvioReteste` (requalificadora, data, quantidade, pendentes de retorno).
  - **Novo envio em etapas:** Requalificadora (nome, CNPJ, documento de envio) → Cilindros (bipagem com leitor, no mesmo padrão do recebimento em `_aba_recebimento.html`; só aceita cilindro vazio e sem bloqueio) → Revisão.
- **Retorno por cilindro** (dentro do envio): formulário com data do teste, pressão de teste, **expansão total e permanente** com cálculo ao vivo do percentual e da aprovação pelo limite normativo da decisão 8B.1, tara aferida com a variação ao vivo e alerta acima de 5% (reaproveite a lógica de `cilindros_drawer.js`, seção 3.2), laudo em PDF e resultado (aprovado ou condenado). Usa `registrar_retorno_reteste`.
- **Cilindro condenado** no reteste: oferecer em seguida a baixa patrimonial (03.2), já preenchida com o tipo "inutilização técnica".
- **Retificação** de um reteste já registrado: modal com motivo obrigatório (`retificar`).

### 03.2 Baixa patrimonial
- No drawer do cilindro e na página de retestes: botão "Dar baixa", que abre um modal com tipo (`INUTILIZACAO_TECNICA`, `EXTRAVIO`, `VENDA`, `SINISTRO`), data, motivo de pelo menos 10 caracteres e documento (laudo, BO ou NF de venda) conforme o tipo; confirmação dupla com `Baros.confirmar({perigo: true})`.
- Aba **Baixas** na página de Patrimônio da Sprint 02: lista com estorno (motivo obrigatório; só ADMIN e GERENTE).
- `BAIXADO` é estado terminal: depois da baixa, o drawer só mostra o estorno.

### 03.3 Ajuste do drawer
- O botão "Registrar retorno de reteste" do drawer passa a abrir o retorno **completo** (03.1) quando o cilindro estiver num `EnvioReteste` aberto. Fora disso, mantém o simples.

## Critérios de aceite
- Fluxo de ponta a ponta na tela: selecionar vencidos → enviar → registrar retorno aprovado (validade renovada) e condenado (baixa oferecida).
- Expansão permanente acima do limite reprova automaticamente, com a mensagem da norma.
- Suíte verde.

## Testes obrigatórios
- Envio recusa cilindro cheio, bloqueado ou de outra empresa.
- Retorno aprovado atualiza `data_ultimo_reteste` e `data_proximo_reteste` conforme a periodicidade do modelo.
- Retorno reprovado por expansão.
- Estorno de baixa: só ADMIN e GERENTE; o cilindro volta ao status anterior.
- Renderização das páginas com os IDs principais.

## Fora do escopo
Lançamentos contábeis da baixa e do reteste (já feitos por eventos em `financeiro/contabilizacao.py`; não mexer).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_03.md`.
