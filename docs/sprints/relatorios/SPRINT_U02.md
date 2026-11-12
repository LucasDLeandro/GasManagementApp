# Relatório — Sprint U02: Financeiro — primeiros passos e plano de contas padrão

**Data:** 12/11/2026
**Branch:** `sprint-u02/financeiro-primeiros-passos` (a partir de `sprint-u01/interface-layout`)
**Commit de código/testes:** `3cd0100`

## Plano inicial
- **Arquivos alterados/criados:**
  - `core/seeds.py`: registrar `seed_financeiro_padrao_completo` (chamando `seed_financeiro_tenant_completo`) no módulo `'financeiro'`.
  - `core/views_baros_admin.py`: chamar `executar_seeds(tenant, modulo=modulo)` ao ligar um módulo em `BarosAdminToggleModuloView.post`.
  - `financeiro/seeds.py`: adicionar `aplicar_seed_tenants_plano_vazio()` para popular tenants com `modulo_financeiro_ativo=True` e `PlanoContas` vazio.
  - `financeiro/migrations/0012_seed_plano_contas_tenants_ativos.py`: migration de dados chamando `aplicar_seed_tenants_plano_vazio()` (`RunPython`, reverso `noop`).
  - `financeiro/views.py`: restringir `PlanoContasViewSet.seed_padrao` a `IsTenantAdmin` (e `RequiresModuleFinanceiro`) e aplicar `seed_financeiro_tenant_completo(tenant)`.
  - `financeiro/selectors/balancete.py`: adicionar `sem_lancamentos` (`not qs_periodo.exists()`) e `status_texto` (`'Sem lançamentos no período'`, `'ZERADO (OK)'` ou `'DIVERGENTE'`).
  - `templates/base_dashboard.html`: corrigir `{% if modulos_ativos.financeiro or is_admin %}` para `{% if modulos_ativos.financeiro or request.user.is_superuser %}` no link do menu Financeiro.
  - `templates/financeiro/dashboard.html`: simplificar subtítulo do cabeçalho, exibir `"Sem lançamentos no período"` no cartão de Balancete quando não houver partidas, e exibir o card `"Primeiros passos no Financeiro"` enquanto faltar plano de contas, conta financeira ou condição de pagamento (com botão `"Aplicar plano de contas padrão"` visível apenas para `ADMIN`, via `Baros.confirmar` e `Baros.api`).
  - `financeiro/tests/test_u02_financeiro_primeiros_passos.py`: 5 testes cobrindo seed ao ligar módulo, balancete sem lançamentos, permissão de `seed-padrao`, backfill apenas em módulo ativo com plano vazio, e ocultação do menu + `403` na tela.

## O que foi feito
1. **Seed automático ao ligar o módulo Financeiro (`core/seeds.py`, `core/views_baros_admin.py`):**
   - `core/services/onboarding.py` já chamava `executar_seeds(tenant)`. Ao registrar `seed_financeiro_padrao_completo` no registro `'financeiro'` em `core/seeds.py`, tanto o onboarding quanto o toggle de módulo no backoffice (`/baros-admin/` → `BarosAdminToggleModuloView.post` quando `novo_valor=True`) passam a executar `seed_financeiro_tenant_completo(tenant)` de forma idempotente.
2. **Backfill para empresas existentes com módulo ativo e plano vazio (`financeiro/seeds.py`, `financeiro/migrations/0012_seed_plano_contas_tenants_ativos.py`):**
   - `aplicar_seed_tenants_plano_vazio()` percorre apenas `Tenant.objects.filter(modulo_financeiro_ativo=True)` cujo `PlanoContas.unscoped.filter(tenant=tenant).exists()` seja falso e aplica `seed_financeiro_tenant_completo(tenant)` dentro de `tenant_context(tenant)`.
   - Executada automaticamente via migration `0012_seed_plano_contas_tenants_ativos` (com dependência em `('core', '0013_painelmonitor')` e `('financeiro', '0011_promessapagamento_limitecreditocliente_and_more')`).
3. **Restrição do endpoint `POST /financeiro/api/plano-contas/seed-padrao/` (`financeiro/views.py`):**
   - `@action(..., permission_classes=[IsAuthenticated, IsTenantAdmin, RequiresModuleFinanceiro, IsTenantSubscriptionActive])` garante que apenas `ADMIN` da empresa (ou superusuário, conforme `IsTenantAdmin`) com módulo financeiro ativo possa executar; outros papéis ou empresas sem o módulo recebem `403`.
4. **Balancete sem lançamentos (`financeiro/selectors/balancete.py`, `templates/financeiro/dashboard.html`):**
   - Quando `qs_periodo` não possui `PartidaContabil`, `obter_balancete_verificacao` retorna `sem_lancamentos=True`, `fechamento_correto=False` e `status_texto='Sem lançamentos no período'`. O card da tela exibe `"Sem lançamentos no período"` sem classe `.success`.
5. **Estado vazio "Primeiros passos" e linguagem simples (`templates/financeiro/dashboard.html`):**
   - Subtítulo alterado para `"Plano de contas, contas bancárias e caixa, balancete, títulos e controle financeiro."` (removida a menção técnica a razão imutável SHA-256).
   - Seção `#fin-primeiros-passos` exibida no topo quando `not plano_contas or not contas_financeiras or not condicoes`, mostrando o status (`Configurado` / `Pendente`) de: (1) Plano de contas, (2) Conta bancária ou caixa, (3) Condições de pagamento.
   - Botão `#btn-seed-plano-padrao` (`Aplicar plano de contas padrão`) renderizado apenas `{% if is_admin %}`, com confirmação via `Baros.confirmar(...)` e chamada via `Baros.api('/financeiro/api/plano-contas/seed-padrao/', ...)`.
6. **Segregação do menu Financeiro (`templates/base_dashboard.html`):**
   - Alterado `{% if modulos_ativos.financeiro or is_admin %}` para `{% if modulos_ativos.financeiro or request.user.is_superuser %}`. Assim, um `ADMIN` comum de empresa sem o módulo financeiro não vê o link no menu lateral e recebe `403` ao acessar `/financeiro/`.

## Decisões pendentes
- **Plano de contas padrão (`financeiro/seeds.py`):** O plano de contas inicial aplicado pelo seed automático e pelo botão "Aplicar plano de contas padrão" é uma premissa técnica e precisa de validação do contador antes de uso fiscal/contábil definitivo pelos clientes.

## Testes que falharam antes
- `financeiro/tests/test_u02_financeiro_primeiros_passos.py` foi criado antes da implementação. Na execução inicial antes das correções de modelo/campo no teste e código, o arquivo falhou na configuração do fixture (`AttributeError` em `nome` e `TypeError` em `slug` de `Tenant`) e antes da implementação não existiam `aplicar_seed_tenants_plano_vazio`, `sem_lancamentos` no balancete, restrição `IsTenantAdmin` em `seed-padrao`, execução de seed no toggle de módulo nem ocultação do menu para `is_admin` sem módulo. Após implementar todas as correções, os 5 testes passaram (`5 passed in 63.45s`).

## Critérios de aceite e pendências de navegador
- **Verificação automática:** Coberta pelos 5 novos testes em `financeiro/tests/test_u02_financeiro_primeiros_passos.py` e pela suíte completa (`788 passed`).
- **Pendências de verificação visual no navegador:**
  - Abrir `/financeiro/` com usuário `ADMIN` de empresa com módulo ativo e sem plano/conta/condição para validar visualmente o card `"Primeiros passos no Financeiro"` e o fluxo do botão `"Aplicar plano de contas padrão"`.
  - Abrir `/financeiro/` com usuário não-admin para confirmar que o botão `"Aplicar plano de contas padrão"` não aparece.
  - Abrir `/inicio/` e `/financeiro/` com usuário comum (`ADMIN` não-superuser) de empresa sem módulo financeiro para confirmar ausência do menu e resposta `403`.

## Notas de deploy
- **Nova migration:** `financeiro/migrations/0012_seed_plano_contas_tenants_ativos.py` (`RunPython` idempotente). Rodar `python manage.py migrate` no deploy; aplicará o plano de contas, centros de custo e condições de pagamento padrão apenas nas empresas com `modulo_financeiro_ativo=True` que ainda não tenham nenhum registro em `PlanoContas`.

## Saída dos checks (após o último ajuste)
- `venv/Scripts/python.exe manage.py check`: `System check identified no issues (0 silenced).`
- `venv/Scripts/python.exe manage.py makemigrations --check --dry-run`: `No changes detected`
- `venv/Scripts/python.exe -m pytest financeiro/tests/test_u02_financeiro_primeiros_passos.py -v`: `5 passed in 63.45s`
- `venv/Scripts/python.exe -m pytest tests/test_integridade_js.py tests/test_u01_interface_layout.py -v`: `6 passed` (`Node.js v24.11.1` disponível no PATH)
- `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`: `788 passed, 4 warnings in 172.39s`
