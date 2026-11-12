# Relatório da Sprint 03 — Produtos: Retestes Hidrostáticos e Baixa Patrimonial

**Data:** 12/11/2026  
**Branch:** `sprint-03/produtos-retestes-baixa`  
**Base:** `sprint-02/produtos-patrimonio`  
**Status:** Pronto para Revisão (verificação em navegador real bloqueada pelo ambiente — detalhes na Seção 7)

---

## 1. O que foi feito (por ID de tarefa)

### Tarefa 03.1 — Página "Retestes" (`/produtos/retestes/`)
- **View, Rota e Navegação:**
  - Adicionada `RetestesTemplateView` em [produtos/views.py](file:///c:/Lucas/GasManagementApp/produtos/views.py) com proteção de login e `assert_modulo(tenant, 'patrimonio')` (HTTP 403 quando o módulo patrimônio estiver desativado).
  - Registrada a rota `/produtos/retestes/` em [produtos/urls.py](file:///c:/Lucas/GasManagementApp/produtos/urls.py).
  - Adicionado link "Retestes" no menu lateral em [templates/base_dashboard.html](file:///c:/Lucas/GasManagementApp/templates/base_dashboard.html) logo abaixo de "Patrimônio", dentro de `{% if modulos_ativos.patrimonio %}`.
  - Estrutura de template seguindo `{% block dashboard_content %}` e `{% block extra_js %}` (sem sobrescrever `{% block content %}`), com [produtos/templates/produtos/retestes/index.html](file:///c:/Lucas/GasManagementApp/produtos/templates/produtos/retestes/index.html) e parciais + [produtos/static/produtos/js/retestes.js](file:///c:/Lucas/GasManagementApp/produtos/static/produtos/js/retestes.js).
- **Cartões de Resumo (KPIs):**
  - Vencidos, Vencendo em 30 dias, Vencendo em 60 dias, Vencendo em 90 dias e Em requalificação agora (`em_requalificacao` adicionado em `CilindroViewSet.relatorio_vencimentos`).
- **Aba Vencimentos (`_aba_vencimentos.html`):**
  - Listagem de cilindros por data do próximo reteste, com filtros por situação, gás e modelo, e seleção múltipla para iniciar envio em lote ("Enviar para reteste").
- **Aba Envios (`_aba_envios.html`) e Novo Envio em Etapas (`_modal_novo_envio.html`):**
  - Tabela de `EnvioReteste` exibindo requalificadora, data de envio, quantidade de cilindros e pendentes de retorno (`pendentes_retorno`).
  - Stepper em 3 etapas: (1) Requalificadora (nome, CNPJ, documento de envio — campo `documento_envio` adicionado ao modelo `EnvioReteste`), (2) Bipagem de Cilindros por código de barras/serial (aceita apenas cilindros em `VAZIO_TRIAGEM` e sem `bloqueio_sanitario`), (3) Revisão antes do envio em lote (`enviar_cilindros_para_reteste`).
- **Retorno Completo por Cilindro (`_modal_retorno_reteste.html`):**
  - Formulário com data do teste, pressão de teste, expansão total e permanente com cálculo ao vivo do percentual (`(permanente / total) * 100`) e verificação frente ao limite normativo de 10% (ABNT NBR 12274, decisão 8B.1), tara aferida com variação percentual ao vivo e alerta acima de 5% (decisão 8B.3), upload de laudo em PDF (`laudo_pdf` adicionado ao modelo `HistoricoRetesteHidrostatico` + endpoint `GET /produtos/api/patrimonio/retestes/{id}/laudo/`) e resultado (`APROVADO` ou `REPROVADO_CONDENADO`).
  - Para cilindro condenado (`REPROVADO_CONDENADO`), quando o backend já tiver criado a baixa automática (`INUTILIZACAO_TECNICA`), informa ao usuário; caso não esteja baixado, oferece abrir o modal de baixa patrimonial pré-preenchido com `INUTILIZACAO_TECNICA`.
- **Retificação de Reteste (`_modal_retificacao.html`):**
  - Modal com motivo obrigatório acionando `POST /produtos/api/patrimonio/retestes/{id}/retificar/` (mapeando `motivo` para `observacoes` no `HistoricoRetesteHidrostaticoViewSet.retificar`).

### Tarefa 03.2 — Baixa Patrimonial
- **Backend e Permissões:**
  - `BaixaPatrimonialViewSet` protegido por `[SomenteGestaoAltera, RequiresModulePatrimonio]`, validando pertença do `cilindro_id` ao tenant (404 se fora do tenant) e motivo com pelo menos 10 caracteres (400).
  - `estornar_baixa` em [produtos/services/baixa.py](file:///c:/Lucas/GasManagementApp/produtos/services/baixa.py) atualizado para autorizar também `Membership` ativa com papel `ADMIN` ou `GERENTE`, preservando `is_superuser` e permissão `produtos.estornar_baixa`.
- **Modal de Baixa Patrimonial (`_modal_baixa_patrimonial.html`):**
  - Compartilhado entre a página de Retestes e o drawer de cilindros, com tipo (`INUTILIZACAO_TECNICA`, `EXTRAVIO`, `VENDA`, `SINISTRO`), data, motivo mínimo de 10 caracteres, documento conforme o tipo (laudo, BO ou NF de venda) e dupla confirmação com `Baros.confirmar({perigo: true})`.
- **Aba Baixas na página de Patrimônio (`_aba_baixas.html`, [patrimonio/index.html](file:///c:/Lucas/GasManagementApp/produtos/templates/produtos/patrimonio/index.html), [patrimonio.js](file:///c:/Lucas/GasManagementApp/produtos/static/produtos/js/patrimonio.js)):**
  - Listagem de baixas patrimoniais com motivo, tipo, valor contábil baixado, status de estorno e botão de estorno (com motivo obrigatório) restrito a `ADMIN`/`GERENTE`.
- **Estado Terminal `BAIXADO` no Drawer (`_drawer_cilindro.html`, [cilindros_drawer.js](file:///c:/Lucas/GasManagementApp/produtos/static/produtos/js/cilindros_drawer.js)):**
  - Cilindros com status `BAIXADO` exibem apenas a ação de estorno da baixa ativa (para gestão), ocultando as demais ações operacionais.

### Tarefa 03.3 — Ajuste do Drawer do Cilindro
- Em [cilindros_drawer.js](file:///c:/Lucas/GasManagementApp/produtos/static/produtos/js/cilindros_drawer.js) e [produtos/templates/produtos/index.html](file:///c:/Lucas/GasManagementApp/produtos/templates/produtos/index.html):
  - `CilindroSerializer` expõe `envio_reteste_aberto` e `baixa_ativa_id`.
  - O botão "Registrar retorno de reteste" no drawer abre o modal completo (`registrar-retorno-reteste-completo` com expansão, tara e laudo PDF) quando o cilindro está vinculado a um `EnvioReteste` aberto, mantendo o retorno simples (`retorno-reteste`) nos demais casos.

---

## 2. Bugs encontrados e corrigidos no caminho

1. **Sintaxe de template em `templates/base_dashboard.html`:**
   - *Sintoma:* `TemplateSyntaxError` por falta de espaços em `current_tenant.id==t.id` na linha 108 ao renderizar páginas do dashboard nos testes.
   - *Correção:* Ajustado pontualmente para `{% if current_tenant.id == t.id %}` na linha 108 sem reformatar o restante do arquivo.
2. **Estorno de baixa restrito apenas a superuser/permissão explícita:**
   - *Sintoma:* Gestores (`ADMIN` / `GERENTE`) via `Membership` recebiam erro de permissão ao tentar estornar baixa na API.
   - *Correção:* `estornar_baixa` em `produtos/services/baixa.py` passou a aceitar também `Membership(user=usuario, tenant=baixa.tenant, papel__in=['ADMIN', 'GERENTE'], ativo=True)`.
3. **Filtro e contagem de cilindros em requalificação em `relatorio_vencimentos`:**
   - *Sintoma:* O endpoint de vencimentos não retornava a contagem nem filtrava por `em_requalificacao`.
   - *Correção:* Adicionado o contador `em_requalificacao` e os filtros por `gas` e `modelo` em `CilindroViewSet.relatorio_vencimentos`.

---

## 3. O que ficou de fora e por quê

- **Verificação interativa em navegador real com console aberto:**
  - *Motivo:* O ambiente local não possuía o Chrome com depuração remota ativa (`DevToolsActivePort` ausente) e o `venv` não possui `playwright` nem `selenium` instalados para abertura headless automatizada. A sintaxe JS (`node --check`), a renderização HTTP dos templates Django e as checagens estáticas de layout/Design System foram validadas, ficando a abertura manual no navegador registrada para conferência no checklist da Seção 7.

---

## 4. Decisões e premissas tomadas

- **Baixa automática ao condenar cilindro no reteste (Decisão 8B):**
  - O serviço `registrar_retorno_reteste` da Sprint 8B já cria `BaixaPatrimonial(tipo='INUTILIZACAO_TECNICA')` automaticamente quando `resultado='REPROVADO_CONDENADO'`. Esse comportamento foi mantido intacto no backend; no frontend, `retestes.js` detecta se o cilindro já ficou `BAIXADO` e informa o usuário, oferecendo o modal de baixa pré-preenchido apenas quando ainda não houver baixa registrada.
- **Migração de banco de dados:**
  - Criada [produtos/migrations/0024_add_documento_envio_e_laudo_pdf_reteste.py](file:///c:/Lucas/GasManagementApp/produtos/migrations/0024_add_documento_envio_e_laudo_pdf_reteste.py) adicionando `documento_envio` em `EnvioReteste` e `laudo_pdf` em `HistoricoRetesteHidrostatico`.

---

## 5. Resultado dos Testes e Checagens

- **Suíte TDD da Sprint 03** (`venv/Scripts/python.exe -m pytest produtos/tests/test_sprint03_produtos_retestes_baixa.py -q`):
  - Antes da implementação: 6 testes falharam (TDD vermelho) e 1 (`test_retorno_reprovado_por_expansao`) já passava pelo backend da Sprint 8B.
  - Após a implementação: **8 passed** (inclui teste estático varrendo todos os templates que estendem `base_dashboard.html` para garantir que nenhum sobrescreve `{% block content %}`, além de ausência de `style="`, `alert/confirm/prompt` e `innerHTML` inseguro nos novos arquivos).
- **Suíte completa após última edição** (`venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`):
  - **776 passed, 4 warnings in 160.84s (0:02:40)** (baseline no início da Sprint 03: **768 passed, 4 warnings**; +8 novos testes, zero regressões).
- **Django System Check** (`venv/Scripts/python.exe manage.py check`):
  - `System check identified no issues (0 silenced).`
- **Django Migrations Check** (`venv/Scripts/python.exe manage.py makemigrations --check --dry-run`):
  - `No changes detected`
- **Checagem de sintaxe JavaScript (`node --check`):**
  - `produtos/static/produtos/js/retestes.js`, `produtos/static/produtos/js/patrimonio.js` e `produtos/static/produtos/js/cilindros_drawer.js`: exit code `0`.

---

## 6. Lista de Commits na Branch

- `1279ca8` — `feat(produtos): regras e APIs de retestes, laudo PDF e baixa patrimonial`
- `2cf6fd1` — `feat(produtos): central de retestes, aba baixas e ajustes no drawer`
- `a68a6bd` — `test(produtos): suite de testes TDD e checagem estatica da sprint 03`
- *(commit de documentação seguinte)* — `docs(sprint-03): relatorio de entrega e atualizacao de progresso`

---

## 7. Checklist de Definição de Pronto (Seção 9 de `00_REGRAS_GERAIS.md`)

- [x] Todos os testes existentes + testes novos da sprint passando (`776 passed`).
- [x] `python manage.py check` e `python manage.py makemigrations --check --dry-run` limpos.
- [x] Nenhuma alteração fora do escopo quebrou outros módulos.
- [x] Sem `style=""` inline, `alert()`, `confirm()` ou `prompt()` nos novos templates e scripts.
- [x] Nenhum template que estende `base_dashboard.html` sobrescreve `{% block content %}` (validado por teste estático).
- [x] Sintaxe JS validada via `node --check`.
- [ ] **Verificação no navegador com console aberto:** **Bloqueado no ambiente do agente** (Chrome sem `DevToolsActivePort` ativo e ausência de `playwright`/`selenium` no `venv`). Recomenda-se abrir `/produtos/retestes/`, `/produtos/patrimonio/` (aba Baixas) e `/produtos/` (drawer do cilindro) no navegador local com DevTools (F12 → Console) após rodar `migrate`.

---

## 8. Notas de Deploy

- **Migrações:** Executar `python manage.py migrate` (aplica `produtos.0024_add_documento_envio_e_laudo_pdf_reteste`).
- **Arquivos estáticos:** Executar `python manage.py collectstatic --noinput` (inclui `produtos/js/retestes.js` e atualizações em `patrimonio.js` e `cilindros_drawer.js`).
- **Armazenamento de mídia:** O campo `laudo_pdf` de `HistoricoRetesteHidrostatico` utiliza `FileField`; garantir que `MEDIA_ROOT` esteja gravável e servido adequadamente em produção.
- **Variáveis de ambiente / dependências:** Nenhuma nova variável ou dependência externa necessária.
