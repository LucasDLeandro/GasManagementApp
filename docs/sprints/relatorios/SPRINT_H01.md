# Relatório da Sprint H01 — Hotfix: tela inicial com JavaScript corrompido

**Data:** 12/11/2026  
**Branch:** `hotfix-h01/tela-inicial`  
**Base:** `fase-2/produtos` (`77793c5`)  
**Status:** Concluída (verificação visual em navegador real pendente — registrada na Seção 3 e Critérios de aceite)

---

## 0. Plano inicial (execução em fila)
- **Arquivos alterados:** [core/templates/core/home.html](file:///c:/Lucas/GasManagementApp/core/templates/core/home.html), [core/static/core/css/dashboard.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/dashboard.css), [templates/financeiro/dashboard.html](file:///c:/Lucas/GasManagementApp/templates/financeiro/dashboard.html), [templates/fiscal/index.html](file:///c:/Lucas/GasManagementApp/templates/fiscal/index.html), [tests/test_integridade_js.py](file:///c:/Lucas/GasManagementApp/tests/test_integridade_js.py), [core/tests/test_sprint01b_02_home_gestao.py](file:///c:/Lucas/GasManagementApp/core/tests/test_sprint01b_02_home_gestao.py).
- **Testes que falham antes:**
  - `tests/test_integridade_js.py::test_integridade_js_scripts_inline_templates` acusa `core/templates/core/home.html:575` (`SyntaxError: Unexpected identifier 'ntListener'`).
  - `tests/test_integridade_js.py::test_layout_base_dashboard_blocos` acusa `templates/financeiro/dashboard.html:1343` e `templates/fiscal/index.html:217` por `<script>` fora de `{% block extra_js %}` (nenhum template sobrescrevia `{% block content %}`).
- **Dúvida de negócio:** o cartão `Receita de Locação Acumulada` (`#kpi-receita-locacao`) repete o valor `Estadia Acumulada` (`#gestao-estadia-faturar`) exibido na Visão de Gestão para `ADMIN`/`GERENTE`, mas papéis operacionais não veem a Visão de Gestão. Opção conservadora adotada: ocultar o cartão apenas quando `is_gestao` for verdadeiro (`{% if not is_gestao %}`).

---

## 1. O que foi feito

- **Reconstrução do `<script>` de [home.html](file:///c:/Lucas/GasManagementApp/core/templates/core/home.html):**
  - Baseado na versão íntegra do commit `919e1b6`, reaplicando somente as mudanças intencionais do commit `5f6e56c` (`hidden` via `removeAttribute('hidden')` / `setAttribute('hidden', '')` no lugar de `style.display`, construção de DOM com `document.createElement` + `textContent` + `replaceChildren()`, e `|| ''` no filtro do radar).
  - Atualizado `?v=20261112_h01` em `dashboard.css`.
- **Botões de período e estados de carregamento/erro:**
  - Botões `.visao-periodo-btn` agora atualizam `active` e `aria-pressed`, desabilitam durante a requisição com classe `.is-loading` em `#secao-visao-gestao` e exibem erro no banner `#gestao-erro-banner` dentro da própria seção quando a API falha.
- **Cartões de baixo da home e coerência com Vendas:**
  - Conferidos os 8 cartões inferiores contra `/inicio/api/stats/` (`frota_total`, `alertas_reteste_inmetro`, `lotes_ativos`, `volume_envasado_mes`, `cilindros_vazios_triagem`, `cilindros_sem_giro_30_mais`, `receita_locacao_acumulada`): todos possuem fonte ativa na API.
  - O cartão `Receita de Locação Acumulada` (`#kpi-receita-locacao`) foi condicionado a `{% if not is_gestao %}` para não duplicar `Estadia Acumulada` na visão de gestão.
  - Adicionado texto de ajuda visível no cartão `Vendas & Faturamento` (`Exclui pendentes, cancelados e bloqueados por crédito`) e estilos correspondentes em [dashboard.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/dashboard.css).
  - **Regra Home × Vendas:** em `core/services/visao_gestao.py`, o faturamento da Home soma `valor_total` no período **excluindo** `Cancelada`, `Pendente` e `BLOQUEADO_FINANCEIRO`. Já em `vendas/views.py` (`dashboard_metrics`), `faturamento_total` soma `valor_total` de todas as vendas do mês (`data_venda__gte=start_of_month`), incluindo pendentes, canceladas e bloqueadas.
- **Verificação automática de JavaScript e layout ([tests/test_integridade_js.py](file:///c:/Lucas/GasManagementApp/tests/test_integridade_js.py)):**
  - Verifica todos os `.js` em `*/static/*/js/` (exceto `static/vendor/`) e todos os `<script>` inline dos templates `.html` (sanitizando tags/variáveis Django) via `node --check` (`Node.js v24.11.1` disponível no PATH). Quando `node` não estiver no PATH, faz `pytest.skip`.
  - Verifica que nenhum template que estende `base_dashboard.html` sobrescreve `{% block content %}` ou coloca `<script>` fora de `{% block extra_js %}`.
- **Teste de datas dos períodos:**
  - Adicionado `test_09_visao_gestao_periodos_datas_fixas` em [core/tests/test_sprint01b_02_home_gestao.py](file:///c:/Lucas/GasManagementApp/core/tests/test_sprint01b_02_home_gestao.py) validando `mes_anterior` (`2026-10-01` a `2026-10-31`) e `ultimos_30_dias` (`2026-10-13` a `2026-11-12`) com data fixa `2026-11-12`.

---

## 2. Bugs encontrados e corrigidos no caminho

1. **`<script>` fora de `{% block extra_js %}` em Financeiro e Fiscal:**
   - [templates/financeiro/dashboard.html](file:///c:/Lucas/GasManagementApp/templates/financeiro/dashboard.html#L1343) e [templates/fiscal/index.html](file:///c:/Lucas/GasManagementApp/templates/fiscal/index.html#L217) fechavam `{% endblock %}` depois do `<script>`. Ajustado para fechar `dashboard_content` antes e envolver o `<script>` em `{% block extra_js %}`.

---

## 3. O que ficou de fora e por quê

- **Verificação interativa em navegador real:** executada em fila automatizada sem navegador interativo acoplado; os critérios visuais em navegador (`gerente.bsb`, superusuário na Gases Goiás e Oxigênio Brasília, console aberto, temas e 375px) ficam pendentes para conferência do dono.

---

## 4. Decisões pendentes

- Confirmar com o dono se o cartão `Receita de Locação Acumulada` deve permanecer visível para papéis operacionais (`{% if not is_gestao %}`) ou ser removido para todos os papéis na Home.
- Confirmar com o dono se `vendas/views.py` (`dashboard_metrics`) deve continuar somando pendentes/bloqueados/cancelados ou ser alinhado à regra da Home em uma sprint futura.

---

## 5. Resultado dos testes e saída pré-correção

- **Suíte de partida (`fase-2/produtos`):** `776 passed, 4 warnings in 190.19s`
- **Node.js na execução:** `v24.11.1` disponível no PATH.
- **Falha antes (`venv/Scripts/python.exe -m pytest tests/test_integridade_js.py -v`):**
```text
FAILED tests/test_integridade_js.py::test_integridade_js_scripts_inline_templates - AssertionError: Erros de sintaxe JS em <script> inline:
  core/templates/core/home.html:575: ...
  documee    ntListener('DOMContentLoaded', () => {
  SyntaxError: Unexpected identifier 'ntListener'
FAILED tests/test_integridade_js.py::test_layout_base_dashboard_blocos - AssertionError: Templates estendendo base_dashboard.html com <script> fora de `block extra_js`: templates/financeiro/dashboard.html:1343, templates/fiscal/index.html:217
======================== 2 failed, 1 passed in 13.94s =========================
```
- **Suíte final (`venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`):** `780 passed, 4 warnings in 187.22s`

---

## 6. Lista de commits

- `327f5d9` — `fix(core): reconstroi script da tela inicial e corrige cartoes e periodos`
- `e65a1e0` — `fix(templates): move scripts de financeiro e fiscal para block extra_js`
- `1e8f0b9` — `test(core): adiciona verificacao de sintaxe JS, layout e periodos da gestao`

---

## 7. Notas de deploy

- Rodar `collectstatic` no servidor por conta da atualização de [core/static/core/css/dashboard.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/dashboard.css) (`?v=20261112_h01`).
- Nenhuma migração nova, variável de ambiente nova ou dependência Python nova.

---

## 8. Checklists da Sprint

### Testes
- [x] **Falha antes:** `tests/test_integridade_js.py` acusa `core/templates/core/home.html` (saída colada na Seção 5).
- [x] **Falha antes:** o teste de layout não acusou nenhum template sobrescrevendo `block content`, e acusou `templates/financeiro/dashboard.html:1343` e `templates/fiscal/index.html:217` por `<script>` fora de `block extra_js` (ambos corrigidos).
- [x] `/inicio/api/gestao/?periodo=mes_anterior` e `?periodo=ultimos_30_dias` devolvem as datas certas no bloco `periodo` (teste com data fixa `2026-11-12` em `test_09_visao_gestao_periodos_datas_fixas`).

### Critérios de aceite
- [ ] Navegador, console aberto, **sem erros**: tela inicial com `gerente.bsb` e com o superusuário (Gases Goiás e Oxigênio Brasília); cada botão de período muda os números; nenhum cartão com "—" *(pendente de conferência visual em navegador pelo dono)*.
- [x] Faturamento do mês na home coerente com a aba Vendas (regra documentada na Seção 1 e visível no texto de ajuda do cartão).
- [x] Definição de pronto (seção 9):
  - `manage.py check`: `System check identified no issues (0 silenced).`
  - `manage.py makemigrations --check --dry-run`: `No changes detected`
  - `pytest -q -p no:cacheprovider`: `780 passed, 4 warnings in 187.22s` (superior aos `776` de partida)
  - `style="` em `home.html` e `dashboard.css`: `0`
  - `alert(`/`confirm(`/`prompt(` em `home.html`: `0`
  - `innerHTML` em `home.html`: `0`
  - `tests/test_integridade_js.py`: verde com `Node.js v24.11.1`
