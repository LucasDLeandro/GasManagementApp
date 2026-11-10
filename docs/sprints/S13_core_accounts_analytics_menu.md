# Sprint 13: Core, Accounts, Analytics e menu

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, as seções 2, 3, 12 e 13 de `docs/GUIA_MODULOS_BAROS.md`, a "FASE 7" (e as pendências da "FASE 1") de `docs/PLANO_CORRECAO_E_EVOLUCAO.md` e `docs/lgpd/MAPEAMENTO_LGPD_ROPA.md`.
**Branch:** `sprint-13/core-accounts` a partir de `sprint-12/fiscal`.

## Objetivo
Acabamento das áreas transversais: página inicial, usuários e acesso, integrações, filiais, LGPD, analytics no menu, o menu lateral reorganizado e as pendências de segurança de acesso.

## O que já existe
- `core/templates/core/home.html` (3 painéis conforme o tipo de operação), `templates/core/integracoes.html`, `templates/core/perfil_regulatorio.html`, e `accounts/templates/accounts/` (`index.html` de pessoal, `meu_perfil.html`, `login.html`, `first_login_password.html`, **este último não usado por nenhuma view**).
- `analytics/templates/analytics/funil_alertas.html`, servida em `/api/analytics/funil-alertas/` e **fora do menu**.
- Modelos: `Filial` (sem tela), `SolicitacaoTitularLGPD` (sem tela), `WebhookEndpoint` e `WebhookDeliveryLog`.
- Backoffice com MFA obrigatório (cadastro no 1º acesso), mas **sem códigos de recuperação e sem troca do autenticador**.

## Tarefas

### 13.1 Segurança de acesso (prioridade)
- **Troca obrigatória da senha provisória no 1º acesso** do app da distribuidora. Hoje o onboarding do backoffice cria o admin com senha provisória e nada obriga a troca. Crie o campo `deve_trocar_senha` no `User` (migração; `True` para usuários criados pelo onboarding e pelo cadastro de pessoal) e um middleware que redireciona para a tela de troca enquanto ele estiver ativo (com exceção da própria tela, logout e estáticos). Use `first_login_password.html` redesenhado e as regras de senha do Django (`validate_password`; o `alterar_senha` atual exige só 6 caracteres: alinhe tudo a `AUTH_PASSWORD_VALIDATORS`).
- **Backoffice:** 10 códigos de recuperação de uso único, gerados no cadastro do MFA (exibidos uma vez; guardados com hash), aceitos no login; e uma tela "Trocar autenticador" que exige o código atual.

### 13.2 Accounts
- Pessoal: lista com papel, filial e status; **cadastro em etapas** (Dados → Papel e filial → Dados trabalhistas → Revisão) respeitando a **cota de usuários** do plano (`checar_cota(tenant, 'usuarios')`); desativar e reativar (desativar é melhor que apagar).
- Meu perfil e troca de senha no padrão (senha atual + nova com validação).

### 13.3 Core
- **Home:** o redesign foi feito na **Sprint 01B** (fila por papel, visão de gestão e monitor de TV). Aqui, só conferir que os 3 painéis (envase, distribuição, integrado) seguem coerentes com o menu novo e com os módulos; não refazer.
- **Integrações:** webhooks (criar com o segredo *write-only*, testar, que já é síncrono, ver o log de entregas e **reenviar** uma entrega com falha) e exportação ERP.
- **Perfil regulatório e RTs** no padrão.
- **Filiais:** CRUD (CNPJ validado, município IBGE de 7 dígitos, matriz não pode ser excluída).
- **LGPD:** fila de solicitações de titulares (acesso, eliminação e anonimização, revogação), com prazo e atendimento usando `core/services/lgpd_service.py`.

### 13.4 Analytics
- Mover o funil de alertas para `/analytics/funil/` (página) e manter a API em `/api/analytics/`; incluir no menu (módulo analytics).
- Redesign do funil (NOVO → EM_CONTATO → CONVERTIDO/DESCARTADO) e um painel de previsão de recompra e risco de não retorno de cilindro.

### 13.5 Menu lateral (`templates/base_dashboard.html`)
- Reorganizar por áreas: **Operação** (Início, Ativos, Rampa, Recebimento, Lotes/CQ, Tanques, Estoque, Recall) · **Comercial** (Clientes, Vendas, Analytics) · **Logística** (Entregas, Torre, Frota, Combustível, Manutenção, Seguros, Rentabilidade, App de Campo) · **Financeiro** · **Fiscal** · **Configurações** (Pessoal, Filiais, Integrações, Perfil regulatório, LGPD).
- Cada item respeita o módulo contratado e o papel. Remover os estilos inline do cabeçalho e do menu do usuário (a classe `.user-menu-link` já existe em `components.css`).

## Critérios de aceite
- Usuário com `deve_trocar_senha` não consegue usar o app antes de trocar a senha; o backoffice aceita um código de recuperação uma única vez.
- Zero estilos inline e zero `alert` em `core`, `accounts` e `analytics`.
- Suíte verde.

## Testes obrigatórios
- Middleware de troca de senha (redireciona, libera depois da troca, não afeta API com JWT de serviço; documente a decisão).
- Código de recuperação: aceito uma vez, recusado na segunda.
- Cota de usuários no cadastro de pessoal.
- Filial matriz não pode ser excluída; isolamento entre empresas em filiais e LGPD.

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_13.md`.
