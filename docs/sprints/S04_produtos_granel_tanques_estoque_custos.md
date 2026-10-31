# Sprint 04: Produtos, granel, tanques criogênicos, estoque e custo de envase

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 5.5 de `docs/GUIA_MODULOS_BAROS.md` e a seção "Sprint 8C" de `docs/DECISOES_PENDENTES.md` (tolerância de pesagem de 2%, boil-off de 3% com justificativa e rateio de energia).
**Branch:** `sprint-04/produtos-granel` a partir de `sprint-03/produtos-retestes-baixa`.

## Objetivo
Dar tela à cadeia gás a granel → tanque → envase → custo → estoque da Sprint 8C, que hoje só existe na API.

## O que já existe
- APIs: `/produtos/api/tanques/` (actions `painel`, `registrar-medicao`, `fechar-periodo`), `/produtos/api/medicoes-tanque/`, `/produtos/api/entradas-granel/`, `/produtos/api/estoque-gas/movimentos/` (somente leitura), `/produtos/api/custos-lote/` (somente leitura + action `estornar`), `/produtos/api/estoque-produto/movimentos/` (somente leitura), `/produtos/api/lotes/{id}/fechar/` (fecha o lote e apura o custo).
- Serviços: `produtos/services/granel.py` (`registrar_entrada_granel`, `registrar_medicao_tanque`, `fechar_periodo_tanque`, `registrar_perda_purga`), `custo_envase.py` (`fechar_lote_envase`, `estornar_fechamento_lote`) e `estoque_produto.py` (`movimentar_estoque_produto`).
- Todas essas telas dependem do módulo **envase** (`RequiresModuleEnvase`).

## Tarefas

### 04.1 Página "Tanques e granel" (`/produtos/tanques/`)
- Um cartão por tanque: gás, capacidade, nível atual (barra), última medição e alerta de nível baixo. Os dados vêm da action `painel`.
- Detalhe do tanque (drawer ou página): gráfico de nível ao longo do tempo com a biblioteca já existente em `static/vendor/chartjs` (não use CDN), lista de movimentos de estoque de gás e de medições.
- **Cadastro e edição de tanque**: modal com seções (só ADMIN e GERENTE).
- **Registrar medição**: modal simples (data e hora, nível ou massa e responsável).
- **Entrada a granel em etapas**: Nota fiscal (fornecedor, chave NF-e, massa da NF) → Pesagem (massa pesada) com **divergência NF × pesagem ao vivo**, aviso acima de 2% e justificativa obrigatória acima da tolerância → Revisão.
- **Perda por purga**: modal com motivo obrigatório (`registrar_perda_purga`; crie o endpoint se não existir).
- **Fechar período do tanque**: mostrar a perda por evaporação apurada; se passar de 3%, exigir justificativa (regra 8C.2) e confirmar.

### 04.2 Lotes de envase e custo
- Na aba Lotes/CQ da tela `/produtos/` (feita na Sprint 01), acrescentar a ação **"Fechar lote"** (apura o custo com `fechar_lote_envase`) e mostrar o custo apurado (gás, energia e total por cilindro) com estorno (motivo obrigatório; ADMIN e GERENTE).
- **Energia da rampa** (`CustoEnergiaRampa`): pequena tela de configuração mensal (valor da conta e kWh) na página de tanques. Crie a API se não existir, com só ADMIN e GERENTE escrevendo.

### 04.3 Estoque
- Página `/produtos/estoque/` com duas abas:
  - **Gás por tanque**: saldo e extrato de movimentos com tipo, quantidade, saldo e origem.
  - **Produto acabado por SKU**: saldo, custo médio e extrato; filtro por período.
- Ajuste manual de estoque de produto (`movimentar_estoque_produto` com tipo `AJUSTE` ou `PERDA`): modal com motivo obrigatório, só ADMIN e GERENTE. Crie o endpoint se não existir.
- Links no menu lateral para "Tanques e granel" e "Estoque", visíveis só com o módulo envase.

## Critérios de aceite
- Fluxo completo na tela: entrada a granel com divergência → medição → envase na rampa (já existe) → fechar o lote → ver o custo → ver o estoque de produto.
- Tolerâncias de 2% e 3% aplicadas com justificativa, também no backend.
- Suíte verde.

## Testes obrigatórios
- Entrada a granel acima da tolerância sem justificativa responde 400.
- Fechamento de período com perda acima de 3% sem justificativa responde 400.
- Ajuste de estoque: só ADMIN e GERENTE; motivo obrigatório.
- Isolamento entre empresas nos endpoints novos.
- Renderização das páginas novas (com o módulo envase ligado no tenant de teste).

## Fora do escopo
Telemetria IoT de tanques nos hospitais (roadmap futuro).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_04.md`.
