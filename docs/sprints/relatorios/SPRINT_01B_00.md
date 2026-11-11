# Relatório da Entrega 01B.00 — Histórico de Status de Vendas e Entregas

**Data:** 11/11/2026  
**Branch:** `sprint-01b.00/historico-status`  
**Status:** Concluída com sucesso (Aguardando revisão do dono para prosseguir com a Entrega 01B.01)

---

## 1. O que foi feito

### Backend de Vendas
- **Modelo `vendas.HistoricoStatusVenda` (`TenantAwareModel`):**
  - Campos: `venda` (FK), `status_anterior` (CharField null=True), `status_novo` (CharField db_index=True), `alterado_em` (DateTimeField auto_now_add=True, db_index=True), `alterado_por` (FK User null=True), `origem` (`TELA`, `API`, `APP_CAMPO`, `SISTEMA`), `observacoes` (TextField).
  - Isolamento multi-tenant estrito com fallback seguro para criação sem contexto de thread (`.unscoped.create(...)`).
- **Serviço de Máquina de Estados e Rastreabilidade (`vendas/services/status.py`):**
  - `transicionar_venda`: atualizado para registrar a transição no histórico contendo `status_anterior` e `status_novo`.
  - `registrar_historico_venda`: função auxiliar para registrar histórico em pontos de transição e criação.
  - `desde_quando_no_status(venda)`: consulta temporal que retorna a data/hora em que a venda entrou no status atual, com fallback seguro para `data_atualizacao` ou `data_venda`.
- **Rastreabilidade na criação e liberação de Venda:**
  - `Venda.save()`: na criação (`is_new`), registra automaticamente a linha inicial do histórico.
  - `vendas/services/liberacao_service.py` (`liberar_bloqueio_venda`): registra transição de `BLOQUEADO_FINANCEIRO` para `Pendente`.
  - `vendas/views.py` (`enviar_para_logistica`): transiciona via serviço de status.
  - `faturamento/views.py`: webhook de liquidação transiciona venda para `Em Separação` com rastro auditado.
- **Migrações de Vendas:**
  - `0012_historico_status_venda`: criação da tabela.
  - `0013_migrar_historico_inicial_vendas`: backfill histórico para todas as vendas legadas com `origem='SISTEMA'` e preservação de datas originais.

### Backend de Logística
- **Modelo `logistica.HistoricoStatusEntrega` (`TenantAwareModel`):**
  - Campos: `entrega` (FK), `status_anterior` (CharField null=True), `status_novo` (CharField db_index=True), `alterado_em` (DateTimeField auto_now_add=True, db_index=True), `alterado_por` (FK User null=True), `origem` (`TELA`, `API`, `APP_CAMPO`, `SISTEMA`), `observacoes` (TextField).
- **Serviço de Máquina de Estados e Rastreabilidade (`logistica/services/status.py`):**
  - Criado o serviço com `transicionar_entrega(entrega, novo_status, usuario, origem, observacoes)`.
  - Validação estrita de transições: `Agendada` → `Em Produção` / `Em Rota` / `Cancelada`; `Em Rota` → `Concluída` / `Cancelada`.
  - `desde_quando_no_status(entrega)`: consulta temporal do último status da entrega.
- **Rastreabilidade nos fluxos operacionais de Entrega:**
  - `Entrega.save()`: na criação (`is_new`), registra o status inicial.
  - `logistica/services/carga.py`: transição auditada para `Em Rota` nos despachos com ou sem liberação formal.
  - `logistica/services/paradas_service.py`: transição auditada para `Concluída` ao finalizar todas as paradas.
  - `logistica/views.py` (`concluir_romaneio` e `conferência de saída`): transições operacionais passando pelo serviço de status.
- **Migrações de Logística:**
  - `0024_historico_status_entrega`: criação da tabela.
  - `0025_migrar_historico_inicial_entregas`: backfill histórico para todas as entregas legadas com `origem='SISTEMA'`.

### Django Admin (Regra 3.5 & Imutabilidade)
- Registrados `HistoricoStatusVendaAdmin` e `HistoricoStatusEntregaAdmin` com desativação total de permissões de adição, edição e exclusão (`has_add_permission = False`, `has_change_permission = False`, `has_delete_permission = False`).

---

## 2. Bugs encontrados e corrigidos no caminho

1. **`AttributeError: 'NoneType' object has no attribute 'is_superuser'` em chamadas de sistema:**
   - Em `validar_papel_alteracao`, se `usuario` for `None` (como em webhooks ou rotinas batch), ocorria exceção ao checar permissão. Ajustado para permitir chamadas legítimas de sistema (`usuario is None`).
2. **`TenantNotSet` durante execução de webhooks de faturamento:**
   - Webhooks externos não carregam contexto de tenant na thread-local. A criação de histórico de status utilizava o manager padrão `HistoricoStatusVenda.objects.create()`, falhando no isolamento fail-closed. Corrigido com `.unscoped.create(tenant=venda.tenant, ...)`.
3. **Idempotência em `concluir_romaneio`:**
   - `test_matriz_rbac_concluir_romaneio` dispara `concluir-romaneio` em sequência para diferentes usuários sobre a mesma entrega. Como a entrega já estava concluída, a validação de transição gerava `ValidationError`. Ajustado para transicionar apenas se `entrega.status != 'Concluída'`.

---

## 3. O que ficou de fora e por quê

- **Monitor de TV (`/painel/<token>/`):** Escopo da Entrega 01B.01 (tarefa 01B.2).
- **Home de Gestão e Painel de KPIs:** Escopo da Entrega 01B.02 (tarefas 01B.3 a 01B.6).

---

## 4. Decisões tomadas por premissa

- **Criação com histórico inicial automático:** Toda nova venda ou entrega cria imediatamente seu registro inicial no histórico correspondente. Isso garante que o monitor de TV e as filas de espera sempre encontrem uma data válida sem necessitar de lógicas de contorno.
- **Preservação de data em migrações legadas:** O backfill nas migrações de dados utilizou `update(alterado_em=data_ref)` para respeitar a data histórica original e contornar a sobrescrita do `auto_now_add=True`.
- **Imutabilidade append-only:** Os históricos são puramente de auditoria e telemetria temporal. Nenhum registro pode ser modificado ou excluído via API ou Admin.

---

## 5. Resultado da suíte de testes

- **Comando:** `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- **Total de testes:** **717 passed**, 4 warnings em 2m47s.
- **Zero falhas.**

---

## 6. Lista de commits

1. `eb3b84d`: `feat(vendas): modelo HistoricoStatusVenda, servico de transicao e rastreabilidade`
2. `84f73f6`: `feat(logistica): modelo HistoricoStatusEntrega, servico de transicao e rastreabilidade`
3. `4f42de0`: `test(vendas): testes de historico de status de vendas e entregas`
4. `[commit atual]`: `docs: relatorio da entrega 01b.00 e atualizacao do progresso`

---

## 7. Notas de deploy

- **Migrações:** Executar `python manage.py migrate` para aplicar:
  - `vendas.0012_historico_status_venda`
  - `vendas.0013_migrar_historico_inicial_vendas`
  - `logistica.0024_historico_status_entrega`
  - `logistica.0025_migrar_historico_inicial_entregas`
- **Variáveis de ambiente novas:** Nenhuma.
- **Dependências novas:** Nenhuma.

---

## 8. Verificação dos Itens da Sprint

### Testes da Entrega (`vendas/tests/test_sprint01b_00_historico_status.py`)
- [x] **Falha antes:** Transição de venda via `transicionar_venda` grava histórico com `status_anterior`, `status_novo`, `alterado_por` e `origem` (`test_01_transicao_venda_grava_historico`).
- [x] Liberação de bloqueio de venda grava transição `BLOQUEADO_FINANCEIRO` → `Pendente` (`test_02_liberacao_bloqueio_venda_grava_historico`).
- [x] **Falha antes:** Transição de entrega via `transicionar_entrega` grava histórico com metadados completos (`test_03_transicao_entrega_grava_historico`).
- [x] Função `desde_quando_no_status` devolve datetime preciso para vendas e entregas (`test_04_desde_quando_no_status_venda_e_entrega`).
- [x] Isolamento multi-tenant fail-closed respeitado nos históricos (`test_05_isolamento_multitenant_historico`).
- [x] Admin dos históricos é estritamente somente leitura (`test_06_admin_somente_leitura`).
- [x] Migração de dados de backfill cria registros com `origem='SISTEMA'` para legados (`test_07_migracao_dados_backfill_existentes`).

---

## 9. Definição de Pronto (Seção 9 das Regras Gerais)

1. **System Check:**
   ```
   > venv/Scripts/python.exe manage.py check
   System check identified no issues (0 silenced).
   ```
2. **Checagem de Migrações:**
   ```
   > venv/Scripts/python.exe manage.py makemigrations --check --dry-run
   No changes detected
   ```
3. **Suíte Geral de Testes:**
   ```
   > venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
   ================= 717 passed, 4 warnings in 167.18s (0:02:47) =================
   ```
4. **Integridade de Documentação:**
   - Comentários e regras preservados.
5. **Git Status:**
   - Working tree limpa antes do commit de documentação.
