# Design System do Baros (v1)

Regras de interface para **todas** as telas do app da distribuidora. A referência visual é a tela de **Clientes** (`/clientes/`), a primeira redesenhada. Toda tela nova ou migrada segue este documento. Uma tela só conta como "redesenhada" quando cumpre a [checklist](#9-checklist-de-tela-redesenhada) do fim.

> Escopo: app da distribuidora (`base_dashboard.html`). O **App de Campo** (PWA) e o **Portal B2B** têm adaptações próprias (Fase 8 do plano); o **backoffice** (`/baros-admin/`) segue o mesmo vocabulário com a paleta escura própria.

---

## 1. Arquivos

| O quê | Onde |
|---|---|
| Tokens (cores, fontes, temas) | `core/static/core/css/home.css` (`:root`, `[data-theme="dark"]`, `[data-theme="high-contrast-sun"]`) |
| Componentes compartilhados | `core/static/core/css/components.css` (seção **Design System v1**) |
| Utilitários JS (`Baros.*`) | `core/static/core/js/core.js` |
| Parciais de template | `templates/components/` (`_metric_card`, `_empty_state`, `_stepper`; filtro `dividir` em `core/templatetags/baros_ui.py`) |
| CSS/JS de cada módulo | `<app>/static/<app>/css/index.css` e `<app>/static/<app>/js/index.js` |

**Regras:**
- **Nada de estilo inline novo** (`style="..."`). Se faltar uma classe, ela é criada no CSS do módulo ou, se for reutilizável, em `components.css`.
- **Nada de cor fixa** (`#fff`, `#0284c7`...) em CSS de módulo. Use sempre os tokens (`var(--color-...)`, `var(--status-...)`). Cores fixas quebram o tema escuro e o de alto contraste.
- **Nada de `alert()`, `confirm()` ou `prompt()`.** Use `Baros.confirmar()`, `Baros.sucesso()`, `Baros.erro()` (seção 6).
- **Nada de CDN.** Bibliotecas ficam em `static/vendor/` (decisão D5 da Sprint 6).

---

## 2. Tokens

### Cores de interface
| Token | Uso |
|---|---|
| `--color-primary` / `--color-primary-dark` | Ação principal, links, item ativo |
| `--color-bg` | Fundo da página |
| `--color-surface` | Cartões, modais, tabelas |
| `--color-hover` | Fundo de seção, cabeçalho de tabela, hover |
| `--color-border` | Bordas e divisores |
| `--color-text` / `--color-text-muted` | Texto principal / secundário |
| `--color-success` / `--color-warning` / `--color-danger` | Feedback |

### Cores de status (badges e linhas de estado)
Cada família tem `-bg`, `-border` e `-text`:

| Família | Significado no Baros |
|---|---|
| `--status-approved` | Concluído, pago, liberado, cheio disponível |
| `--status-transit` | Em andamento, em rota, em envase |
| `--status-warning` | Pendente, vencendo, aguardando aprovação |
| `--status-danger` | Bloqueado, vencido, rejeitado, cancelado |
| `--status-quarantine` | Quarentena sanitária, recall, em análise de RT |

### Tipografia
- Texto: `--font-family` (Inter, self-hosted).
- Números, códigos, placas, séries, CNPJ, chaves de NF-e: `--font-family-mono` (JetBrains Mono) com a classe `.font-mono`.
- Tamanhos: título da página 1.5rem/700 · título de seção 0.82rem/700 caixa alta · rótulo 0.85rem/600 · texto 0.9rem · auxiliar 0.75rem.

### Espaçamento e forma
- Escala: 4 · 8 · 12 · 16 · 20 · 24 · 32 px.
- Raio: 6px (campos, botões pequenos) · 8px (botões, seções) · 12px (stepper, abas) · 16px (cartões de métrica, modais).

---

## 3. Estrutura de uma página

```
┌ Cabeçalho da página ─────────────────────────────── [Ação secundária] [Ação principal] ┐
│ Título + subtítulo curto                                                                 │
├ Métricas (3 a 5 cartões) ───────────────────────────────────────────────────────────────┤
├ Abas (quando a página tem mais de uma visão) ───────────────────────────────────────────┤
│ Filtros + busca                                                                          │
│ Tabela (ou kanban / lista) com estados: carregando · vazio · erro                        │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- Cabeçalho (marcação direta, porque as ações variam por página):
  ```html
  <header class="ds-page-header">
      <div><h1 class="ds-page-title">Clientes</h1><p class="ds-page-subtitle">Cadastro, contratos e estadia</p></div>
      <div class="ds-page-actions"><button class="btn-secondary">Exportar</button><button class="btn-primary">Novo cliente</button></div>
  </header>
  ```
- Uma única **ação principal** por página (`.btn-primary`). As outras são `.btn-secondary` ou `.btn-outline`.
- Página com mais de ~6 abas ou mais de ~800 linhas de template **vira páginas separadas com submenu** (é o caso de Logística e Financeiro).

---

## 4. Componentes

### 4.1 Cartão de métrica
```html
{% include "components/_metric_card.html" with rotulo="Cilindros em comodato" valor=total_comodato tom="transit" %}
```
`tom`: `approved`, `transit`, `warning`, `danger`, `quarantine` ou vazio. Valor numérico sempre formatado (moeda `R$ 1.234,56`, milhar com ponto).

### 4.2 Abas
`.tabs-nav` > `button.tab-btn[data-tab="x"]` e `.tab-pane#tab-x`. A aba ativa fica na URL (`?aba=x`), para o link poder ser compartilhado e o F5 não perder a posição.

### 4.3 Tabela
- `.table-container` > `table`. Cabeçalho em caixa alta, 0.75rem.
- Colunas numéricas alinhadas à direita, em `.font-mono`.
- Status sempre como **badge** (`.badge.badge-status-{approved|transit|warning|danger|quarantine}`), nunca como texto colorido solto.
- Ações da linha à direita: no máximo 2 botões visíveis; o resto num menu "⋯".
- Paginação e busca **no servidor** (DRF), nunca carregar tudo no navegador.

### 4.4 Estados
Toda área que carrega dados tem três estados:
- **Carregando:** `.ds-skeleton` (linhas cinza animadas), não um "Carregando..." solto.
- **Vazio:** `{% include "components/_empty_state.html" with titulo="Nenhum cilindro encontrado" texto="Ajuste os filtros ou cadastre o primeiro." %}`, com a ação principal quando fizer sentido.
- **Erro:** a mesma caixa de vazio com `tom="danger"` e o botão "Tentar de novo".

### 4.5 Drawer (painel lateral)
Para **ver detalhes** sem sair da lista (ex.: Cilindro 360°). Abre pela direita, largura de 480px no desktop e tela cheia no celular, fechando com Esc. Cadastros e edições **não** usam drawer: usam o modal com stepper.

---

## 5. Formulários

### 5.1 Quando usar o stepper
| Situação | Formato |
|---|---|
| Cadastro com mais de ~8 campos ou com blocos de assuntos diferentes | **Modal com stepper** (etapas) |
| Edição rápida (até ~6 campos) | Modal simples com seções |
| Ação com confirmação e motivo (bloqueio, estorno, cancelamento) | `Baros.confirmar({ motivo: true })` |
| Operação de pátio (rampa, bipagem) | Tela "estação" em página cheia, botões grandes |

### 5.2 Anatomia do stepper
```html
{% include "components/_stepper.html" with id="novo-cliente" etapas="Identificação|Contato|Endereço|Revisão" %}
<div class="ds-step-pane" data-step="1"> ... </div>
<div class="ds-step-pane" data-step="2"> ... </div>
...
```
```js
const stepper = Baros.Stepper('#novo-cliente', {
  validar: (etapa) => Baros.validarCampos(`.ds-step-pane[data-step="${etapa}"]`),
});
stepper.proxima(); stepper.anterior(); stepper.ir(3);
```
- A última etapa é sempre **Revisão**: um resumo do que vai ser gravado, só leitura, com "Voltar" e "Confirmar".
- Só avança se os campos da etapa estiverem válidos.
- Rodapé fixo: `Cancelar` à esquerda; `Voltar` e `Próximo`/`Confirmar` à direita.

### 5.3 Seções dentro de uma etapa
`.modal-section-card` > `h4.modal-section-title` com um ícone e um título curto. No máximo 3 seções por etapa.

### 5.4 Campos
- `.form-grid` (2 colunas no desktop, 1 no celular) > `.form-group` (`label` + campo + ajuda/erro).
- Todo campo tem `label` com `for`. Obrigatório leva `*` no rótulo e `required` no campo.
- **Máscaras automáticas** (já em `core.js`): campos cujo `name`/`id` contenham `cnpj`, `cpf`, `tel`, `cep`, `placa` (ou classe `mask-*`).
- Erro de validação: borda `--color-danger` + mensagem abaixo do campo (`.ds-field-error`). Nunca só um alerta genérico no topo.
- Erros vindos da API (DRF `{campo: [mensagem]}`) são distribuídos nos campos com `Baros.mostrarErrosApi(form, erro)`.
- Dinheiro: entrada com vírgula, envio como string decimal (`"1234.56"`), **nunca float**.
- Datas: `input type="date"`; exibição `dd/mm/aaaa`.

### 5.5 Botões
| Classe | Uso |
|---|---|
| `.btn-primary` | Ação principal (1 por tela ou modal) |
| `.btn-secondary` | Ações secundárias |
| `.btn-outline` | Ações de linha de tabela, filtros |
| `.btn-danger` | Ação destrutiva, **sempre** depois de `Baros.confirmar()` |
| `.btn-sm` | Tamanho reduzido em tabelas |

Durante uma requisição, o botão fica desabilitado e com o texto de progresso (`Baros.carregando(botao, 'Salvando...')`).

---

## 6. JavaScript compartilhado (`window.Baros`)

| Função | O que faz |
|---|---|
| `Baros.api(url, { method, body })` | `fetch` com JWT, CSRF e `X-Tenant-ID`. Devolve o JSON. Em erro lança `Baros.ApiError` com `status`, `mensagem` (texto amigável) e `campos` (erros por campo) |
| `Baros.confirmar({ titulo, texto, botao, perigo, motivo })` | Diálogo de confirmação. Com `motivo: true` (ou um número mínimo de caracteres), exige justificativa e devolve o texto; devolve `null` se cancelado |
| `Baros.sucesso(texto)` / `Baros.erro(texto)` / `Baros.aviso(texto)` | Feedback curto (toast) |
| `Baros.carregando(botao, texto)` | Desabilita o botão e devolve a função que o restaura |
| `Baros.Stepper(seletor, { validar, aoMudar })` | Controla o stepper da seção 5.2 |
| `Baros.validarCampos(seletor)` | Valida os campos `required`/`pattern` de um trecho e mostra os erros |
| `Baros.mostrarErrosApi(form, erro)` | Distribui os erros de campo da API no formulário |
| `Baros.moeda(v)` / `Baros.data(v)` | Formatação pt-BR |

Exemplo completo:
```js
async function salvarCliente(form) {
  const restaurar = Baros.carregando(form.querySelector('[type=submit]'), 'Salvando...');
  try {
    await Baros.api('/clientes/api/clientes/', { method: 'POST', body: Baros.dadosDoForm(form) });
    Baros.sucesso('Cliente cadastrado.');
  } catch (e) {
    Baros.mostrarErrosApi(form, e);
  } finally {
    restaurar();
  }
}
```

---

## 7. Temas e acessibilidade

- Testar toda tela nos três temas: **claro**, **escuro** e **alto contraste solar** (uso no pátio, sob sol).
- Contraste mínimo AA (4.5:1 para texto).
- Navegação por teclado: Tab percorre os campos na ordem visual; Esc fecha modal/drawer; Enter avança o stepper.
- Ícones decorativos com `aria-hidden="true"`; botões só com ícone têm `aria-label`.
- Cor nunca é o único sinal: um status tem cor **e** texto.

## 8. Responsivo

- Breakpoints: ≤ 640px (celular) · ≤ 1024px (tablet) · desktop.
- No celular: `.form-grid` com 1 coluna, modais em tela cheia, tabelas com rolagem horizontal dentro do `.table-container` (nunca da página) ou viram cartões.
- Alvos de toque com pelo menos 40×40px.

---

## 9. Checklist de tela redesenhada

- [ ] Cabeçalho, métricas, abas e tabela seguindo as seções 3 e 4
- [ ] Cadastros com stepper e etapa de Revisão; edições em modal com seções
- [ ] Zero `style="..."` novos e zero cores fixas no CSS do módulo
- [ ] Zero `alert()`/`confirm()`/`prompt()`; usa `Baros.*`
- [ ] Chamadas pela `Baros.api()`; erros de campo mostrados nos campos
- [ ] Estados de carregando, vazio e erro
- [ ] Funciona nos temas claro, escuro e alto contraste
- [ ] Funciona com 375px de largura
- [ ] Ações visíveis só para quem tem papel para executá-las, **e o backend também bloqueia**
- [ ] Template com menos de ~800 linhas (senão, dividir em parciais ou páginas)
