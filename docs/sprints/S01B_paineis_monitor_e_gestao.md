# Sprint 01B: Painéis — monitor operacional (TV) e visão de gestão na home

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a "FASE 7" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md` (tarefas 7.1 a 7.1.4) e `core/views.py` (`HomeView` e `DashboardStatsAPIView`).
**Branch:** crie `sprint-01b/paineis` a partir de `sprint-01.02/etiquetas`.

## Objetivo
Separar o que hoje está misturado na home (`/inicio/`):
1. **Monitor operacional**: uma tela para ficar numa TV do pátio ou da expedição, sem login, mostrando a fila de trabalho do momento (como os painéis de senha de hospitais e de centros de distribuição).
2. **Home de gestão** para ADMIN e GERENTE: a home atual continua, mas ganha no topo uma visão básica do negócio (vendas, patrimônio, dinheiro), que funciona **com ou sem** o módulo financeiro contratado.

## Diagnóstico da home atual (não repetir estes problemas)
- `DashboardStatsAPIView` calcula e descarta `faturamento_mes`, `entregas_pendentes`, `clientes_ativos`, `frota_manutencao`, `estoque_baixo` e as vendas dos últimos 7 dias (7 consultas, uma por dia). Nada disso aparece na tela.
- O alerta de reteste aparece duas vezes (fila e cartão de métrica).
- GERENTE não vê os cartões de rotas e pedidos; ADMIN não vê bloqueio sanitário nem recall.
- "Pedidos aguardando expedição" mistura `Pendente` com `Em Separação`.
- Estilos inline e cores fixas em `core/templates/core/home.html`.
- O sistema **não guarda quando cada status da venda ou da entrega mudou** (só há `prazo_entrega` e `data_entrega_efetiva`), então não é possível medir tempo de espera.

## Tarefas

### 01B.1 Histórico de status (pré-requisito)
- Criar `vendas.HistoricoStatusVenda` (`TenantAwareModel`): `venda` (FK), `status_anterior`, `status_novo`, `alterado_em` (`auto_now_add`, indexado), `alterado_por` (FK User, `null=True`), `origem` (`TELA`, `API`, `APP_CAMPO`, `SISTEMA`).
- Gravar uma linha **em todo** ponto onde o status da venda muda, a começar por `vendas/services/status.py::transicionar_venda()`. Procure com `grep` outros pontos que alterem `venda.status` diretamente e faça-os passar pelo serviço ou gravar o histórico.
- Fazer o mesmo para `logistica.Entrega` (`HistoricoStatusEntrega`).
- Migração de dados: para vendas e entregas existentes, criar uma linha inicial com o status atual e `alterado_em = data_atualizacao` (ou `data_venda`), marcada como `origem='SISTEMA'`.
- Uma propriedade/consulta reutilizável `desde_quando_no_status(venda)` (último registro com `status_novo == venda.status`).

### 01B.2 Monitor operacional (`/painel/<token>/`)
**Acesso:**
- Modelo `core.PainelMonitor` (`TenantAwareModel`): `nome` (ex.: "TV Expedição"), `filial` (FK opcional), `token` (gerado com `secrets.token_urlsafe(32)`, único, nunca o id), `ativo`, `criado_por`, `criado_em`, `ultimo_acesso_em`, `mostrar_nomes_clientes` (bool, padrão `True`), `tempo_alerta_min` (padrão 30) e `tempo_critico_min` (padrão 60), `secoes` (JSON com as seções ligadas).
- Tela de gestão dos painéis (ADMIN e GERENTE) em Configurações: criar, copiar o link, revogar (desativar) e gerar novo token.
- Rota pública `path('painel/<str:token>/', ...)` (HTML) e `path('painel/<str:token>/dados/', ...)` (JSON). **Sem sessão e sem DRF auth**: o token resolve o tenant (siga o padrão do link público de cobrança `cobranca/<uuid>/` e do rastreio público). Token inválido ou inativo → 404 (não 403, para não confirmar que existe). Atualize `ultimo_acesso_em` no máximo 1 vez por minuto.
- O JSON **não pode** conter valores em R$, CNPJ, telefone, endereço completo nem nada financeiro. Se `mostrar_nomes_clientes=False`, mostrar só o nº do pedido e o bairro/cidade.
- Throttle por token (ex.: 12 requisições por minuto) para evitar abuso.

**Layout (pensado para TV a 3–4 m de distância):**
- Tema escuro, fonte grande (mínimo 24px no corpo, números de 48px+), sem rolagem: se a coluna encher, mostrar "+N pedidos". Paleta só com significado: verde (no prazo), amarelo (passou de `tempo_alerta_min`), vermelho (passou de `tempo_critico_min` ou atrasado em relação ao `prazo_entrega`).
- Atualização automática a cada 30 s via `fetch` (sem recarregar a página), relógio no canto e "atualizado há X s". Se a atualização falhar por mais de 2 minutos, mostrar uma faixa "SEM CONEXÃO — dados de HH:MM" em vez de dados velhos sem aviso.
- Tela cheia ao clicar uma vez (Fullscreen API) e `wake lock` quando o navegador suportar.

**Seções (cada uma liga/desliga em `secoes`; respeitar módulos ativos):**
1. **Esteira de pedidos** (módulo distribuição/vendas): colunas *A separar* (`Pendente`) → *Em separação* → *Pronto para carregar / Faturada* → *Em rota* → *Concluídos hoje* (só o número). Cada cartão: nº do pedido, cliente (ou bairro), gases e quantidades, e **há quanto tempo está na etapa** (01B.1), com a cor de alerta. Pedidos `BLOQUEADO_FINANCEIRO` aparecem com selo "Bloqueado" na coluna *A separar*, sem o motivo.
2. **Pátio × demanda por gás**: para cada gás/SKU, cheios disponíveis (`CHEIO_DISPONIVEL`) contra a quantidade pedida nos pedidos em aberto com `prazo_entrega` até hoje. Falta → vermelho ("O₂ 10 m³: faltam 6"). Até a Sprint 05, os itens de venda podem apontar para `sku` ou para o `produto` legado: trate os dois.
3. **Retornos**: vazios em triagem (`VAZIO_TRIAGEM`) e recolhas previstas para hoje.
4. **Faixa de alertas** no rodapé: cilindros **no pátio** com reteste vencido (não podem sair), bloqueios sanitários, recall aberto.
5. **Fábrica** (só com módulo envase): fila da rampa (inspeções pendentes), lotes em quarentena e **nível dos tanques** em % (`saldo_atual_kg / capacidade_kg`, usando a action `painel` de `/produtos/api/tanques/`), com alerta de nível baixo.
- O JSON é montado por um serviço `core/services/painel_monitor.py::montar_dados_painel(painel)` com consultas agregadas (sem N+1; meta: até 15 consultas por atualização) e cache de 15 s por painel.

### 01B.3 Home: fila operacional por papel (corrigir)
- GERENTE passa a ver os mesmos cartões operacionais que o ADMIN. ADMIN e GERENTE passam a ver também bloqueio sanitário e recall aberto (só leitura; a ação continua com o RT).
- Separar "Pedidos aguardando aprovação/produção" (`Pendente`) de "Pedidos em separação".
- Remover o cartão de métrica de reteste duplicado (fica só na fila; na visão de gestão vai a janela de 90 dias, ver 01B.4).
- Cartões da fila com tempo de espera do mais antigo ("mais antigo: há 2 h") usando 01B.1.
- Botão "Abrir monitor" para ADMIN e GERENTE quando houver painel cadastrado.

### 01B.4 Home: visão de gestão (ADMIN e GERENTE)
Bloco "Visão do negócio" no topo da home, com seletor de período (mês atual × mês anterior até o mesmo dia). Montado por `core/services/visao_gestao.py`, uma consulta agregada por grupo, cache de 5 min por tenant, e exposto em `GET /inicio/api/gestao/` (com `TenantViewSetMixin`; 403 para outros papéis). Cada número mostra, ao passar o mouse, a fórmula e a fonte (padrão já usado em `analytics/views.py`).

**Sempre (sem depender do módulo financeiro):**
- **Vendas:** faturamento do período (vendas não canceladas), variação % contra o período anterior, nº de pedidos, ticket médio, gráfico de linha diário do mês (uma consulta com `TruncDate`, não 30 consultas).
- **Vendas a prazo × à vista** do período (por `condicao_pagamento`/`forma_pagamento`) e **pedidos bloqueados por crédito** (`BLOQUEADO_FINANCEIRO`) com o valor somado.
- **Patrimônio:** total de cascos, valor do parque (pela `TabelaIndenizacaoCilindro` ou pelo valor do `AtivoImobilizado`, o que existir; deixar claro qual), cascos em clientes, **risco em R$** (cascos em clientes há mais de 90 e de 180 dias) e **estadia a faturar** (já calculada por `calcular_radar_comodato_tenant`).
- **Giro médio do casco:** média de dias entre a saída para o cliente (`ENTREGA_CLIENTE`/`SAIDA_ENTREGA`) e o retorno (`RECOLHA_CLIENTE`/`RETORNO_VAZIO`) no ledger `MovimentacaoCilindro`, nos ciclos fechados nos últimos 90 dias. Mostrar também por gás.
- **Conformidade:** retestes vencendo em 90 dias (agrupados por mês, para planejar envio em lote) e vencidos.
- **Nível de serviço:** % de pedidos entregues até o `prazo_entrega` no período.
- **Clientes em risco de parar de comprar:** contagem e top 5 dos `AlertaComercial` tipo `RISCO_CHURN` não resolvidos (só se o módulo vendas ou comercial estiver ativo), com link para o funil.

**Só com o módulo financeiro ativo e permissão `ver_dre`** (`is_modulo_ativo(tenant, 'financeiro')` + `user_has_ver_dre`):
- **A receber:** em aberto, vencido (inadimplência) e a vencer em 30 dias, a partir das parcelas (`ParcelaFinanceira`/`TituloFinanceiro`), com os 5 maiores devedores. Destacar quem é devedor **e** tem casco retido há mais de 90 dias.
- **Caixa:** saldo das contas (`ContaFinanceira`) e o alerta de caixa aberto (`AlertaCaixa`), se houver.
- **A pagar** nos próximos 7 dias.

**Sem o módulo financeiro:** no lugar do bloco "Dinheiro", mostrar só o que vem de vendas (faturado, a prazo, bloqueados) e um aviso discreto "Contas a receber, inadimplência e caixa ficam disponíveis com o módulo Financeiro". Nunca mostrar números zerados como se fossem reais.

- Link "Análise completa" para o Analytics quando o módulo estiver ativo.
- Os outros papéis (VENDEDOR, OPERADOR_PATIO, RT) continuam vendo só a fila do seu papel; MOTORISTA continua indo para `/campo/`.

### 01B.5 Limpeza de `DashboardStatsAPIView` e da home
- Remover os cálculos que nenhuma tela usa (ou movê-los para 01B.4), eliminar o laço de 7 consultas e a duplicidade do reteste.
- Zero estilos inline e zero cores fixas em `home.html`: usar os tokens e componentes do Design System (`ds-page-header`, cartões de métrica, `badge-status-*`, `ds-skeleton`, estados vazio e erro).

### 01B.6 Dados de exemplo
- `populate_db.py`: a empresa "Distribuidora Padrão de Gases" (`tenant 0…01`) tem 37 vendas e 9 entregas mas **nenhum cilindro**, o que zera a home. Gerar cilindros coerentes com as vendas e entregas (em pátio, em rota, em clientes com idades variadas de posse, alguns com reteste vencendo) e histórico de status com horários espalhados no dia, para o monitor ter o que mostrar. O script continua idempotente.

## Critérios de aceite
- Um painel criado em Configurações abre numa aba anônima pelo link, atualiza sozinho e some (404) ao ser revogado.
- O JSON do painel não contém nenhum valor monetário nem dado de contato (teste automatizado que varre as chaves e valores).
- Home de ADMIN com e sem módulo financeiro, verificada no navegador nos dois casos.
- `GET /inicio/` + `/inicio/api/stats/` + `/inicio/api/gestao/` sem N+1 (teste com `django_assert_max_num_queries`).
- Suíte verde.

## Testes obrigatórios
- Histórico: toda transição de venda e de entrega grava uma linha; a migração de dados cria a linha inicial.
- Painel: token inválido/inativo → 404; isolamento entre empresas (token da empresa A nunca mostra dados da B); throttle; ausência de dados financeiros e de contato; `mostrar_nomes_clientes=False` esconde os nomes.
- Seção "Fábrica" só aparece com o módulo envase; "Esteira" só com distribuição.
- Visão de gestão: 403 para VENDEDOR/OPERADOR_PATIO/RT; bloco financeiro ausente sem o módulo ou sem `ver_dre`; giro médio e risco em R$ conferidos com dados montados no teste.

## Fora do escopo
- Som/alerta sonoro no monitor e rotação automática entre várias telas (pode vir depois).
- Telemetria IoT dos tanques (roadmap).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_01B.md`.
