# Relatório da Sprint C01 — Correções das Sprints 02, 03, H01, U01 e U02

**Data:** 13/11/2026  
**Branch:** `correcao-c01/patrimonio-retestes-financeiro` (a partir de `sprint-u02/financeiro-primeiros-passos`)  
**Status:** Concluída (verificação visual em navegador pendente para o dono)

---

## 1. O que foi feito

1. **Baixa patrimonial imutável (`produtos/views.py`, `produtos/serializers.py`):**
   - `BaixaPatrimonialViewSet` limitado a `http_method_names = ['get', 'post', 'head', 'options']` (PATCH, PUT e DELETE respondem `405`).
   - `BaixaPatrimonialSerializer`: `status_anterior`, `usuario`, `usuario_estorno` e `motivo_estorno` marcados como `read_only_fields`, e `cilindro` travado como `read_only` quando `self.instance is not None`.

2. **Envio para reteste (`produtos/views.py`):**
   - `EnvioRetesteViewSet` limitado a `http_method_names = ['get', 'post', 'head', 'options']`.
   - Criada a permissão `SomenteEnvioRetesteAltera` liberando leitura para todo membro com módulo patrimônio ativo e restringindo escrita (D1) a `ADMIN`, `GERENTE`, `RESPONSAVEL_TECNICO` e `OPERADOR_PATIO` (`VENDEDOR` e `MOTORISTA` recebem `403`).

3. **Retificação de reteste (`produtos/views.py`):**
   - Criada a permissão `SomenteRetificacaoReteste` aplicada à action `retificar`, restringindo a `ADMIN`, `GERENTE` e `RESPONSAVEL_TECNICO` (D2); demais papéis recebem `403`.
   - Resolução via `reteste_antigo = self.get_object()` antes de chamar `retificar_reteste` (reteste de outra empresa responde `404`).
   - Validação obrigatória de `motivo` (aceitando `motivo` ou legado `observacoes`) com no mínimo 10 caracteres; quando inválido, responde `400` no formato `{"motivo": ["..."]}`.
   - Montagem explícita de `dados` campo a campo via `request.data.get(...)` em vez de `dict(request.data)`.

4. **Baixa a partir de cilindro condenado (`produtos/static/produtos/js/retestes.js`, `produtos/static/produtos/js/cilindros_drawer.js`, `produtos/templates/produtos/index/_drawer_cilindro.html`):**
   - No fluxo `REPROVADO_CONDENADO` de `retestes.js`, o modal de baixa só abre quando `RETESTES_CONFIG.podeEditarPatrimonio` é verdadeiro; para os demais papéis, exibe `Baros.aviso` orientando que um Administrador ou Gerente precisa registrar a baixa.
   - No drawer (`_drawer_cilindro.html`), o botão `#drawer-btn-dar-baixa` já estava protegido por `{% if pode_editar_patrimonio and modulos_ativos.patrimonio %}`.

5. **Data local (`core/static/core/js/core.js`, `retestes.js`, `cilindros_drawer.js`):**
   - Adicionada `Baros.hojeISO()` em `core.js` retornando `AAAA-MM-DD` no fuso local.
   - Substituídas todas as ocorrências de `new Date().toISOString().slice(0, 10)` em `retestes.js` (4 ocorrências) e `cilindros_drawer.js` (2 ocorrências) por `Baros.hojeISO()`.
   - Atualizado `?v=20261113_c01` em `templates/base_dashboard.html` (`core.js`), `templates/baros_admin/base.html` (`baros_admin.js`), `produtos/templates/produtos/retestes/index.html` (`retestes.js`) e `produtos/templates/produtos/index.html` (`cilindros_drawer.js`).

6. **Seed financeiro fora da migração — D3 (`financeiro/management/commands/seed_financeiro_plano_vazio.py`, `financeiro/migrations/0012_seed_plano_contas_tenants_ativos.py`):**
   - Criado o comando `seed_financeiro_plano_vazio` com suporte a `--dry-run`, aplicando `aplicar_seed_tenants_plano_vazio()` apenas nas empresas com `modulo_financeiro_ativo=True` e `PlanoContas` vazio.
   - A migração `0012_seed_plano_contas_tenants_ativos.py` (que ainda não foi aplicada no servidor) foi convertida para `migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)` sem import de `financeiro.seeds` (conforme regra 3.11 de `00_REGRAS_GERAIS.md`).
   - Seed automático mantido ao ligar o módulo (backoffice e onboarding).

7. **Erro de seed visível no backoffice (`core/views_baros_admin.py`, `core/static/core/js/baros_admin.js`):**
   - Em `BarosAdminToggleModuloView.post`, quando `executar_seeds(tenant, modulo=modulo)` lança exceção, o erro é registrado via `logger.exception`, o módulo permanece ligado (`ativo=True`, `seed_aplicado=False`) e o JSON devolve `aviso_seed` explicando a falha e como aplicar pela tela Financeiro ("Aplicar plano de contas padrão").
   - Em `baros_admin.js`, quando `r.aviso_seed` está presente, exibe `Swal.fire({ icon: 'warning', ... })` com a mensagem retornada.
   - O comportamento de `executar_seeds` no onboarding não foi alterado (continua propagando exceção em caso de falha).

8. **Erratas em `SPRINT_02.md` e `SPRINT_03.md`:**
   - Adicionada a seção `## Errata (Sprint C01)` ao final de `docs/sprints/relatorios/SPRINT_02.md` e `docs/sprints/relatorios/SPRINT_03.md`, preservando o restante dos relatórios.

---

## 2. Bugs encontrados no caminho

- `produtos/tests/test_sprint03_produtos_retestes_baixa.py::test_retorno_aprovado_atualiza_datas_conforme_modelo` enviava `observacoes` (campo legado) no `POST .../retificar/`. Ajustado `retificar` para aceitar `motivo` ou `observacoes` mantendo a obrigatoriedade de no mínimo 10 caracteres.
- No início da sprint, o working tree continha 8 arquivos modificados apenas por formatação/fim de linha fora do escopo (incluindo `current_tenant.id==t.id` em `templates/base_dashboard.html`), que foram restaurados antes da execução.

---

## 3. Prova do teste da U02 no commit `e92177d`

Worktree temporário criado em `C:/Temp/baros_u02_antes` no commit `e92177d` (anterior à U02), executado com `C:/Lucas/GasManagementApp/venv/Scripts/python.exe -m pytest financeiro/tests/test_u02_financeiro_primeiros_passos.py -v` e removido em seguida com `git worktree remove`. Nenhum ajuste foi necessário no arquivo de teste da U02 — todos os 5 testes falharam diretamente por asserção / símbolo ausente:

```text
financeiro/tests/test_u02_financeiro_primeiros_passos.py::U02FinanceiroPrimeirosPassosTests::test_01_ligar_modulo_financeiro_executa_seed_idempotente FAILED [ 20%]
financeiro/tests/test_u02_financeiro_primeiros_passos.py::U02FinanceiroPrimeirosPassosTests::test_02_balancete_sem_lancamentos_informa_estado FAILED [ 40%]
financeiro/tests/test_u02_financeiro_primeiros_passos.py::U02FinanceiroPrimeirosPassosTests::test_03_action_seed_padrao_restrita_a_admin_e_modulo_ativo FAILED [ 60%]
financeiro/tests/test_u02_financeiro_primeiros_passos.py::U02FinanceiroPrimeirosPassosTests::test_04_comando_seed_aplica_apenas_modulo_ativo_e_plano_vazio FAILED [ 80%]
financeiro/tests/test_u02_financeiro_primeiros_passos.py::U02FinanceiroPrimeirosPassosTests::test_05_usuario_sem_modulo_nao_ve_menu_e_recebe_403_na_tela FAILED [100%]

>       self.assertGreater(qtd_plano_1, 0)
E       AssertionError: 0 not greater than 0
>       self.assertTrue(res.get("sem_lancamentos"))
E       AssertionError: None is not true
>       self.assertEqual(r_vend.status_code, 403)
E       AssertionError: 200 != 403
>       from financeiro.seeds import aplicar_seed_tenants_plano_vazio
E       ImportError: cannot import name 'aplicar_seed_tenants_plano_vazio' from 'financeiro.seeds' (C:\Temp\baros_u02_antes\financeiro\seeds.py)
>       self.assertNotIn(b"/financeiro/", resp_home.content)
E       AssertionError: b'/financeiro/' unexpectedly found in ...
======================== 5 failed in 74.98s (0:01:14) =========================
```

---

## 4. Resultado da suíte e checks (Seção 9)

- **Suíte de partida (`sprint-u02/financeiro-primeiros-passos`):** `788 passed, 4 warnings in 194.91s`
- **Testes C01 (`produtos/tests/test_c01_correcoes.py`):** na execução inicial pré-correção falharam 6 de 7 testes (`test_02` a `test_07`; `test_01` passou durante a escrita concorrente da view); após a correção, `7 passed` (`15 passed` junto com `test_sprint03_produtos_retestes_baixa.py`).
- **`venv/Scripts/python.exe manage.py check`:** `System check identified no issues (0 silenced).`
- **`venv/Scripts/python.exe manage.py makemigrations --check --dry-run`:** `No changes detected`
- **`venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`:** `795 passed, 4 warnings in 196.84s`
- **`tests/test_integridade_js.py` + `tests/test_u01_interface_layout.py`:** `6 passed` (`Node.js v24.11.1` disponível)
- **Contagens estáticas nos arquivos tocados:** `style="` = 0 novos (apenas os 11 pré-existentes em `base_dashboard.html`); `alert(`/`confirm(`/`prompt(` = 0 novos; `innerHTML` = 0 novos.

---

## 5. Checklists da Sprint

### Testes
- [x] PATCH, PUT e DELETE em `/produtos/api/patrimonio/baixas/{id}/` como ADMIN → `405`, baixa e `status_anterior` preservados (`test_01`).
- [x] PATCH, PUT e DELETE em `/produtos/api/patrimonio/envios-reteste/{id}/` → `405` e `ItemEnvioReteste` preservados (`test_02`).
- [x] POST em `envios-reteste` como MOTORISTA e VENDEDOR → `403`; como OPERADOR_PATIO e RESPONSAVEL_TECNICO → `201` (`test_02`).
- [x] `retificar` sem motivo ou com motivo < 10 caracteres → `400` com erro no campo `motivo` (`test_03`).
- [x] `retificar` como VENDEDOR, OPERADOR_PATIO e MOTORISTA → `403`; como RESPONSAVEL_TECNICO → `201` (`test_03`).
- [x] `retificar` em reteste de outra empresa → `404` (`test_03`).
- [x] Teste estático confirma que `retestes.js` e `cilindros_drawer.js` não contêm `toISOString().slice(0, 10)` (`test_04`).
- [x] Teste estático confirma que `retestes.js` checa `podeEditarPatrimonio` antes de chamar `abrirModalBaixa` no fluxo de condenado (`test_04`).
- [x] Teste estático confirma que a migração `0012` não importa `financeiro.seeds` (`test_05`).
- [x] Comando `seed_financeiro_plano_vazio` aplica apenas em empresa com módulo ativo e plano vazio, é idempotente e `--dry-run` não grava (`test_06`).
- [x] Com seed mockado levantando exceção, ligar módulo pelo backoffice devolve `aviso_seed` ao administrador (`test_07`).
- [x] Saída do item 8 do escopo colada neste relatório (Seção 3).
- [x] `tests/test_integridade_js.py` e `tests/test_u01_interface_layout.py` verdes.

### Critérios de aceite
- [x] Nenhuma baixa, envio ou reteste pode ser alterado ou apagado pela API. Mudanças só pelos fluxos `create`, `estornar` e `retificar`.
- [x] Um `migrate` num banco que já tem dados não grava o plano de contas (`0012` é `noop`).
- [ ] Navegador, console aberto, **sem erros**: `/produtos/retestes/` (condenado como GERENTE e como OPERADOR_PATIO), `/produtos/patrimonio/` (aba Baixas) e o drawer do cilindro em `/produtos/` — **pendente de verificação pelo dono** (ambiente sem navegador interativo).
- [x] Definição de pronto (seção 9), incluindo `git status` limpo e nenhuma reformatação de arquivo inteiro.

---

## 6. Notas de deploy
- A migração `financeiro/migrations/0012_seed_plano_contas_tenants_ativos.py` virou `noop` (não grava plano de contas no `migrate`).
- O comando novo `python manage.py seed_financeiro_plano_vazio` (aceita `--dry-run`) deve ser rodado **só depois** da validação do plano de contas pelo contador.
- Executar `python manage.py collectstatic --noinput` por causa da atualização de `?v=20261113_c01` em `core.js`, `baros_admin.js`, `retestes.js` e `cilindros_drawer.js`.
- No nginx da VM, `/media/` **não** pode ser servido diretamente, porque os laudos de reteste devem passar só pelo endpoint `/produtos/api/patrimonio/retestes/{id}/laudo/`, que checa permissão.

---

## C01.1

### O que foi feito
- **`core/seeds.py` (`executar_seeds`):** alterado para retornar lista de dicionários por seed (`{'modulo', 'seed', 'sucesso', 'resultado', 'erro'}`), com parâmetro `capturar_erros: bool = False`. No onboarding (`capturar_erros=False`, padrão), qualquer exceção continua sendo logada e propagada (`raise`), mantendo o comportamento existente.
- **`core/views_baros_admin.py` (`BarosAdminToggleModuloView.post`):** removido o `try/except`; agora chama `executar_seeds(tenant, modulo=modulo, capturar_erros=True)` e monta `aviso_seed` a partir dos itens com `sucesso == False`.
- **`produtos/tests/test_c01_correcoes.py` (`test_07_backoffice_toggle_modulo_mostra_erro_quando_seed_falha`):** reescrito para fazer o mock dentro de `core.seeds._seeds_por_modulo['financeiro']`, validando o retorno estruturado de `executar_seeds(..., capturar_erros=True)` e a resposta `aviso_seed` do backoffice.
- **Limpeza de working tree:** descartadas as sobras de fim de linha em `docs/PROGRESSO.md` (`git checkout -- docs/PROGRESSO.md`) e removida a linha em branco extra de `SPRINT_C01.md`.

### Saída do `test_01` no worktree anterior (`C:/Temp/baros_c01_antes`, `sprint-u02/financeiro-primeiros-passos`)
```text
>       self.assertEqual(r_patch.status_code, 405)
E       AssertionError: 200 != 405

produtos\tests\test_c01_correcoes.py:217: AssertionError
=========================== short test summary info ===========================
FAILED produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_01_baixa_patrimonial_imutavel_sem_patch_put_delete - AssertionError: 200 != 405
================= 1 failed, 6 deselected in 75.52s (0:01:15) ==================
```

### Saída do `test_07` antes e depois da C01.1
- **Antes (código da C01):**
```text
>           resultados = executar_seeds(self.tenant, modulo="financeiro", capturar_erros=True)
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           TypeError: executar_seeds() got an unexpected keyword argument 'capturar_erros'
================= 1 failed, 6 deselected in 71.40s (0:01:11) ==================
```
- **Depois (após C01.1, `venv/Scripts/python.exe -m pytest produtos/tests/test_c01_correcoes.py -v`):**
```text
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_01_baixa_patrimonial_imutavel_sem_patch_put_delete PASSED [ 14%]
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_02_envio_reteste_permissoes_d1_e_imutabilidade_patch_put_delete PASSED [ 28%]
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_03_retificar_reteste_motivo_obrigatorio_papeis_d2_e_404_outro_tenant PASSED [ 42%]
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_04_estaticos_js_data_local_e_guard_condenado PASSED [ 57%]
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_05_migracao_0012_nao_importa_financeiro_seeds PASSED [ 71%]
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_06_comando_seed_financeiro_plano_vazio PASSED [ 85%]
produtos/tests/test_c01_correcoes.py::C01CorrecoesTests::test_07_backoffice_toggle_modulo_mostra_erro_quando_seed_falha PASSED [100%]

======================== 7 passed in 70.97s (0:01:10) =========================
```

### Checks finais (C01.1)
- `venv/Scripts/python.exe manage.py check`: `System check identified no issues (0 silenced).`
- `venv/Scripts/python.exe manage.py makemigrations --check --dry-run`: `No changes detected`
- `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`: `795 passed, 4 warnings in 204.37s`
- `git status -sb`: limpo (`## correcao-c01/patrimonio-retestes-financeiro`)
