# Sprint 10: Financeiro, cobrança, crédito e fluxo de caixa

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, as seções 8.4 e 8.6 de `docs/GUIA_MODULOS_BAROS.md` e as seções 10A, 10C e 11C de `docs/DECISOES_PENDENTES.md` (PSP piloto, limiares de conciliação, restrições da régua, cenários de 90 dias, exposição de crédito, regra assistencial).
**Branch:** `sprint-10/financeiro-cobranca-credito` a partir de `sprint-09/financeiro-estrutura`.

## Objetivo
Criar as telas da gestão do dinheiro que hoje só existem na API: visão do dono, fluxo de caixa projetado, cobrança registrada e régua, e crédito do cliente.

## O que já existe (backend)
- **Cobrança:** `financeiro/services/cobranca_service.py` (`emitir_cobranca_parcela`, `emitir_cobranca_titulo`, `cancelar_cobranca_parcela`, `processar_webhook_cobranca`); APIs `api/cobranca/emitir-parcela/`, `configuracoes-cobranca`, `reguas-cobranca`, `envios-cobranca`, `consentimentos-contato`.
- **Régua:** `regua_service.py` (`executar_regua_cobranca`, janela comercial, consentimento LGPD, templates).
- **Crédito:** `credito_service.py` (`avaliar_credito`, `criar_promessa_pagamento`, `atualizar_status_promessas_diario`); APIs `parametros-credito`, `limites-credito-cliente`, `promessas-pagamento`, `api/painel-bloqueios/`.
- **Caixa:** `fluxo_caixa_service.py`, `projecao_caixa_service.py`, `alerta_caixa_service.py`; APIs `api/fluxo-caixa-realizado/`, `api/projecao-caixa/`, `alertas-caixa`, `recorrencias`, `perfis-pagamento`.

## Tarefas

### 10.1 Visão geral do dono (`/financeiro/`)
- Cartões: saldo consolidado hoje, a receber em 30 dias, a pagar em 30 dias, inadimplência (valor e %), alertas de caixa ativos.
- Gráfico (`static/vendor/chartjs`) de entradas × saídas dos próximos 90 dias e lista dos 5 maiores atrasos.

### 10.2 Fluxo de caixa (`/financeiro/fluxo-de-caixa/`)
- Realizado (período escolhido) + projeção de 90 dias em **3 cenários** (pessimista, base, otimista), em gráfico e tabela por semana; explicação de cada cenário conforme 10C.1.
- **Recorrências** (aluguel, folha, contas fixas): CRUD e efeito na projeção.

### 10.3 Cobrança (`/financeiro/cobranca/`)
- **Configuração do PSP** (só ADMIN): credenciais apenas como campos *write-only* (nunca devolver a chave na API; mostrar só "configurada").
- **Emitir boleto ou PIX** a partir de uma parcela (botão na página Receber) e cancelar.
- **Régua de cobrança:** editor de etapas (dias antes e depois do vencimento, canal, template com variáveis e pré-visualização), respeitando as restrições de 10A.3 (janela comercial, consentimento).
- **Log de envios** com filtro por status e **consentimentos** (registrar e revogar).

### 10.4 Crédito (`/financeiro/credito/`)
- Parâmetros de crédito (ADMIN), limites por cliente (lista com exposição atual, % usado e bloqueados), promessas de pagamento (criar e acompanhar ATIVA, CUMPRIDA, QUEBRADA) e o **painel de bloqueios** (`api/painel-bloqueios/`) com o link para liberar a venda (`vendas`, Sprint 06).
- Mostrar de forma clara a **regra assistencial** de gás medicinal para hospital (11C.3) quando ela impedir o bloqueio.

## Critérios de aceite
- Telas no Design System, sem estilos inline nem `alert`.
- Nenhuma credencial do PSP sai na API ou no HTML.
- Suíte verde (incluindo `financeiro/tests/test_sprint10a*`, `test_sprint11c*` e `analytics/tests/test_sprint10c*`).

## Testes obrigatórios
- A API de configuração de cobrança não devolve o segredo.
- Limite de crédito e promessa: só ADMIN e GERENTE escrevem; isolamento entre empresas.
- Renderização das páginas.

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_10.md`.
