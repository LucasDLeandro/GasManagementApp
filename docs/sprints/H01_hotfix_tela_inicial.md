# Sprint H01 — Hotfix: tela inicial com JavaScript corrompido

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md` e `docs/sprints/00_REGRAS_GERAIS.md` (inteiro, incluindo as seções 4.11 a 4.13, novas). Urgente: o defeito está no servidor de teste.
**Branch:** `hotfix-h01/tela-inicial` a partir de `fase-2/produtos`. Se houver outra sprint em andamento na pasta, termine o passo atual e faça commit dela antes de trocar de branch.

## Objetivo
A tela inicial volta a funcionar: a visão do negócio carrega com os números reais, os botões de período trocam os números e nenhum cartão fica com "—". E o projeto passa a ter uma verificação automática que pega JavaScript quebrado.

## O que está errado (verificado em 12/11/2026)
1. **JavaScript corrompido em `core/templates/core/home.html`.** O commit `5f6e56c` (revisão da 01B.02, "limpeza de estilos") trocou trechos de 75 linhas do `<script>` por espaços. Exemplos: `let periodo        aoAtivo = 'mes_atual';`, `async funct        carregarVisaoGestao(periodo) {`, `con                it fetch(...)`, `function ge        hHeaders() {`. A versão do commit anterior, `919e1b6`, está íntegra. Com o erro de sintaxe, o script inteiro não roda:
   - a "Visão do negócio" fica com os valores fixos do HTML (R$ 0,00), enquanto a tela de Vendas mostra R$ 495,00 no mês para a mesma empresa (Gases Goiás);
   - os botões "Mês atual", "Mês anterior" e "Últimos 30 dias" não fazem nada;
   - os cartões de baixo ("Frota total de cilindros", "Cilindros sem giro > 30d", "Receita de locação acumulada", "Alertas de reteste") mostram "—"; gráfico, radar e tabela não carregam.
2. **Nenhum teste executa JavaScript**, por isso a suíte passou. O mesmo aconteceu na Sprint 02 (tela de Patrimônio, corrigida no commit "fix(produtos): tela de patrimonio usa o bloco do layout...").

## Escopo
- **Reconstrua o `<script>` de `home.html` a partir de `919e1b6`** e reaplique **somente** as mudanças intencionais de `5f6e56c` no JS (por exemplo, `style.display` trocado por `hidden` ou classes). Use `git diff 919e1b6 5f6e56c -- core/templates/core/home.html` para separar o que foi intencional do que é corrupção. O HTML e o CSS de `5f6e56c` (zero `style="`) continuam valendo.
- **Cartões de baixo da home:** confira cada um contra o que `/inicio/api/stats/` ainda devolve depois da limpeza da 01B.5. Um número que já aparece na visão de gestão não se repete (remova o cartão); um cartão sem fonte de dados sai. Nenhum "—" fixo na tela.
- **Botões de período:** marcam o ativo, mostram carregando, recarregam a visão e mostram o erro na própria seção se a API falhar.
- **Coerência com a tela de Vendas:** com o script funcionando, compare o faturamento do mês na home com o da aba Vendas para a Gases Goiás. Se forem diferentes, explique a regra de cada um no relatório (a home exclui pendentes e bloqueados) e deixe a regra visível no texto de ajuda do número.
- **Verificação automática de JavaScript** (`tests/test_integridade_js.py`):
  - extrai todo `<script>` inline dos templates `.html` do projeto (ignorando os que têm `src=` e os blocos `{% %}`/`{{ }}`, que podem ser substituídos por um literal antes da checagem) e todos os `.js` de `*/static/*/js/` (exceto `static/vendor/`);
  - roda `node --check` em cada um quando `node` estiver no PATH (`shutil.which('node')`); sem node, o teste é pulado com uma mensagem clara (`pytest.skip`);
  - registre no relatório se o node estava disponível na sua execução.
- **Teste estático de layout:** nenhum template que faz `{% extends "base_dashboard.html" %}` sobrescreve `{% block content %}` (deve usar `dashboard_content`), e todo `<script>` de página fica em `{% block extra_js %}`.

## Testes
- [ ] **Falha antes:** `tests/test_integridade_js.py` acusa `core/templates/core/home.html` (rode no código atual e cole a saída no relatório).
- [ ] **Falha antes:** o teste de layout acusa qualquer template que ainda sobrescreva `block content` (se nenhum acusar, registre).
- [ ] `/inicio/api/gestao/?periodo=mes_anterior` e `?periodo=ultimos_30_dias` devolvem as datas certas no bloco `periodo` (teste com data fixa).

## Critérios de aceite
- [ ] Navegador, console aberto, **sem erros**: tela inicial com `gerente.bsb` e com o superusuário (Gases Goiás e Oxigênio Brasília); cada botão de período muda os números; nenhum cartão com "—".
- [ ] Faturamento do mês na home coerente com a aba Vendas (ou diferença explicada).
- [ ] Definição de pronto (seção 9).

## Fora do escopo
Ajustes de layout, abas e rolagem (Sprint U01).
