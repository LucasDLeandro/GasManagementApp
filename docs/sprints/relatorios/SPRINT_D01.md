# Relatório — Sprint D01: Banco de dados PostgreSQL 16

- **Branch:** `sprint-d01/postgresql` (criada a partir de `correcao-c01/patrimonio-retestes-financeiro`, pois a C01 ainda não foi mergeada em `fase-2/produtos`).
- **Banco local na estação (D2):** EDB PostgreSQL **16.16** (zip archive Windows x86-64 em `C:\Temp\pgsql16`, cluster UTF-8 em `C:\Temp\pgsql16_data`, porta `5432`).
- **Driver:** `psycopg[binary]>=3.2.0` (`psycopg[binary]==3.3.9` instalado no `venv` Python 3.13; conferida no PyPI a existência de wheel `cp314-manylinux2014_x86_64` para o servidor Ubuntu 24.04 Python 3.14).

---

## 1. Diagnóstico inicial no PostgreSQL (antes das correções)

1. **Bloqueio inicial de migrações (todos os testes de banco falharam no setup):**
   - `core/tenancy.py` (`get_default_tenant_pk`): durante `produtos.0002_produto_tenant`, consultava `Tenant.objects` (selecionando colunas de migrações futuras ainda inexistentes em `core_tenant`) dentro de `try/except`, o que no PostgreSQL abortava a transação inteira (`psycopg.errors.InFailedSqlTransaction`).
   - `produtos/migrations/0005_vinculolegadoinferido_and_more.py`: `UPDATE produtos_movimentacaocilindro SET is_legado = 1;` falhava com `DatatypeMismatch: column "is_legado" is of type boolean but expression is of type integer`.
2. **Suíte após desbloquear migrações (`781 passed, 14 failed`):**
   - **Truncamento de `CharField` ignorado pelo SQLite (12 falhas):**
     - `accounts/tests.py` (4 falhas): `UserProfile.cpf` tinha `max_length=11`, mas a aplicação e os testes gravam CPF formatado com 14 caracteres (`123.456.789-00`).
     - `fiscal/tests/test_sprint11a_fiscal_nfe.py` (3 falhas): `Venda.documento_fiscal_ref` tinha `max_length=60`, mas `emitir_nfe_venda` grava `f"NF-e {numero}/{serie} - Chave {chave_acesso}"` (61+ caracteres).
     - `fiscal/tests/test_sprint11b_fiscal_gases.py` (5 falhas): `DocumentoFiscal.tipo_operacao` tinha `max_length=10`, mas serviços gravam `'REMESSA_COMODATO'`, `'RETORNO_COMODATO'`, `'FATURA_LOCACAO'`, `'RECARGA_TERCEIRO'` e `'CTE_TRANSPORTE'` (14–16 caracteres).
   - **`QueryDict` vs lista em `envios-reteste` (1 falha):**
     - `produtos/tests/test_sprint03_produtos_retestes_baixa.py::test_retorno_aprovado_atualiza_datas_conforme_modelo`: `EnvioRetesteViewSet.create` lia `request.data.get('cilindro_ids', [])` em vez de `getlist`, retornando string `'510'` em `multipart/form-data`. No SQLite funcionava por coincidência quando `id < 10` (`len('1') == 1`).
   - **Trigger real de imutabilidade apagada pelo próprio teste (1 falha):**
     - `financeiro/tests/test_sprint9a_financeiro_base.py::DatabaseTriggerImutabilidadeTests.tearDown`: executava `DROP TRIGGER IF EXISTS prevent_update_delete_lancamento` no PostgreSQL, removendo a trigger real criada pela migração `0002_triggers_imutabilidade`.

---

## 2. O que foi feito

1. **Configuração e dependências:**
   - `requirements.txt`: adicionado `psycopg[binary]>=3.2.0` (sem dependências MySQL no repositório).
   - `config/settings.py`: corrigido padrão de `DB_PORT` para `'5432'` quando `'postgresql' in DB_ENGINE`, removido padrão `'root'` de `DB_USER` (agora `''`), adicionado `CONN_MAX_AGE` lido de `DB_CONN_MAX_AGE` (padrão `60`), mantendo `ATOMIC_REQUESTS: True` e sem credenciais fixas.
   - Criado `.env.example` documentando variáveis de PostgreSQL e segurança.
2. **Correções reais descobertas pelo PostgreSQL:**
   - `core/tenancy.py`: `get_default_tenant_pk()` agora usa `with transaction.atomic():` (savepoint) e `.values_list('id', flat=True).first()`, evitando abortar a transação em migrações iniciais.
   - `produtos/migrations/0005_vinculolegadoinferido_and_more.py`: alterado `is_legado = 1` para `is_legado = TRUE`.
   - `accounts/models.py` (`accounts/migrations/0005_alter_userprofile_cpf.py`): `cpf` ampliado de `11` para `14` caracteres.
   - `vendas/models.py` (`vendas/migrations/0014_alter_venda_documento_fiscal_ref.py`): `documento_fiscal_ref` ampliado de `60` para `120` caracteres.
   - `fiscal/models.py` (`fiscal/migrations/0003_alter_documentofiscal_tipo_operacao.py`): `tipo_operacao` ampliado de `10` para `30` caracteres.
   - `produtos/views.py`: `PatrimonioViewSet.enviar_reteste` e `EnvioRetesteViewSet.create` agora tratam `request.data.getlist('cilindro_ids')` e string/int unitário.
   - `produtos/services/baixa.py`: corrigido bug real de concorrência em `baixar_cilindro_patrimonial` — `validar_transicao_status_cilindro` aceitava `BAIXADO -> BAIXADO` como no-op; agora `baixar_cilindro_patrimonial` rejeita explicitamente se `cilindro.status == 'BAIXADO'` após adquirir o lock `select_for_update()`.
3. **Testes de concorrência, triggers e `loaddata`:**
   - Ajustados `core/tests/test_sprint7b_saas_governanca.py`, `produtos/tests/test_sprint8c_granel_custo_envase.py` e `fiscal/tests/test_sprint11a_fiscal_nfe.py` para usar `sqlite_lock` somente quando `connection.vendor == 'sqlite'` e fechar conexões nas threads.
   - Ajustado `DatabaseTriggerImutabilidadeTests` (`financeiro/tests/test_sprint9a_financeiro_base.py`) para não apagar as triggers da migração `0002` no PostgreSQL, usando `DISABLE/ENABLE TRIGGER USER` com `try/finally` apenas durante a simulação de corrupção de hash.
   - Criado `tests/test_concorrencia_postgresql.py` com 4 testes reais usando `threading.Barrier(2)` (pulados no SQLite) + `TestLoaddataRawSemEfeitosColaterais` garantindo que `loaddata` (`raw=True`) não gera registros duplicados de auditoria/movimentação.
4. **Prova de captura de corrida sem `select_for_update()`:**
   Removido temporariamente `.select_for_update()` em `produtos/services/baixa.py` e executado `test_01_baixa_patrimonial_concorrente_mesmo_cilindro` no PostgreSQL 16 (restaurado logo em seguida):
   ```text
   FAILED tests/test_concorrencia_postgresql.py::TestConcorrenciaRealPostgresql::test_01_baixa_patrimonial_concorrente_mesmo_cilindro
   >       self.assertEqual(len(sucessos), 1, f"Esperado 1 sucesso, obtido {sucessos}")
   E       AssertionError: 2 != 1 : Esperado 1 sucesso, obtido [6, 7]
   ```
5. **Comando `contar_registros`, teste end-to-end da migração e Runbook:**
   - Criado `core/management/commands/contar_registros.py` usando `.unscoped` / `_base_manager`.
   - Testada a migração completa em cópia do `db.sqlite3` (`C:\Temp\baros_src.sqlite3`) → banco PostgreSQL `baros_mig_test` → `pg_dump -Fc` → `pg_restore` em `baros_restore_test`:
     - **Atenção encontrada no teste:** `flush --no-input` apaga `django_content_type` (quebrando a chave natural de `auth.Group`), e sem limpar seeds de migrações de dados ocorre `UniqueViolation` em `core_planosaas` e `auth_group`. A solução validada e documentada no runbook é `TRUNCATE TABLE core_planosaas, auth_group RESTART IDENTITY CASCADE;` após `migrate` e antes de `loaddata`.
     - Contagem idêntica antes (SQLite) e depois (PostgreSQL e após `pg_restore`): **`TOTAL: 1117`** (`accounts.User: 6`, `auth.Group: 5`, `clientes.Cliente: 55`, `clientes.ContratoComodato: 33`, `clientes.DiaCilindro: 281`, `core.Filial: 3`, `core.Membership: 7`, `core.PerfilRegulatorioTenant: 3`, `core.PlanoSaaS: 3`, `core.ResponsavelTecnico: 2`, `core.Tenant: 3`, `financeiro.AlcadaAprovacao: 3`, `financeiro.CentroCusto: 12`, `financeiro.CondicaoPagamento: 12`, `financeiro.ParametroFinanceiroTenant: 3`, `financeiro.PlanoContas: 243`, `logistica.ConfiguracaoCombustivelFrota: 1`, `logistica.ConfiguracaoRentabilidade: 1`, `logistica.ConfiguracaoSeguros: 1`, `logistica.Entrega: 22`, `logistica.HistoricoStatusEntrega: 22`, `logistica.Rota: 16`, `logistica.Veiculo: 18`, `produtos.AuditoriaBloqueioSanitario: 2`, `produtos.Cilindro: 36`, `produtos.ClasseAtivo: 3`, `produtos.EnvaseCilindro: 18`, `produtos.FabricanteCilindro: 6`, `produtos.GasQuimico: 3`, `produtos.HistoricoQualidadeLote: 1`, `produtos.HistoricoRetesteHidrostatico: 16`, `produtos.InspecaoPreEnvase: 12`, `produtos.LoteEnvase: 10`, `produtos.ModeloCilindro: 6`, `produtos.MovimentacaoCilindro: 34`, `produtos.Produto: 17`, `produtos.SkuRecarga: 6`, `produtos.TabelaIndenizacaoCilindro: 3`, `vendas.HistoricoStatusVenda: 54`, `vendas.ItemVenda: 81`, `vendas.Venda: 54`).
   - Criado `docs/runbooks/RUNBOOK_MIGRACAO_POSTGRESQL.md` e atualizados `docs/sprints/00_REGRAS_GERAIS.md`, `docs/PROGRESSO.md`, `CLAUDE.md`, `docs/sprints/S15_go_live.md` e `docs/sprints/README.md`.

---

## 3. Verificação final (Definição de pronto)

- `manage.py check --database default` (PostgreSQL 16): `System check identified no issues (0 silenced).`
- `manage.py makemigrations --check --dry-run` (PostgreSQL 16): `No changes detected`
- **Suíte completa no PostgreSQL 16 (`pytest -q -p no:cacheprovider --create-db`):** **`800 passed, 4 warnings in 1019.15s (0:16:59)`** (incluindo `tests/test_concorrencia_postgresql.py`, `tests/test_integridade_js.py` e `tests/test_u01_interface_layout.py`).
- **Suíte completa no SQLite (`pytest -q -p no:cacheprovider`):** **`796 passed, 4 skipped, 4 warnings in 219.79s (0:03:39)`** (os 4 pulos são exclusivamente os testes de `Barrier` marcados com `@unittest.skipIf(connection.vendor == 'sqlite', ...)`).

---

## 4. Notas de deploy

1. **Dependência nova:** `psycopg[binary]>=3.2.0` em `requirements.txt` (`pip install -r requirements.txt` na EC2).
2. **Banco novo na EC2:** instalar PostgreSQL 16 local (`localhost:5432`), criar usuário/banco e seguir passo a passo `docs/runbooks/RUNBOOK_MIGRACAO_POSTGRESQL.md` (parar aplicação, backup de `db.sqlite3`, `migrate` no SQLite, `contar_registros`, `dumpdata`, configurar `.env` com `DB_ENGINE=django.db.backends.postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST=localhost`, `DB_PORT=5432`, `DB_CONN_MAX_AGE=60`, `migrate` no PG, `TRUNCATE TABLE core_planosaas, auth_group RESTART IDENTITY CASCADE;`, `loaddata`, `sqlsequencereset`, conferir `contar_registros`, configurar cron diário de `pg_dump -Fc`).
3. **Migrações novas:** `accounts.0005_alter_userprofile_cpf`, `fiscal.0003_alter_documentofiscal_tipo_operacao`, `vendas.0014_alter_venda_documento_fiscal_ref` (e ajuste booleano `is_legado = TRUE` em `produtos.0005` para bancos novos).

---

## D01.1 — Ajustes finais antes do deploy

### O que foi feito
1. **`docs/runbooks/RUNBOOK_MIGRACAO_POSTGRESQL.md`:**
   - Alterado o destino do `dumpdata` de `/tmp` para `/var/backups/baros/baros_dump_AAAAMMDD.json`, com `chmod 600 /var/backups/baros/baros_dump_*.json` logo após a exportação.
   - Incluído o passo final removendo o dump JSON (`/var/backups/baros/baros_dump_*.json`) após a conferência do `contar_registros`.
   - Adicionada na seção de rollback a regra explícita de que voltar ao SQLite só é seguro antes de liberar o uso do sistema (lançamentos posteriores no PostgreSQL seriam perdidos) e que a decisão ocorre no mesmo dia da virada.
2. **`core/seeds.py` e `produtos/tests/test_c01_correcoes.py`:**
   - Em `executar_seeds(..., capturar_erros=True)`, cada seed agora executa dentro de `with transaction.atomic():` (savepoint), preservando a transação da requisição (`ATOMIC_REQUESTS=True`) no PostgreSQL quando um seed falha com erro de banco (`IntegrityError`).
   - Adicionado `C01CorrecoesTests.test_08_backoffice_toggle_modulo_com_integrity_error_no_seed_grava_auditoria` simulando `UniqueViolation` dentro do seed e validando resposta `200`, `aviso_seed` e gravação de `LogAuditoriaSaaS`.
3. Removida a linha em branco extra ao final de `SPRINT_D01.md`.

### Saída do teste `test_08` no PostgreSQL 16 (antes e depois da correção)

**Antes (`core/seeds.py` sem savepoint):**
```text
psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "core_tenant_cnpj_key"
DETAIL:  Key (cnpj)=(12345678000190) already exists.
...
  File "C:\Lucas\GasManagementApp\core\views_baros_admin.py", line 489, in post
    LogAuditoriaSaaS.objects.create(
...
django.db.transaction.TransactionManagementError: An error occurred in the current transaction. You can't execute queries until the end of the 'atomic' block.
FAILED produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_08_backoffice_toggle_modulo_com_integrity_error_no_seed_grava_auditoria
1 failed, 7 deselected in 6.91s
```

**Depois (`core/seeds.py` com `transaction.atomic()` quando `capturar_erros=True`):**
```text
produtos\tests\test_c01_correcoes.py .                                   [100%]
1 passed, 7 deselected in 2.90s
```

### Verificação final (D01.1)
- `manage.py check --database default` (PostgreSQL 16): `System check identified no issues (0 silenced).`
- `manage.py makemigrations --check --dry-run` (PostgreSQL 16): `No changes detected`
- **Suíte completa no PostgreSQL 16 (`pytest -q -p no:cacheprovider --create-db`):** `801 passed, 4 warnings in 1054.77s (0:17:34)`
- **Suíte completa no SQLite (`pytest -q -p no:cacheprovider`):** `797 passed, 4 skipped, 4 warnings in 176.83s (0:02:56)`
- **`git status --short`:** limpo.
