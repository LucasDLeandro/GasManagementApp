# Sprint 01.01 — Ativos 360°: filtros que funcionam, contadores e drawer seguro

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md` e `docs/sprints/00_REGRAS_GERAIS.md` (inteiro). Depende da Sprint 01.00.
Leia também: `docs/DESIGN_SYSTEM.md` e a seção 5 de `docs/GUIA_MODULOS_BAROS.md`.
**Branch:** `sprint-01.01/ativos-drawer` a partir de `sprint-01.00/lotes-cq`.

## Objetivo
A aba Ativos 360° de `/produtos/` abre já filtrada quando vem de um atalho (home, outras telas), mostra contadores da frota e o drawer do cilindro exibe dados de cadastro sem risco de XSS.

## O que está errado (verificado em 10/11/2026)
1. **Atalhos da home não filtram.** `core/views.py::HomeView` aponta para `/produtos/?status=VAZIO_TRIAGEM`, `?reteste_vencido=true`, `?bloqueio_sanitario=true` e `?filtro=extravio_candidato`. `cilindros_drawer.js` só lê `cilindro_id`/`abrir_drawer` da URL: a lista abre sem filtro.
2. **Números divergentes.** A home conta reteste "vencendo ou vencido" com `data_proximo_reteste <= hoje + 30`; o filtro `reteste_vencido=true` do `CilindroViewSet` usa `< hoje`. O cartão diz 5 e a lista mostra 2.
3. **XSS armazenado.** A tabela (`tbodyCilindros.innerHTML = cilindros.map(...)`, ~linha 117) insere `cliente_posse_nome` e `motivo_bloqueio_sanitario` (texto livre digitado por usuário). A linha do tempo (~333) e os retestes (~396) também montam HTML com dados; o erro (~105) insere `err.message`. Total: 13 `innerHTML` no arquivo.
4. **Estilo.** Badges de status com cores fixas inline (`#e0f2fe`, `#fef3c7`...). `style="`: `_aba_ativos.html` 20, `_drawer_cilindro.html` 23, `_abas_nav.html` 2.
5. **Sem visão geral.** Não há contadores da frota no topo da aba.

## O que já existe (não refazer)
- `GET /produtos/api/cilindros/` com `search`, `status`, `propriedade`, `gas`, `bloqueio_sanitario`, `reteste_vencido`, `filtro=extravio_candidato`, paginação no servidor.
- Actions `timeline` e `timeline-retestes`; modais de ação (bloqueio, reteste, reclassificação, estorno) em `_modais.html`; `window.CilindrosFrota`; `id="btn-novo-cilindro"`.

## Escopo
- **Filtros pela URL:** ao carregar, ler `status`, `bloqueio_sanitario`, `reteste_vencido`, `reteste_ate_dias`, `filtro`, `gas`, `search`; aplicar na chamada da API, marcar a pílula correspondente e atualizar a URL (`history.replaceState`) quando o usuário trocar de filtro, para o link poder ser copiado.
- **Reteste:** novo parâmetro `reteste_ate_dias=N` no `CilindroViewSet` (`data_proximo_reteste <= hoje + N`, exclui baixados). Ajustar o link da home para `?reteste_ate_dias=30`, com o mesmo critério da contagem.
- **Contadores:** action `GET /produtos/api/cilindros/resumo/` com uma consulta agregada: total, cheios no pátio, em clientes, vazios em triagem, em rota, em reteste, bloqueados, reteste vencido, reteste em 30 dias. Cartões no topo da aba; clicar num cartão aplica o filtro.
- **Tabela e drawer com `createElement`/`textContent`** em todos os pontos que recebem dado da API (tabela, linha do tempo, retestes, mensagens de erro). Badges `badge-status-*`.
- **Drawer:** abre pela direita (480px; tela cheia até 640px), fecha com Esc e devolve o foco; seções identificação, situação atual, patrimônio, próximo reteste, linha do tempo do ledger e retestes. Botões de ação só para o papel que pode executar (o backend continua validando).
- Zero `style="` nas três parciais (exceto largura dinâmica de barra de progresso).

## Testes
- [ ] **Falha antes:** teste estático — `cilindros_drawer.js` não contém `innerHTML` recebendo template string com `${` (hoje falha).
- [ ] `reteste_ate_dias=30` devolve os vencidos e os que vencem em 30 dias, e a contagem bate com a da home (mesma função de critério, reaproveitada pelas duas).
- [ ] `resumo`: contagens corretas com dados montados no teste; isolamento entre empresas; no máximo 3 consultas.
- [ ] Renderização de `/produtos/` com GERENTE: IDs principais presentes, sem `alert(`.

## Critérios de aceite
- [ ] No navegador (cópia do banco, seção 6): cada atalho da home abre a aba com o filtro certo e o mesmo número do cartão; clicar nos cartões filtra; o drawer abre, fecha com Esc e mostra a linha do tempo. Temas claro, escuro e alto contraste; 375px.
- [ ] Definição de pronto (seção 9).

## Fora do escopo
Lotes/CQ (01.00), etiquetas (01.02), redesign da home (01B).
