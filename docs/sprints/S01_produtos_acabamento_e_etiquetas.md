# Sprint 01: Produtos, acabamento da tela principal e etiquetas

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 5 de `docs/GUIA_MODULOS_BAROS.md` e a "FASE 2" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.
**Branch:** crie `sprint-01/produtos-acabamento` a partir de `fase-2/produtos`.

## Objetivo
Terminar o redesign da tela `/produtos/`: aba Ativos 360°, aba Lotes/CQ, drawer do cilindro e as etiquetas de impressão. Ao final, nenhum estilo inline e nenhum `innerHTML` com dado de cadastro.

## O que já existe (não refazer)
- `produtos/templates/produtos/index.html` só inclui parciais de `produtos/templates/produtos/index/`.
- Já estão no padrão novo: `_aba_catalogo.html`, `_aba_recebimento.html`, `_aba_rampa.html`, `_modal_cadastro_cilindro.html` e os 4 modais de ação em `_modais.html` (bloqueio, reteste, reclassificação, estorno).
- JS no padrão: `catalogo.js`, `cadastro_cilindro.js` e os blocos de rampa/recebimento de `fase3_rampa_recebimento_lotes.js`.

## Tarefas

### 01.1 Aba Ativos 360° (`index/_aba_ativos.html` + `cilindros_drawer.js`, função `carregarCilindros` e render da tabela)
- Cabeçalho `ds-page-header` com título, subtítulo, busca e o botão "Cadastrar cilindro" (já existe, manter o `id="btn-novo-cilindro"`).
- Cartões de métrica no topo: total de cilindros, cheios no pátio, em clientes, vazios em triagem, com reteste vencido e bloqueados. Use os filtros já aceitos por `GET /produtos/api/cilindros/` (`status`, `reteste_vencido`, `bloqueio_sanitario`). Se faltar um contador, crie a action `GET /produtos/api/cilindros/resumo/` no `CilindroViewSet`, com contagens por status, numa consulta agregada.
- Os filtros rápidos (pílulas) passam a ser abas ou pílulas no padrão (`tabs-nav` ou `ds-filtros`), e a situação de cada cilindro vira badge `badge-status-*`.
- Tabela com estados de carregando (`ds-skeleton`), vazio e erro; paginação no servidor (já existe: manter).
- Remover todos os `style="..."` desta parcial.

### 01.2 Drawer Cilindro 360° (`index/_drawer_cilindro.html` + `cilindros_drawer.js`)
- O drawer abre pela direita (480px; tela cheia no celular) e fecha com Esc.
- Seções: identificação, situação atual (status, posse, lote atual, bloqueio), patrimônio, próximo reteste e **linha do tempo do ledger** (`/produtos/api/cilindros/{id}/timeline/`) e de retestes (`/timeline-retestes/`).
- Trocar todo `innerHTML` com dado vindo da API por `createElement` + `textContent`.
- Botões de ação (bloqueio, reteste, reclassificar, estornar, etiqueta) só aparecem para o papel que pode executar (o backend continua validando).

### 01.3 Aba Lotes e CQ (`index/_aba_lotes.html` + objeto `CentralLotesCQ` em `fase3_rampa_recebimento_lotes.js`)
- Cabeçalho, cartões (aprovados, em quarentena, reprovados), tabela de lotes com badge de qualidade e ações "Aprovar" e "Reprovar" (a reprovação já usa `Baros.confirmar` com motivo, manter).
- Remover estilos inline e `innerHTML` com dados.
- Esta aba só aparece com o módulo envase (`tem_modulo_envase`); manter.

### 01.4 Etiquetas (modal 5 e modal 6 de `index/_modais.html`, `produtos/templates/produtos/etiqueta_casco.html`, `etiqueta_colarinho.html`, `produtos/static/produtos/css/etiquetas.css`)
- Mover todos os estilos inline para `etiquetas.css`, mantendo o layout de impressão (60x40 mm e colarinho).
- Os modais de pré-visualização seguem `dialog.action-modal.ds-dialog`.
- O QR code da etiqueta hoje é um quadrado "[ QR CODE 2D ]". Gere o QR de verdade **no servidor** em SVG, com a biblioteca `qrcode` (já está no `requirements.txt`; veja `BarosAdminMfaCadastroView._render` em `core/views_baros_admin.py`). Conteúdo: a URL pública **absoluta** do passaporte do cilindro (`/v/cilindro/<codigo_qr>/`), montada com `request.build_absolute_uri()` para funcionar no domínio do servidor de teste (nunca `localhost`).
- Testar a impressão com `@media print` (sem menus, só as etiquetas).

### 01.5 Limpeza
- `grep -c 'style="'` deve dar **0** em todas as parciais de `produtos/templates/produtos/index/`, exceto larguras dinâmicas de barra de progresso.
- `alert(`, `confirm(` e `prompt(` devem dar **0** em `produtos/static/produtos/js/`.
- Atualizar o `?v=` dos estáticos alterados em `produtos/templates/produtos/index.html`.

## Critérios de aceite
- `/produtos/` funciona nos temas claro, escuro e alto contraste e com 375px de largura.
- Busca, filtros, paginação e abrir o drawer funcionam como antes.
- A etiqueta impressa contém um QR legível que aponta para o passaporte público, com o domínio de quem acessou a tela.
- Suíte completa verde.

## Testes obrigatórios
- Teste da action `resumo` (se criada): contagens corretas e isolamento entre empresas.
- Teste da view da etiqueta: resposta 200 com `<svg` e a URL do passaporte; 404 para cilindro de outra empresa.
- Ampliar `test_scripts_de_produtos_sem_alert_confirm_prompt` (em `produtos/tests/test_fase2_catalogo_cadastro_cilindro.py`) para cobrir todos os JS de `produtos/static/produtos/js/`.

## Fora do escopo
Telas de patrimônio, retestes em lote, tanques e granel (sprints 02 a 04).

## Entrega
Siga a seção 7 de `00_REGRAS_GERAIS.md`. Relatório: `docs/sprints/relatorios/SPRINT_01.md`.
