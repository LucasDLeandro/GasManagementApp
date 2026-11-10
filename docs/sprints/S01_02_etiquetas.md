# Sprint 01.02 — Etiquetas: uma impressão só, a verdadeira

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md` e `docs/sprints/00_REGRAS_GERAIS.md` (inteiro). Depende da Sprint 01.01.
Leia também: `docs/DESIGN_SYSTEM.md`.
**Branch:** `sprint-01.02/etiquetas` a partir de `sprint-01.01/ativos-drawer`.

## Objetivo
Toda etiqueta impressa pelo sistema (casco e colarinho) sai de uma página do servidor, com dados reais e QR legível que abre o passaporte público do cilindro no domínio de quem imprimiu.

## O que está errado (verificado em 10/11/2026)
1. **Duas etiquetas de casco.** A página real `/produtos/cilindros/<pk>/etiqueta-casco/` (`EtiquetaCascoView`, `produtos/views.py` ~linha 1700) já gera o QR de verdade com `request.build_absolute_uri("/v/cilindro/<codigo_qr>/")`. Mas o modal de etiqueta em `produtos/templates/produtos/index/_modais.html` (~linhas 120–145) desenha um layout falso com o quadrado `[ QR CODE 2D ]` e valores de exemplo, e o botão "Imprimir Etiqueta" chama `window.print()` da **tela inteira**.
2. **Colarinho montado no navegador.** As etiquetas de colarinho da rampa são montadas em JS (`fase3_rampa_recebimento_lotes.js`, ~linhas 383–437) com `innerHTML` contendo `empresa_nome`, `gas_nome`, `lote_codigo` e cores fixas (`#dc2626`), enquanto já existe a página `/produtos/lotes/<pk>/etiqueta-colarinho/` e a API `api/envases/etiquetas-colarinho/`.
3. **CSS espalhado.** `etiqueta_casco.html` e `etiqueta_colarinho.html` têm blocos `<style>` próprios, embora exista `produtos/static/produtos/css/etiquetas.css`. `_modais.html` tem 22 `style="`.

## Escopo
- O modal de etiqueta vira uma **pré-visualização da página real** (iframe da `etiqueta-casco` do cilindro, no padrão `dialog.action-modal.ds-dialog`) com o botão "Imprimir" que imprime **só o iframe** (`iframe.contentWindow.print()`) e um link "Abrir em nova aba". Remover o layout falso.
- Colarinho: a rampa abre a página do servidor (por lote, ou por envases selecionados — se a página não aceitar envases, crie a rota usando a mesma API) em vez de montar HTML no JS.
- QR: manter a geração no servidor; nível de correção `M`, tamanho que leia impresso em 60×40 mm (meça no relatório: módulos e mm). Conteúdo: URL absoluta do passaporte (`build_absolute_uri`).
- Mover os `<style>` das duas páginas para `etiquetas.css` (carregado com `{% static %}`), com `@media print` (só a etiqueta, sem margens do navegador, `@page` no tamanho certo).
- Zero `style="` em `_modais.html` (exceto barra de progresso); `?v=` atualizado.

## Testes
- [ ] **Falha antes:** `_modais.html` não contém `[ QR CODE 2D ]` (hoje contém).
- [ ] **Falha antes:** as páginas de etiqueta não contêm `<style>` (hoje contêm).
- [ ] `etiqueta-casco` com `HTTP_HOST='teste.exemplo'`: 200, contém o QR e `http://teste.exemplo/v/cilindro/<codigo_qr>/`; cilindro de outra empresa: 404.
- [ ] Colarinho por lote: 200 com os cilindros do lote; lote de outra empresa: 404.
- [ ] Teste estático: o trecho de etiquetas de colarinho em `fase3_rampa_recebimento_lotes.js` não usa `innerHTML` com `${`.

## Critérios de aceite
- [ ] No navegador: a pré-visualização mostra a etiqueta real; "Imprimir" abre a impressão só da etiqueta (Ctrl+P na página da etiqueta também); o QR lido pelo celular abre o passaporte (no ambiente local, confira a URL no relatório; a leitura real é feita pelo dono no servidor de teste — registre nas Notas de deploy).
- [ ] Definição de pronto (seção 9).

## Fora do escopo
Impressoras térmicas (ZPL/EPL) e impressão em lote de muitos cilindros: podem virar sprint própria.
