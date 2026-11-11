# Relatório da Entrega 01B.00 — Histórico de Status de Vendas e Entregas

**Data:** 11/11/2026  
**Branch:** `sprint-01b.00/historico-status`  
**Status:** Concluída com sucesso após correções das revisões 1 e 2 (Aguardando aprovação do dono para iniciar a Entrega 01B.01)

---

## 1. O que foi feito

### Backend de Vendas
- **Modelo `vendas.HistoricoStatusVenda` (`TenantAwareModel`):**
  - Campos: `venda` (FK), `status_anterior` (CharField null=True), `status_novo` (CharField db_index=True), `alterado_em` (DateTimeField auto_now_add=True, db_index=True), `alterado_por` (FK User null=True), `origem` (`TELA`, `API`, `APP_CAMPO`, `SISTEMA`), `observacoes` (TextField).
  - Isolamento multi-tenant estrito com fallback seguro para criação sem contexto de thread (`.unscoped.create(...)`).
- **Serviço de Máquina de Estados e Rastreabilidade (`vendas/services/status.py`):**
  - `@transaction.atomic`: garante consistência atômica entre a alteração do modelo e a gravação do histórico.
  - O próprio `transicionar_venda` persiste `status` e `data_atualizacao` via `save(update_fields=['status', 'data_atualizacao'])`. Quem chama não precisa salvar o status novamente. Se a validação falhar, nem status nem histórico são alterados.
  - `validar_origem_e_usuario`: exige obrigatoriamente usuário autenticado para operações com `origem='TELA'` ou `'APP_CAMPO'`. `usuario=None` é aceito estritamente para `origem='SISTEMA'` ou `'API'`.
  - **Checagem de papel restrita:** `validar_papel_alteracao` só é executada quando a origem for `'TELA'` ou `'APP_CAMPO'`. Em chamadas com `origem='SISTEMA'` (cascata de entrega, sinistros, avaliação de crédito), o usuário que iniciou o evento é gravado no histórico para auditoria sem que seja exigido papel comercial dele.
  - `TRANSICOES_VENDA`: estritamente blindada. `BLOQUEADO_FINANCEIRO` só permite transição para `Cancelada` na máquina de estados. O desbloqueio é exclusivo do serviço formal `liberar_bloqueio_venda`. A entrada em `BLOQUEADO_FINANCEIRO` só é permitida via `origem='SISTEMA'`.
  - `desde_quando_no_status(venda)`: consulta temporal que retorna a data/hora em que a venda entrou no status atual, com fallback seguro para `data_atualizacao` ou `data_venda`.
- **Rastreabilidade em todos os fluxos de Venda:**
  - `Venda.save()`: na criação (`is_new`), registra automaticamente a linha inicial do histórico.
  - `vendas/serializers.py`: avaliação de crédito comercial na criação da venda roda independentemente do módulo Financeiro (preservando o comportamento da Sprint 11C) e transiciona formalmente para `BLOQUEADO_FINANCEIRO` com histórico (`origem='SISTEMA'`), com tratamento e logging explícitos de `ValidationError` e `Exception` (Regra 3.9).
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
  - `@transaction.atomic`: garante que a entrega e o histórico são persistidos atomicamente.
  - `transicionar_entrega` persiste a entrega no banco (`save(update_fields=...)`), preenchendo automaticamente `data_saida` quando a entrega entra em `'Em Rota'`.
  - `validar_origem_e_usuario`: exige usuário autenticado para `origem='TELA'` ou `'APP_CAMPO'`, aceitando `usuario=None` somente com `origem='SISTEMA'` ou `'API'`.
  - `TRANSICOES_ENTREGA`: tabela oficial parametrizada (detalhes na seção 4).
  - `desde_quando_no_status(entrega)`: consulta temporal do último status da entrega.
- **Rastreabilidade em todos os fluxos de Entrega:**
  - `Entrega.save()`: na criação (`is_new`), registra o status inicial.
  - `logistica/serializers.py`: campo `status` tornado estritamente `read_only = True` no `EntregaSerializer` (Regra 3.7).
  - `logistica/views.py` (`EntregaViewSet.perform_update`): intercepta alterações de status por PATCH/PUT via `transicionar_entrega`. Ao transicionar a entrega para `'Em Rota'`, `'Concluída'` ou `'Cancelada'`, as vendas vinculadas são atualizadas individualmente uma a uma por `transicionar_venda(..., origem='SISTEMA')`, eliminando 100% dos `.update(status=)` em lote do queryset.
  - `logistica/services/seguros_sinistros.py`: cancelamento de entrega/vendas e reagendamento de viagem por sinistro passam por `transicionar_entrega` e `transicionar_venda(..., origem='SISTEMA')`.
  - `logistica/services/carga.py`: transição auditada para `Em Rota` nos despachos com ou sem liberação formal.
  - `logistica/services/paradas_service.py`: transição auditada para `Concluída` ao finalizar todas as paradas.
  - `logistica/views.py` (`concluir_romaneio` e conferência de saída): transições operacionais passando pelo serviço de status.
- **Migrações de Logística:**
  - `0024_historico_status_entrega`: criação da tabela.
  - `0025_migrar_historico_inicial_entregas`: backfill histórico para todas as entregas legadas com `origem='SISTEMA'`.

### Django Admin (Regra 3.5 & Imutabilidade)
- Registrados `HistoricoStatusVendaAdmin` e `HistoricoStatusEntregaAdmin` com desativação total de permissões de adição, edição e exclusão (`has_add_permission = False`, `has_change_permission = False`, `has_delete_permission = False`).

---

## 2. Correções Realizadas nas Revisões 1 e 2

1. **Blindagem do Bloqueio Financeiro e Prevenção de Regressão do Bug 0.3.2 (Revisão 2):**
   - `TRANSICOES_VENDA['BLOQUEADO_FINANCEIRO']` mantido estritamente como `{'Cancelada'}`.
   - Qualquer tentativa de transicionar uma venda bloqueada para `Pendente` via tela ou API (ex.: action `alterar_status` chamada por VENDEDOR ou GERENTE) é sumariamente rejeitada com HTTP 400 (`test_13`).
   - O desbloqueio continua sendo atribuição exclusiva de `vendas/services/liberacao_service.py::liberar_bloqueio_venda()`, que exige autorização formal, justificativa e grava LiberacaoBloqueio junto ao histórico.
   - A transição `Pendente` → `BLOQUEADO_FINANCEIRO` é aceita apenas quando disparada com `origem='SISTEMA'`; chamadas diretas por usuário via API/tela recebem HTTP 400.
2. **Cascata Automática com Auditoria de Usuário (Revisão 2):**
   - A checagem de papel comercial em `transicionar_venda` (`validar_papel_alteracao`) foi restringida para `origem in ('TELA', 'APP_CAMPO')`.
   - Quando um MOTORISTA despacha a entrega para `'Em Rota'` pelo PWA/API da logística, as vendas vinculadas transicionam com `origem='SISTEMA'`, gravando no histórico o `alterado_por=motorista` sem que o motorista precise ter permissões comerciais na empresa (`test_14`).
3. **Avaliação de Crédito Comercial Desacoplada de Módulo (Revisão 2):**
   - Restaurada a avaliação de crédito na criação do pedido independentemente da contratação do módulo financeiro (comportamento original da Sprint 11C), mantendo a gravação do histórico e o tratamento explícito de exceções.
4. **Eliminação de alterações de status sem histórico e fim do `.update(status=)` em lote (Revisão 1):**
   - Em `EntregaViewSet.perform_update`, eliminou-se `updated_entrega.vendas.filter(...).update(status=...)`. Todas as vendas vinculadas são transicionadas uma a uma via `transicionar_venda` com `origem='SISTEMA'`.
   - `EntregaSerializer.status` tornado `read_only = True`. Mudanças de status via API/Tela passam obrigatoriamente pela validação e gravação de histórico.
   - Em `logistica/services/seguros_sinistros.py`, cancelamentos de entregas/pedidos e reagendamento de viagens por sinistro passam por `transicionar_entrega` e `transicionar_venda`.
   - Adicionado teste estático rigoroso (`test_12_static_scan_sem_update_status_nem_atribuicao_direta_fora_services`) que varre o repositório inteiro via regex garantindo zero `.update(status=` em vendas/entregas e zero atribuições diretas fora dos serviços autorizados.
5. **Consistência Atômica (Revisão 1):**
   - `transicionar_venda` e `transicionar_entrega` decorados com `@transaction.atomic`. O próprio serviço persiste o novo status no banco de dados (`save(update_fields=[...])`).
   - Se qualquer validação falhar, nada é alterado no banco e nenhum histórico órfão é gravado (`test_09`).
6. **Auditoria de Origem vs Usuário (Revisão 1):**
   - `usuario=None` só é aceito com `origem='SISTEMA'` ou `'API'`.
   - Com `origem='TELA'` ou `'APP_CAMPO'`, exige obrigatoriamente usuário autenticado, disparando `ValidationError` caso contrário (`test_08`).

---

## 3. O que ficou de fora e por quê

- **Monitor de TV (`/painel/<token>/`):** Escopo da Entrega 01B.01 (tarefa 01B.2).
- **Home de Gestão e Painel de KPIs:** Escopo da Entrega 01B.02 (tarefas 01B.3 a 01B.6).

---

## 4. Decisões tomadas por premissa e decisões pendentes para o dono

### Tabela `TRANSICOES_ENTREGA` (Premissas para validação do Dono do Produto)
A máquina de estados da Entrega foi parametrizada em `logistica/services/status.py::TRANSICOES_ENTREGA` com as seguintes transições permitidas:
1. **`Agendada` → `{'Em Produção', 'Em Rota', 'Cancelada'}`:**
   - *Em Produção:* Início de carregamento/separação física no pátio.
   - *Em Rota:* Saída do caminhão (direto da triagem ou após carga).
   - *Cancelada:* Cancelamento pré-viagem por motivos comerciais ou operacionais.
2. **`Em Produção` → `{'Em Rota', 'Cancelada'}`:**
   - *Em Rota:* Conclusão do carregamento e partida do veículo.
   - *Cancelada:* Abortamento do carregamento.
3. **`Em Rota` → `{'Concluída', 'Cancelada', 'Agendada'}`:**
   - *Concluída:* Finalização normal de todas as paradas/comprovantes.
   - *Cancelada:* Interrupção de rota por sinistro com perda total da carga.
   - *Agendada (Premissa para o dono validar):* Reagendamento de viagem por sinistro com reposição de carga avariada (implementado no fluxo `logistica/services/seguros_sinistros.py::resolver_sinistro` com decisão `reentregar`).
4. **`Concluída` → `set()` (Estado final):**
   - Nenhuma transição permitida após a conclusão da rota.
5. **`Cancelada` → `{'Agendada'}` (Premissa para o dono validar):**
   - Permite reativar ou reagendar uma entrega anteriormente cancelada para uma nova tentativa operacional sem necessidade de recriar o romaneio do zero.

### Decisão pendente para o dono (Módulo Financeiro vs Avaliação de Crédito Comercial)
- **Avaliação de crédito comercial na criação da venda:** Atualmente, a avaliação de crédito comercial ocorre independentemente de a empresa ter contratado o módulo Financeiro (comportamento herdado da Sprint 11C). Fica registrado como decisão pendente para o Dono do Produto definir se empresas sem o módulo Financeiro ativo devem ou não ter a avaliação e bloqueio automático de pedidos de venda.

---

## 5. Resultado da suíte de testes

- **Comando:** `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- **Total de testes:** **724 passed**, 4 warnings em 2m47s.
- **Zero falhas.**

---

## 6. Lista de commits

1. `eb3b84d`: `feat(vendas): modelo HistoricoStatusVenda, servico de transicao e rastreabilidade`
2. `84f73f6`: `feat(logistica): modelo HistoricoStatusEntrega, servico de transicao e rastreabilidade`
3. `4f42de0`: `test(vendas): testes de historico de status de vendas e entregas`
4. `aed1fce`: `fix(vendas,logistica): correcoes da revisao da entrega 01b.00 para rastreabilidade estrita e atomicidade`
5. `[commit atual]`: `fix(vendas): protecao contra desbloqueio indevido de credito e cascata com auditoria de usuario`

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
- [x] **Falha antes:** `usuario=None` é recusado com `origem='TELA'` e `'APP_CAMPO'` e aceito com `'SISTEMA'` e `'API'` (`test_08_usuario_obrigatorio_para_tela_e_app_campo`).
- [x] **Falha antes:** Atomicidade estrita com `save(update_fields=...)` embutido nos serviços de transição (`test_09_atomicidade_se_validacao_falhar_nem_status_nem_historico_mudam`).
- [x] **Falha antes:** `EntregaSerializer.status` é `read_only` e PATCH na API transiciona individualmente cada venda vinculada (`test_10_entrega_serializer_status_read_only_e_patch_transiciona_vendas`).
- [x] **Falha antes:** Cancelamento e reagendamento por sinistro usam serviços de transição auditados (`test_11_sinistros_reagendamento_e_cancelamento_usam_transicoes`).
- [x] **Falha antes:** Verificação estática com zero `.update(status=` em vendas/entregas e zero atribuição direta fora dos serviços autorizados (`test_12_static_scan_sem_update_status_nem_atribuicao_direta_fora_services`).
- [x] **Falha antes (Revisão 2):** `BLOQUEADO_FINANCEIRO` protegido contra desbloqueio indevido por vendedor/gerente em `alterar_status`, bloqueio direto por usuário negado, e liberação formal preservada (`test_13_revisao2_bloqueio_financeiro_protegido_contra_desbloqueio_indevido`).
- [x] **Falha antes (Revisão 2):** Motorista despacha entrega em cascata automática sem erro de papel comercial e com auditoria de usuário (`test_14_revisao2_cascata_automatica_motorista_despacha_entrega_e_vendas_mudam`).

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
   ================= 724 passed, 4 warnings in 167.18s (0:02:47) =================
   ```
4. **Integridade de Documentação:**
   - Comentários e regras do sistema preservados.
5. **Git Status:**
   - Working tree limpa e rastreada.
