# Relatório da Sprint U01 — Interface: rolagem horizontal, largura das páginas, abas e barras de rolagem

**Data:** 12/11/2026  
**Branch:** `sprint-u01/interface-layout`  
**Base:** `hotfix-h01/tela-inicial` (`994b650`)  
**Status:** Concluída (verificação visual em navegador real a 1366px/375px pendente — registrada na Seção 3 e Critérios de aceite)

---

## 0. Plano inicial (execução em fila)
- **Arquivos alterados:** [components.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/components.css), [home.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/home.css), [integracoes.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/integracoes.css), [perfil_regulatorio.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/perfil_regulatorio.css), [base_dashboard.html](file:///c:/Lucas/GasManagementApp/templates/base_dashboard.html), os templates das 12 telas listadas no escopo e [tests/test_u01_interface_layout.py](file:///c:/Lucas/GasManagementApp/tests/test_u01_interface_layout.py).
- **Testes que falham antes:**
  - `test_sem_rotulos_internos_em_texto_visivel_templates` acusa 10 ocorrências em `logistica/templates/logistica/index.html`, `templates/core/integracoes.html` e `templates/financeiro/dashboard.html`.
  - `test_telas_com_abas_usam_tabs_nav_sem_emoji` acusa emojis e ausência de `.tabs-nav`/`role="tablist"`/`role="tab"` em Clientes, Vendas, Logística, Patrimônio, Integrações e Financeiro.
  - `test_telas_usam_ds_page_e_sem_max_width_de_pagina` acusa as 10 telas que ainda não usavam `.ds-page`.
- **Dúvidas / premissas:** largura máxima única de `.ds-page` definida em `1440px` (`width: 100%; max-width: 1440px; margin: 0 auto; min-width: 0;`).

---

## 1. O que foi feito

- **Largura única e fim da rolagem horizontal da página:**
  - Adicionado `min-width: 0; overflow-x: hidden;` em `.content-area` ([home.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/home.css)) para impedir que filhos flex (tabelas e grids largos) expandam a página horizontalmente.
  - Criado `.ds-page` (`max-width: 1440px`, `min-width: 0`) em [components.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/components.css) e aplicado nas 12 telas: Início, Comercial & Estadia (Clientes), Vendas, Logística, Ativos 360°, Patrimônio, Recall, Integrações, Perfil Regulatório, Pessoal, Financeiro e Fiscal.
  - Removidos os `max-width` próprios de página em [integracoes.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/integracoes.css), [perfil_regulatorio.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/perfil_regulatorio.css), [dashboard.html](file:///c:/Lucas/GasManagementApp/templates/financeiro/dashboard.html) (`.fin-container`) e [fiscal/index.html](file:///c:/Lucas/GasManagementApp/templates/fiscal/index.html).
  - Atualizado `.table-container` em [components.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/components.css) para `overflow-x: auto; max-width: 100%; min-width: 0;`.
- **Componente único de abas (`.tabs-nav` / `.tab-btn`) e barras de rolagem globais:**
  - Padronizado `.tabs-nav` em [components.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/components.css) com sublinhado na aba ativa, rolagem horizontal própria (`overflow-x: auto; flex-wrap: nowrap`), foco visível (`:focus-visible`) e sem emojis.
  - Aplicado `.tabs-nav`, `role="tablist"`, `role="tab"` e `aria-selected` nas telas com abas (Clientes, Vendas, Logística, Patrimônio, Integrações e Financeiro — mantendo `switchFinTab` e IDs/atributos usados pelos scripts).
  - Adicionadas regras globais de barra de rolagem discreta (`scrollbar-width: thin`, `scrollbar-color` com `var(--color-border)` e `::-webkit-scrollbar*`) em [components.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/components.css), compatíveis com os 3 temas.
  - Atualizado `?v=20261112_u01` em [base_dashboard.html](file:///c:/Lucas/GasManagementApp/templates/base_dashboard.html), `integracoes.css` e `perfil_regulatorio.css`.
- **Textos e cabeçalhos:**
  - Removidos os rótulos internos `(D7)`, `(D8)`, `(D9)` e `(Sprint ...)` de textos visíveis em Logística, Integrações e Financeiro.
  - Corrigido o botão `+ + Nova Venda` para `Nova Venda` (mantendo o ícone `+` SVG) em [vendas/index.html](file:///c:/Lucas/GasManagementApp/vendas/templates/vendas/index.html).
  - Padronizado o cabeçalho `.ds-page-header` nas telas atualizadas.
- **Testes estáticos ([tests/test_u01_interface_layout.py](file:///c:/Lucas/GasManagementApp/tests/test_u01_interface_layout.py)):**
  - `test_sem_rotulos_internos_em_texto_visivel_templates`
  - `test_telas_com_abas_usam_tabs_nav_sem_emoji`
  - `test_telas_usam_ds_page_e_sem_max_width_de_pagina`

---

## 2. Bugs encontrados e corrigidos no caminho

- Em `clientes/templates/clientes/index.html`, `vendas/templates/vendas/index.html`, `logistica/templates/logistica/index.html`, `templates/core/integracoes.html` e `templates/financeiro/dashboard.html`, os seletores de abas foram preservados (`onclick`, `data-target`, `.fin-tab-btn`) junto de `.tabs-nav` / `.tab-btn` para não quebrar os scripts existentes.

---

## 3. O que ficou de fora e por quê

- **Verificação interativa em navegador real (1366px e 375px, 3 temas e console aberto):** executada em fila automatizada sem navegador interativo acoplado; pendente de conferência visual pelo dono nas 12 telas.

---

## 4. Decisões pendentes

- Confirmar se a largura máxima única de `1440px` em `.ds-page` atende a preferência visual do dono em monitores ultrawide.

---

## 5. Resultado da suíte

- **Partida (`hotfix-h01/tela-inicial`):** `780 passed`
- **Final (`venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`):** `783 passed, 4 warnings in 174.91s`

---

## 6. Lista de commits

- `ff6d345` — `style(core): padroniza .ds-page, .tabs-nav, scrollbars e overflow horizontal`
- `a4932a5` — `refactor(ui): aplica .ds-page, .tabs-nav e remove rotulos internos nas 12 telas`
- `edb0f00` — `test(ui): adiciona verificacao estatica de layout, abas e rotulos internos`

---

## 7. Notas de deploy

- Rodar `collectstatic` no servidor por conta das atualizações em [components.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/components.css), [home.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/home.css), [integracoes.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/integracoes.css) e [perfil_regulatorio.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/perfil_regulatorio.css) (`?v=20261112_u01`).
- Nenhuma migração, variável de ambiente ou dependência nova.

---

## 8. Checklists da Sprint

### Testes
- [x] **Falha antes:** teste estático acusou `(Sprint`, `(D7)`, `(D8)`, `(D9)` em texto visível antes da correção.
- [x] Teste estático: as telas listadas usam `tabs-nav` e não usam emoji nas abas.
- [x] Teste estático: nenhum `max-width` de página fora do `.ds-page` nos CSS das telas listadas.
- [x] Suíte e verificação de JavaScript da H01 continuam verdes (`tests/test_integridade_js.py` com `Node.js v24.11.1`).

### Critérios de aceite
- [ ] Para cada tela listada, no navegador a 1366px e a 375px: `document.documentElement.scrollWidth <= document.documentElement.clientWidth`, console sem erros, abas iguais, rolagem discreta nos três temas *(pendente de conferência visual em navegador pelo dono)*.
- [x] Definição de pronto (seção 9):
  - `manage.py check`: `System check identified no issues (0 silenced).`
  - `manage.py makemigrations --check --dry-run`: `No changes detected`
  - `pytest -q -p no:cacheprovider`: `783 passed, 4 warnings in 174.91s`
  - `tests/test_integridade_js.py`: verde com `Node.js v24.11.1`
