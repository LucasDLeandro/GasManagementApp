# ADR-040: Versionamento Seguro de IndexedDB no PWA de Campo (F-40)

## Status
Aprovado e Implementado (Sprint 9C)

## Contexto
O PWA de Campo (`/campo/`) opera sob arquitetura *offline-first* para garantir que motoristas consigam bipar cilindros, registrar entregas, reportar avarias e registrar despesas de rota (combustível, pedágio, manutenção) mesmo em zonas de sombra sem sinal de celular.

Na Sprint 8, o banco de dados IndexedDB local do cliente estava na versão `7` (`DB_VERSION = 7`), contendo os object stores:
- `movimentacoes_queue`
- `rota_pacote`
- `abastecimentos_queue`
- `checklists_queue`
- `defeitos_queue`
- `sinistros_queue`
- `gps_tracking_queue`

A introdução das Despesas de Campo Antifraude (Sprint 9C) requer o store unificado `despesas_pendentes`, com índices para busca por `criado_em`, `status_local` e `tipo`, permitindo idempotência por `client_uuid` e resolução determinística de conflitos onde o servidor prevalece em registros já consolidados ou aprovados.

A falha arquitetural F-40 alertou que incrementos de versão no IndexedDB sem encadeamento rigoroso em `onupgradeneeded` poderiam disparar `VersionError` ou perda silenciosa de dados não sincronizados mantidos no dispositivo do motorista.

## Decisão
1. **Incremento Estrito de Versão:**
   - A constante `DB_VERSION` em `static/js/offline_sync.js` é incrementada de `7` para **`8`**.
2. **Migração Sequencial Encadeada:**
   - O manipulador `request.onupgradeneeded` avalia explicitamente `event.oldVersion`:
     - Se `oldVersion < 8`, cria o store `despesas_pendentes` com keyPath `client_uuid` e índices `criado_em`, `status_local` e `tipo`.
     - Preserva integralmente todos os stores pré-existentes e registros pendentes de envio.
3. **Resolução de Conflitos e Idempotência:**
   - Todo lançamento offline possui um `client_uuid` gerado no dispositivo.
   - Reenvios do mesmo `client_uuid` são idempotentes no backend via `UniqueConstraint(tenant, client_uuid)`.
   - Se o backend já possuir a despesa com status `APROVADO`, `REJEITADO` ou `CONSOLIDADO`, o retorno do servidor atualiza o status local para `SINCRONIZADO`, prevenindo duplicações.

## Consequências
- Os dispositivos em campo migram automaticamente e de forma transparente para a versão 8 na próxima abertura do app.
- Nenhum dado previamente gravado nas filas de movimentação ou sinistro é corrompido ou descartado.
