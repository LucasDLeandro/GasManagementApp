# Análise Geral do Sistema Baros — 27/10/2026

Raio-X do código atual, feito para servir de base ao trabalho **módulo a módulo** daqui em diante. Fontes: código-fonte, `PLANO_MELHORIAS_E_PROPOSTA_SPRINTS.md`, `Blueprint_Arquitetural_Mestre.md`, relatórios das Sprints 1–6 e `docs/DECISOES_PENDENTES.md` (decisões até a Sprint 12B).

---

## 1. Resumo executivo

1. **O backend está muito à frente das telas.** As sprints 7 a 12 entregaram modelos, serviços e APIs (financeiro, fiscal, patrimônio, logística, portal B2B, governança SaaS), mas boa parte disso **não tem nenhuma interface**. Os números: cerca de 130 endpoints REST para 36 templates.
2. **O redesign só foi aplicado de verdade em `clientes`.** Os outros módulos ainda usam o padrão antigo: formulários soltos, estilos inline, `alert()`/`confirm()` do navegador.
3. **Risco crítico: quase metade do código não está no git.** Os apps `financeiro`, `fiscal`, `portal_b2b`, `faturamento` e `analytics` estão inteiros fora do controle de versão. São cerca de 290 arquivos não rastreados, mais 38 arquivos modificados (+6.900 linhas) desde o último commit (`bee24cc`). Um problema no disco perde meses de trabalho.
4. **Falha de segurança no `/baros-admin/`:** sem dispositivo MFA cadastrado, o login aceita qualquer código, inclusive em produção.

---

## 2. Bloqueadores (resolver antes de qualquer módulo)

| # | Problema | Onde | Ação |
|---|---|---|---|
| B1 | ~290 arquivos não rastreados + 38 modificados | raiz do repo | Commit imediato, separado por app, e push para o remoto |
| B2 | Login do backoffice aceita qualquer código MFA quando o superusuário não tem TOTP | `core/views_baros_admin.py:119-127` | Sem dispositivo → forçar fluxo de cadastro do TOTP (QR code) antes do login; nunca aceitar código sem verificação |
| B3 | App `frotas` está morto: fora do `INSTALLED_APPS`, sem rota e com modelos **sem tenant** (`models.Model`) | `frotas/` | Remover. A frota real vive em `logistica` (aba Frota/Veículos) |
| B4 | `.coverage` e `db.sqlite3` na raiz | raiz | Conferir o `.gitignore` antes do commit (não versionar banco nem cobertura) |
| B5 | Venda sem máquina de estados: `alterar_status` aceita qualquer status, inclusive furar o bloqueio de crédito | `vendas/views.py:143` | Ver o plano, tarefa 0.3.2 |
| B6 | Faturada → Finalizada baixa o estoque duas vezes; o erro é engolido por `except Exception: pass` | `vendas/views.py:165-170` | Ver o plano, tarefa 0.3.3 |

---

## 3. Mapa do sistema

| Módulo | Modelos | Linhas Py | Endpoints API | Telas HTML | No menu? | Situação das telas |
|---|---:|---:|---:|---:|:---:|---|
| `core` (home, tenant, RBAC, integrações, perfil regulatório) | 15 | 12.006 | — | 3 + base | ✅ | Home sem redesign; integrações e perfil regulatório parciais |
| `accounts` (usuários, perfil, login) | 2 | 628 | poucos | 5 | ✅ (admin) | Padrão antigo |
| `clientes` | 10 | 5.062 | 4 | 1 | ✅ | **Redesenhado (referência)** |
| `vendas` | 4 | 1.114 | 2 | 1 | ✅ | Parcial: tem cards de métrica, mas o formulário de venda é antigo |
| `produtos` (cilindros, envase, lotes, recall, patrimônio, granel) | 34 | 15.209 | 22 | 5 | ✅ | Drawer de cilindros novo (não commitado); formulários antigos; patrimônio/tanques/granel **sem tela** |
| `logistica` (entregas, frota, rotas, combustível, manutenção, seguros) | 46 | 20.053 | 59 | 3 | ✅ | Tela gigante (3.594 linhas, 110 modais, 648 estilos inline); precisa ser quebrada |
| `financeiro` | 50 | 24.474 | 56 | 3 | ✅ | Dashboard com 14 abas; vários submódulos **sem tela** |
| `fiscal` | 14 | 7.320 | 12 | 1 | ✅ | Tela mínima (lista/cancelamento NF-e) |
| `faturamento` (NF-e, cobranças, webhooks) | 3 | 1.275 | 5 | 0 | ❌ | Só API (sobreposto ao `fiscal`) |
| `analytics` (funil de alertas comerciais) | 1 | 4.648 | 2 | 1 | ❌ | Tela existe, mas **não aparece no menu** |
| `portal_b2b` (cliente final) | 6 | 4.626 | 19 | 6 | — (portal próprio) | Funcional, visual próprio, sem redesign |
| Backoffice `/baros-admin/` | (em `core`) | — | 10 views | 3 | ❌ | Ver seção 5 |

---

## 4. O padrão do redesign (referência: `clientes`)

O commit `1976f60` ("redesign de cadastro e topbar") é a única implementação completa. Os elementos que definem o padrão são:

- **Cadastro em assistente por etapas** (stepper `step-item` / `step-circle` / `step-content-pane`) dentro de modal, em vez de um formulário longo
- **Seções em cartões** (`modal-section-card` + `modal-section-title`)
- **Cartões de métrica** no topo (`metrics-grid` / `metric-card`)
- **Abas** (`tabs-nav` / `tab-btn` / `tab-pane`)
- **CSS e JS próprios do módulo** (`<app>/static/<app>/css/index.css`, `js/index.js`), consumindo `core/css/components.css`
- Paginação DRF e busca no servidor
- Temas claro/escuro/alto contraste via `data-theme` (já vem de `base_dashboard.html`)

> ⚠️ A especificação do redesign **não está escrita no repositório**: o que foi discutido antes não ficou documentado aqui. Sugiro registrar o padrão em `docs/DESIGN_SYSTEM.md` antes do primeiro módulo, para que todos os próximos sigam a mesma regra.

### Situação por tela

Legenda: ✅ redesenhada · 🟡 parcial · ❌ padrão antigo · ⛔ não existe

| Tela | Status | Observações |
|---|:---:|---|
| `clientes/index.html` | ✅ | Referência |
| `vendas/index.html` | 🟡 | Métricas OK; modal de nova venda sem stepper; 92 estilos inline |
| `produtos/index.html` | 🟡 | Drawer de cilindros novo; modais de envase, reteste, reclassificação, estorno e SKU no padrão antigo; 221 estilos inline |
| `produtos/recall_anvisa.html` | ❌ | 1.211 linhas, 17 `alert/confirm` nativos |
| `logistica/index.html` | 🟡/❌ | Stepper só no cadastro de veículo; demais formulários antigos |
| `logistica/app_campo.html` (PWA) | ❌ | 246 estilos inline; tem layout mobile próprio, então o redesign deve ser adaptado |
| `financeiro/dashboard.html` | ❌ | 1.574 linhas, 25 `alert/confirm`, nenhum cartão de seção |
| `financeiro/conciliacao.html` | ❌ | 20 `alert/confirm` |
| `financeiro/fechamento_caixa_detalhe.html` | ❌ | |
| `fiscal/index.html` | ❌ | 11 `alert/confirm` |
| `core/home.html` | ❌ | 45 estilos inline |
| `core/integracoes.html` / `perfil_regulatorio.html` | 🟡 | CSS próprio já separado |
| `accounts/index.html` / `meu_perfil.html` | ❌ | |
| `analytics/funil_alertas.html` | ❌ | Fora do menu |
| `portal_b2b/*` | ❌ | Visual separado (é o portal do cliente final) |
| `baros_admin/*` | ❌ | Ver seção 5 |

---

## 5. Backoffice Baros (`/baros-admin/`)

| Função | Backend | Tela |
|---|:---:|:---:|
| Dashboard (MRR, empresas por status, inadimplência, cotas) | ✅ | ✅ |
| Lista de empresas | ✅ | ✅ (somente leitura; botão "Gerenciar" sem ação) |
| Onboarding de empresa | ✅ `BarosAdminOnboardingView` | ⛔ |
| Ligar/desligar módulos | ✅ `BarosAdminToggleModuloView` | ⛔ |
| Mudar status da assinatura | ✅ `BarosAdminTransicionarAssinaturaView` | ⛔ |
| Planos SaaS | ✅ `BarosAdminPlanosView` | ⛔ |
| Faturas SaaS e status | ✅ `BarosAdminFaturasView` / `FaturaStatusView` | ⛔ |
| Acesso de suporte (break-glass) | ✅ iniciar/encerrar | ⛔ (só o banner no app) |
| Cadastro de MFA (TOTP) | ⛔ | ⛔ |
| Link no menu para superusuário | — | ⛔ |

---

## 6. Funcionalidades com backend e sem tela

### Financeiro (Sprints 9A–11C)
Sem nenhuma interface: **régua de cobrança** (configurações, envios, consentimentos), **depreciação** e revisão de vida útil, **orçamento**, **PDD**, **lançamentos manuais** com alçada, **recorrências**, **alertas e projeção de fluxo de caixa** (cenários 90 dias), **limite de crédito, bloqueio e promessa de pagamento**, **perfis de pagamento**, **parâmetros tributários / gestão / crédito**, **DRE** (só 2 menções na tela).

### Fiscal (Sprints 11A–11B)
A tela atual cobre apenas a listagem e o cancelamento de NF-e. Sem tela: **regras tributárias**, **configuração fiscal / certificado A1**, **MDF-e**, **documentos de entrada**, **movimentos de comodato**, **apuração**, **ordens de recarga**, **inutilização** (parcial).
Há também **sobreposição com `faturamento`** (`NotaFiscal`, `ConfiguracaoFiscalTenant`): é preciso decidir qual app é a fonte da verdade.

### Produtos / Patrimônio (Sprints 8A–8C)
Sem tela: **tanques criogênicos e medições**, **entradas a granel**, **estoque de gás e de produto**, **custo por lote**, **fabricantes, classes e ativos patrimoniais**, **indenizações**, **envios para reteste**, **baixa patrimonial**.

### Logística (Sprint 12A)
A maior parte tem aba, mas faltam: **motoristas** (cadastro dedicado), **regras de incompatibilidade de carga (ANTT)**, **capacidade veículo × cilindro**, **alocação de equipe**, **tabelas de frete interno**, **otimização de paradas**.

### Outros
- `analytics` (funil de alertas comerciais): tela pronta, mas fora do menu.
- `portal_b2b`: falta no app da distribuidora a tela para **convidar e revogar usuários B2B** dos clientes (conferir em `clientes`).

---

## 7. Dívidas técnicas observadas

- **Templates monolíticos:** `logistica/index.html` (3.594 linhas), `financeiro/dashboard.html` (1.574), `recall_anvisa.html` (1.211). Devem virar parciais (`{% include %}`) por aba, cada uma com seu JS.
- **Cerca de 2.000 estilos inline** somando todos os templates.
- **77 `alert()`/`confirm()` nativos.** Já existe `sweetalert2` em `static/vendor/`: padronizar com um helper único em `core.js`.
- **Rotas duplicadas:** `analytics` e `fiscal` são incluídos duas vezes com namespaces diferentes (`config/urls.py`).
- Commits genéricos ("adicionando tudo", "atualizando o projeto"). Daqui em diante, um commit por módulo/etapa.

---

## 8. Ordem sugerida de trabalho

| Fase | Escopo | Por quê |
|---|---|---|
| **0** | Commit de todo o código atual (B1, B4), remover `frotas` (B3), corrigir as 10 falhas de teste (seção 9), escrever `docs/DESIGN_SYSTEM.md` | Proteger o trabalho, partir de suíte verde e fixar o padrão |
| **1** | **Backoffice Baros**: corrigir o MFA (B2), telas de onboarding, módulos, assinatura, planos, faturas SaaS, break-glass, link no menu | É como vocês operam o SaaS; contém a falha de segurança |
| **2** | **Produtos** (núcleo operacional): redesign dos formulários + telas de patrimônio, tanques e granel | Base de todo o resto (cilindro → envase → entrega) |
| **3** | **Vendas** | Pequeno; completa o fluxo comercial junto com `clientes` |
| **4** | **Logística**: quebrar o template, redesenhar, telas faltantes (motoristas, ANTT) | Maior tela, maior ganho de manutenção |
| **5** | **Financeiro**: quebrar o dashboard + telas faltantes (cobrança, crédito, fluxo de caixa, DRE, orçamento, PDD, depreciação) | Maior volume de backend sem tela |
| **6** | **Fiscal + Faturamento**: unificar e criar as telas | Depende de decisão sobre o gateway (`DECISOES_PENDENTES` 11A) |
| **7** | `core/home`, `accounts`, `analytics` (+ menu), `app_campo` (PWA), `portal_b2b` | Acabamento e consistência |

Para cada módulo, o roteiro é: **(a)** inventário de telas e formulários → **(b)** redesign no padrão → **(c)** telas faltantes → **(d)** testes → **(e)** commit próprio.

---

## 9. Estado dos testes

Execução completa de `pytest` em 27/10/2026: **609 passaram, 10 falharam** (2min54s).

| Teste que falhou | Causa / leitura | Módulo |
|---|---|---|
| `accounts` › `test_autoatendimento_alterar_senha` | `login()` sem `backend=` com vários backends de autenticação configurados (`accounts/views.py:260`). **Bug real**: trocar a senha quebra em produção | accounts |
| `cross_tenant` › `test_list_endpoints_never_leak...` | `/produtos/api/cilindros/` responde **500** (erro interno, não vazamento). Provável efeito das mudanças não commitadas em `produtos` | produtos |
| `cross_tenant` › `envases/1/` | Retorna 403 em vez de 404. Não vaza dados, mas revela que o registro existe em outro tenant (regra fail-closed exige 404) | produtos |
| `fase5` › ping de webhook com HMAC / `webhook_shielding` › outbox | Disparo de webhooks / outbox | core |
| `sprint6` › webhooks com HMAC e romaneio | Webhooks | logistica |
| `sprint8` › roteirização, sync GPS, rastreio público (3 testes) | Torre de controle / rastreio | logistica |
| `sprint9c` › versionamento IndexedDB (ADR-040) | PWA offline | financeiro |

Também há 7 avisos: datas sem fuso (naive datetime) em testes e paginação sem `order_by` em `logistica.Veiculo`.

**Recomendação:** corrigir as 10 falhas na Fase 0, junto com o commit, para que cada módulo comece com a suíte verde. Cada falha restante é corrigida na fase do seu módulo, no máximo.
