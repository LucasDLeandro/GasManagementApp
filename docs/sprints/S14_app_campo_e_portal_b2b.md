# Sprint 14: App de Campo (PWA) e Portal B2B

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md` (seção 8 e a estação de rampa em `produtos/static/produtos/css/index.css`, bloco "Estação de rampa", como referência de tela de campo), as seções 7.1 e 11 de `docs/GUIA_MODULOS_BAROS.md`, `docs/adr/ADR-040-indexeddb-versioning.md`, `docs/adr/ADR-043-...` e as seções 12A e 12B de `docs/DECISOES_PENDENTES.md`.
**Branch:** `sprint-14/campo-b2b` a partir de `sprint-13/core-accounts`.

## Objetivo
Redesenhar as duas interfaces usadas fora do escritório: o **App de Campo** do motorista (PWA, offline) e o **Portal B2B** do cliente final.

## O que já existe
- **App de Campo:** `logistica/templates/logistica/app_campo.html` (246 estilos inline), `static/js/app_campo.js` (grande), `static/js/offline_sync.js` (IndexedDB na versão 9: filas de movimentações, despesas e `gps_tracking_queue` com `lat`/`lng`), `static/css/app_campo.css`, `static/sw.js` e `static/manifest.json`. Sincronização: `/api/movimentacoes/sync-offline/` (idempotente por `client_uuid`) e `/logistica/api/tracking/sync/`.
- **Portal B2B:** `portal_b2b/templates/portal_b2b/` (base, login, mfa, termo, aceitar_convite, dashboard) com sessão separada (`b2b_sessionid`), ViewSets próprios, laudo por URL assinada e reposição em 1 clique (`portal_b2b/reposicao_service.py`, que avalia crédito).

## Tarefas

### 14.1 App de Campo
- Adaptar o Design System para o uso no caminhão: botões de pelo menos 48px, fonte maior, **alto contraste solar** como padrão opcional e uso com uma mão.
- Fluxo em telas sequenciais: **Checklist do veículo** → **Carregar** (bipagem dos cilindros da entrega) → **Paradas** (lista com ETA; abrir no mapa ou navegação) → **Na parada:** entregar cheio / recolher vazio (bipagem), assinatura do recebedor, foto e ocorrência → **Despesas** (abastecimento, pedágio, com foto) → **Caixa de rota** (contagem cega).
- **Estado offline sempre visível:** banner "Sem conexão: N itens aguardando envio", fila de pendências com status (pendente, enviado, rejeitado com motivo) e botão "Sincronizar agora".
- Se precisar de uma nova store ou índice no IndexedDB, **suba a versão para 10** com migração encadeada (`if (oldVersion < 10)`) e escreva a ADR `docs/adr/ADR-044-...`. Nunca apague stores com dados pendentes.
- Remover todos os estilos inline e os `alert`/`confirm`; o JS pode ter funções `Baros.*` próprias se `core.js` não for carregado no PWA (avalie e documente).

### 14.2 Portal B2B
- Redesign com a identidade da distribuidora (nome e logo do tenant, quando houver), mantendo a sessão separada.
- Páginas: **Início** (cilindros comigo, estadia acumulada no mês, boletos a vencer, alertas de reteste), **Meus cilindros** (lista com reteste e laudo), **Faturas e boletos** (2ª via), **Laudos** (download por URL assinada de uso único, que já existe), **Pedir reposição** (1 clique por SKU habitual, com resultado claro se bloquear por crédito) e **Notificações**.
- Usuário LEITOR não vê "Pedir reposição"; FINANCEIRO vê faturas; COMPRADOR pede. **Valide no backend**.
- Login, MFA, termo e aceite de convite no padrão, sem estilos inline.

## Critérios de aceite
- O App de Campo funciona offline de ponta a ponta (teste manual descrito no relatório: modo avião → registrar entrega → voltar a conexão → sincronizou sem duplicar).
- O Portal B2B nunca mostra dados de outro cliente (teste) e respeita o papel.
- Suíte verde (incluindo `logistica/tests/test_sprint6*`, `test_fase4*`, `financeiro/tests/test_sprint9c*` e `portal_b2b/tests/*`).

## Testes obrigatórios
- Sincronização offline: reenvio com o mesmo `client_uuid` não duplica.
- Portal: isolamento por cliente e permissão por papel em reposição e faturas.
- Teste que garante `DB_VERSION >= 9` e a presença das migrações encadeadas (há um teste parecido em `financeiro/tests/test_sprint9c_antifraude_caixa_rota.py`).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_14.md`.
