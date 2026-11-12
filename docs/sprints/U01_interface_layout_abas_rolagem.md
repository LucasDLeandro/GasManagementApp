# Sprint U01 — Interface: rolagem horizontal, largura das páginas, abas e barras de rolagem

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md`, `docs/sprints/00_REGRAS_GERAIS.md` (inteiro) e `docs/DESIGN_SYSTEM.md`. Depende da H01.
**Branch:** `sprint-u01/interface-layout` a partir de `fase-2/produtos` (com a H01 mergeada).

## Objetivo
Todas as telas principais têm a mesma largura, os mesmos espaçamentos, a mesma barra de abas e barras de rolagem discretas, sem rolagem horizontal da página e sem rótulos internos de desenvolvimento.

## O que está errado (verificado em 12/11/2026, pelas telas do servidor de teste e pelo código)
1. **A página inteira rola na horizontal** em Vendas, Logística, Clientes e na tela inicial: o menu lateral aparece cortado à esquerda e há barra de rolagem no rodapé (Clientes). Algum elemento é mais largo que a área útil. Para achar o culpado em cada tela, rode no console:
   `[...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)`
2. **Larguras diferentes entre telas:** Integrações limita a 1300px (`core/static/core/css/integracoes.css`, linha 7), Perfil Regulatório e Financeiro ficam estreitos e centralizados, as demais ocupam 100%.
3. **Cinco estilos de barra de abas:** Financeiro (abas que estouram a largura com a barra de rolagem nativa e setas, em `templates/financeiro/dashboard.html`), Logística (abas com emoji dentro de uma caixa, `logistica/templates/logistica/index.html`), Clientes e Vendas (pílulas dentro de uma caixa), Integrações (sublinhado com ícone), Produtos e Patrimônio (`tabs-nav`).
4. **Barras de rolagem nativas, grossas e claras** no tema escuro; nenhuma regra global de `scrollbar-*` no projeto.
5. **Rótulos de desenvolvimento visíveis ao usuário:** "(Sprint 9A)" no título do Financeiro, "(D7)" e "(D9)" nas abas de Integrações, "(D8)" na Logística, entre outros (22 ocorrências em templates).
6. **Botão "+ + Nova Venda"** em Vendas: ícone de "+" e o texto também começa com "+" (`vendas/templates/vendas/index.html`, linha 22).
7. **Espaçamentos diferentes** no cabeçalho das páginas e entre cartões de uma tela para outra.

## Escopo
- **Container de página único** no Design System (`core/static/core/css/components.css`): `.ds-page` com uma largura máxima única (defina e registre o valor) e padding lateral pelos tokens `--space-*`; todas as telas abaixo usam o mesmo. Remova os `max-width` próprios das telas.
- **Sem rolagem horizontal da página:** corrija a causa em cada tela (tabela larga dentro de um contêiner com `overflow-x: auto` próprio, grid com `minmax(0, 1fr)`, `min-width: 0` em filhos flex etc.). Tabelas largas rolam dentro do próprio cartão, nunca a página.
- **Um componente de abas** (`tabs-nav` no `components.css`): sublinhado na aba ativa, rolagem horizontal própria quando não couber (sem setas nativas, com barra fina), sem emoji, foco visível por teclado, `role="tablist"`/`role="tab"`/`aria-selected`. Aplique em todas as telas listadas, mantendo os ids e `data-*` que os scripts usam.
- **Barras de rolagem globais** em `components.css`: `scrollbar-width: thin`, `scrollbar-color` com tokens e `::-webkit-scrollbar*`, nos temas claro, escuro e alto contraste.
- **Textos:** retire dos textos visíveis "(Sprint …)", "(D7)", "(D8)", "(D9)" e semelhantes (podem ficar em comentários do template); corrija o "+ + Nova Venda".
- **Espaçamento:** cabeçalho de página com `ds-page-header` e distâncias por tokens em todas as telas listadas.
- **Telas:** Início, Comercial & Estadia (Clientes), Vendas, Logística, Ativos 360°, Patrimônio, Recall, Integrações, Perfil Regulatório, Pessoal, Financeiro, Fiscal.
- **Altere só o necessário** em cada arquivo (seção 4.13 das regras): nada de reformatar arquivos inteiros.

## Testes
- [ ] **Falha antes:** teste estático que procura `(Sprint`, `(D7)`, `(D8)`, `(D9)` em texto visível dos templates (fora de comentários `{# #}` e `<!-- -->`).
- [ ] Teste estático: as telas listadas usam `tabs-nav` e não usam emoji nas abas.
- [ ] Teste estático: nenhum `max-width` de página fora do `.ds-page` nos CSS das telas listadas.
- [ ] Suíte e verificação de JavaScript da H01 continuam verdes.

## Critérios de aceite
- [ ] Para cada tela listada, no navegador a 1366px e a 375px: `document.documentElement.scrollWidth <= document.documentElement.clientWidth` (registre o resultado tela a tela no relatório), console sem erros, abas iguais, rolagem discreta nos três temas.
- [ ] Definição de pronto (seção 9).

## Fora do escopo
Redesign do conteúdo das telas (Sprints 06, 07, 08, 09 e seguintes). Aqui é só a casca comum.
