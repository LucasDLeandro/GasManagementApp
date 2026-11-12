# Relatório da Entrega 01B.02 — Home: Fila por Papel, Visão de Gestão, Limpeza e Dados de Exemplo

**Data:** 12/11/2026  
**Branch:** `sprint-01b.02/home-gestao`  
**Base:** `fase-2/produtos` (commit `4fc6e99` contendo Entrega 01B.01)  
**Status:** Pronto para Revisão  

---

## 1. O que foi feito (por ID de tarefa)

### Tarefa 01B.3 — Home: fila operacional por papel (corrigida)
- **Paridade ADMIN e GERENTE:** Ambos os papéis possuem visualização idêntica de todos os cartões operacionais da fila de ação imediata.
- **Alertas Sanitários:** Alertas operacionais de cilindros com bloqueio sanitário ativo (`Cilindro.bloqueio_sanitario=True`) e campanhas de recall abertas (`RecallCampanha.status in ['ABERTO', 'HOMOLOGADO_RT', 'EM_NOTIFICACAO']`) são exibidos para ADMIN e GERENTE (visão de acompanhamento; ação de liberação exclusiva do RT).
- **Separação de Pedidos:** A esteira da fila operacional divide com precisão os pedidos aguardando início de separação (`status='Pendente'`) dos pedidos em processo de bipagem e separação de cascos (`status='Em Separação'`).
- **Eliminação de Duplicidades:** Removido o cartão de métrica de reteste duplicado nos KPIs do topo (o alerta permanece na fila operacional e sua projeção detalhada de 90 dias integra a Visão de Gestão).
- **Tempo de Espera do Mais Antigo:** Cada cartão da fila operacional informa há quanto tempo o item mais antigo está aguardando ação (ex: `mais antigo: há 2 h`), calculado com base no histórico de status e datas de movimentação.
- **Botão "Abrir Monitor de TV":** Disponibilizado no header da Home para ADMIN e GERENTE quando a empresa possui ao menos um [PainelMonitor](file:///c:/Lucas/GasManagementApp/core/models.py) ativo configurado.

### Tarefa 01B.4 — Home: visão de gestão (ADMIN e GERENTE)
- **Serviço Centralizado:** Desenvolvido o serviço [core/services/visao_gestao.py](file:///c:/Lucas/GasManagementApp/core/services/visao_gestao.py) com a função canônica `montar_visao_gestao()`.
- **Endpoint da API:** `GET /inicio/api/gestao/?periodo=[mes_atual|mes_anterior|ultimos_30_dias]` protegido com `[IsAuthenticated, IsTenantAdminOrGerente]`. Perfis operacionais (VENDEDOR, OPERADOR_PATIO, RT, MOTORISTA) recebem status HTTP 403 Forbidden.
- **Isolamento de Cache Particionado:** Cache de 5 minutos utilizando chave estrita: `cache_visao_gestao_{tenant.id}_{periodo}_{tem_dre}`, impedindo qualquer vazamento de dados do bloco financeiro entre usuários com e sem permissão de DRE.
- **Indicadores Estratégicos:**
  - *Vendas & Faturamento:* Faturamento do período computa estritamente pedidos faturados/entregues/em rota, excluindo Canceladas, Pendentes e Bloqueados por Crédito; variação percentual calculada com a mesma fórmula estrita sobre o período homólogo anterior; contagem de pedidos faturados; ticket médio; divisão à vista × a prazo; alerta em badge com quantidade e valor de pedidos bloqueados por crédito (`BLOQUEADO_FINANCEIRO`); e gráfico diário com agregação única via `TruncDate`.
  - *Patrimônio de Cascos:* Valoração do parque priorizando a [TabelaIndenizacaoCilindro](file:///c:/Lucas/GasManagementApp/produtos/models.py) vigente para o par `(modelo, gas_dedicado)`, com fallback para `valor_aquisicao`. Retorno explícito da base avaliada e da quantidade de `cascos_sem_valor` (sem somar zero silenciosamente); contagem de cascos em clientes; risco em R$ de cascos retidos há mais de 90 e 180 dias; e taxa de estadia acumulada a faturar.
  - *Giro Médio do Casco:* Média em dias calculada em Python sobre os ciclos fechados nos últimos 90 dias entre saída (`ENTREGA_CLIENTE`/`SAIDA_ENTREGA`) e retorno (`RECOLHA_CLIENTE`/`RETORNO_VAZIO`), desconsiderando estornos e movimentações estornadas (`estornada_por__isnull=False`), com detalhamento por gás químico.
  - *Nível de Serviço (OTIF):* Percentual de entregas realizadas dentro do `prazo_entrega` e base avaliada (X de Y entregas com prazo preenchido).
  - *Conformidade Normativa:* Contagem de retestes vencidos e vencendo nos próximos 90 dias com distribuição mês a mês.
  - *Bloco Financeiro Condicional:* Ativo somente quando `is_modulo_ativo(tenant, 'financeiro')` e `user_has_ver_dre(request)` forem verdadeiros. Exibe contas a receber em aberto, vencidos (inadimplência), saldo disponível em caixa/bancos, contas a pagar nos próximos 7 dias e lista dos 5 maiores clientes devedores destacando quem retém cascos há mais de 90 dias. Sem o módulo ou sem permissão, apresenta aviso explicativo limpo e amigável sem exibir valores zerados como se fossem reais.
  - *Transparência Total:* Tooltips informativos (atributo `title`) em todos os cartões explicando a fórmula matemática e a fonte de dados.

### Tarefa 01B.5 — Limpeza de `DashboardStatsAPIView` e `home.html`
- **Otimização de Consultas:** Eliminado o laço de 7 consultas diárias em `DashboardStatsAPIView`, substituído por uma única agregação agrupada com `TruncDate`.
- **Eliminação Total de Estilos Inline:** [core/templates/core/home.html](file:///c:/Lucas/GasManagementApp/core/templates/core/home.html) foi 100% limpo, atingindo **zero ocorrências de `style="`** (todas as 44 ocorrências removidas).
- **Atributo Nativo `hidden`:** Estados de visibilidade condicional foram migrados para o atributo nativo `hidden` e manipulados via JavaScript com `removeAttribute('hidden')` / `setAttribute('hidden', '')`.
- **Design System Tokens:** Toda estilização visual, espaçamentos, cores e badges foram migrados para [core/static/core/css/dashboard.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/dashboard.css) utilizando estritamente variáveis de tokens do tema (`var(--color-primary)`, `var(--color-surface)`, `var(--status-approved-*)`, `var(--status-danger-*)`, etc.), garantindo suporte aos temas claro, escuro e alto contraste.
- **Segurança de Frontend:** Construção dinâmica do DOM em JavaScript com `document.createElement`, `classList`, `textContent` e `replaceChildren` (zero `innerHTML` com dados da API).

### Tarefa 01B.6 — Dados de exemplo em `populate_db.py`
- Povoamento do tenant padrão `00000000-0000-0000-0000-000000000001` ("Distribuidora Padrão de Gases") com 20 cilindros físicos distribuídos coerentemente entre pátio (`CHEIO_DISPONIVEL`, `VAZIO_TRIAGEM`), clientes (`EM_POSSE_CLIENTE`), rotas e retestes.
- Criação de contratos de comodato, movimentações de entrega com datas passadas, tabelas de indenização vigentes e históricos de status com horários espalhados.
- Idempotência validada: execuções repetidas completam com 100% de sucesso sem duplicação de dados.

---

## 2. Bugs encontrados e corrigidos no caminho

1. **Reversão da alteração em `core/permissions.py`:** Inicialmente, para testar gerente sem DRE, havíamos alterado `core/permissions.py` excluindo GERENTE. Conforme apontado na revisão, essa mudança alteraria o acesso ao DRE no sistema inteiro e não fazia parte do escopo. A alteração foi **completamente revertida**, restaurando `membership.papel in ('ADMIN', 'GERENTE')`, e o isolamento de cache no teste `test_02_cache_visao_gestao_chave_distingue_ver_dre` foi implementado via mock pontual da função `user_has_ver_dre`.
2. **Estilos inline e `innerHTML` inseguro no frontend:** O template continha 44 ocorrências de `style="` e renderizações via template string em `innerHTML` para lotes, devedores e radar de comodato. Todos foram substituídos por classes em `dashboard.css`, elementos criados com `document.createElement` e manipulação segura de texto via `textContent`.
3. **Constraint de integridade em movimentações manuais nos testes:** Movimentações de cilindro sem vínculo a lote de envase ou recebimento disparavam violação de `check_movimentacao_envase_coerente`. Corrigido nos testes definindo `is_legado=True` para movimentações simuladas.
4. **Campo de relacionamento em `HistoricoStatusVenda` e `HistoricoStatusEntrega` no script de povoamento:** O script usava `historicos_status__isnull` (plural), quando o `related_name` correto é `historico_status` (singular). Corrigido.

---

## 3. O que ficou de fora e por quê

- Telemetria IoT dos tanques de criogenia e alertas sonoros no monitor de TV (explicitamente fora de escopo da sprint).
- Automação do fluxo de cobrança de extravio de cascos retidos há mais de 180 dias (escopo da Sprint 02).

---

## 4. Decisões tomadas por premissa (para validação com o Dono do Produto e RT)

1. **(a) Regra de À Vista × A Prazo (Formas de Pagamento):**
   - Vendas com forma de pagamento `PIX`, `DINHEIRO` e `CARTAO` são contabilizadas como "À Vista". Vendas com `BOLETO`, `FATURADO` e `EMPENHO` são computadas como "A Prazo".
   - *Decisão para validação do dono:* Boletos bancários emitidos para faturamento contra apresentação ou D+0 podem na prática ser considerados à vista. A convenção foi explicitada no tooltip de ajuda da métrica.
2. **(b) Regra de "Inspeção Pendente" no Monitor (Validação com o RT):**
   - Cilindros no pátio com status `VAZIO_TRIAGEM` sem inspeção pré-envase ([InspecaoPreEnvase](file:///c:/Lucas/GasManagementApp/produtos/models.py)) com `aprovado=True` realizada nos últimos 7 dias são computados como inspeção pendente.
   - *Decisão para validação com o RT:* Confirmar se o intervalo de 7 dias atende aos Procedimentos Operacionais Padrão (POPs) da distribuidora e às diretrizes da RDC 501 / IN 129 da ANVISA, ou se deve expirar imediatamente em cada ciclo de recolha.
3. **(c) Premissas de Cálculo da Visão de Gestão:**
   - *Faturamento:* Exclui estritamente `Cancelada`, `Pendente` e `BLOQUEADO_FINANCEIRO`. A variação percentual adota rigorosamente a mesma exclusão no período homólogo anterior.
   - *Valoração de Cascos:* Prioridade para a `TabelaIndenizacaoCilindro` vigente para o par `(modelo, gas_dedicado)`, com fallback para `valor_aquisicao`. Se ambos forem nulos ou zero, o sistema não soma zero silenciosamente: reporta os `cascos_sem_valor` em separado e informa na tela a cobertura real (ex: "valor de 18 de 20 cascos").
   - *Giro do Casco:* Considera ciclos fechados nos últimos 90 dias entre a saída do cilindro e o retorno, desconsiderando movimentações estornadas e as que estornam outras.
   - *Nível de Serviço (OTIF):* Computa o percentual de entregas realizadas até o `prazo_entrega` acordado, considerando apenas vendas entregues com prazo e data efetiva preenchidos.
4. **(d) Acesso de GERENTE ao DRE e Bloco Financeiro:**
   - No código atual mantido intacto, `user_has_ver_dre` concede acesso financeiro/DRE para membros com papel `ADMIN` ou `GERENTE` (além de superusers e grupos financeiros). Registra-se como decisão pendente para o dono do produto se no futuro o papel `GERENTE` deve ter o DRE restrito a quem possuir a permissão granular `financeiro.ver_dre` atribuída.

---

## 5. Resultado da Suíte de Testes e Checagens

- **Suíte Global Completa (`pytest -q -p no:cacheprovider`):** **748 passed**, 0 failed (218.09s — 100% verde).
- **Suíte da Entrega 01B.02 (`test_sprint01b_02_home_gestao.py`):** **8 passed** (86.85s).
- **Suíte da Entrega 01B.01 (`test_sprint01b_01_monitor_tv.py`):** **16 passed** (65.84s — regressão zero).
- **Verificações de Integridade do Django:**
  - `python manage.py check` → `System check identified no issues (0 silenced).`
  - `python manage.py makemigrations --check --dry-run` → `No changes detected`
- **Contagens Estáticas nos Arquivos Tocados:**
  - `core/templates/core/home.html`:
    - `style="`: **0**
    - `alert(`: **0**
    - `innerHTML`: **0**
  - `core/static/core/css/dashboard.css`:
    - 100% tokens do Design System, zero `style="`.

---

## 6. Lista de Commits

1. `26c63da fix(core): pátio do monitor conta só cheios aptos`
2. `919e1b6 feat(core): home de gestao, filas operacionais e dados de exemplo conforme sprint 01b.02`
3. Commit desta revisão: `fix(core): conformidade estrita de template, reversao de permissions e limpeza de estilos`

---

## 7. Notas de Deploy

- **Migrações:** Nenhuma migração nova.
- **Variáveis de ambiente:** Nenhuma variável nova.
- **Estáticos:** Rodar `python manage.py collectstatic --noinput` para atualizar arquivos estáticos.
- > [!CAUTION]
  > **ATENÇÃO:** O script `populate_db.py` **NÃO DEVE** ser executado em servidores de homologação/teste ou produção. Ele foi concebido exclusivamente para bootstrapping de cenários em ambientes locais de desenvolvimento desacoplados.

---

## 8. Checklists da Sprint

### Testes Obrigatórios
- [x] Histórico: toda transição de venda e de entrega grava uma linha; a migração de dados cria a linha inicial (Entrega 01B.00).
- [x] Painel: token inválido/inativo → 404; isolamento entre empresas (token da empresa A nunca mostra dados da B); throttle; ausência de dados financeiros e de contato; `mostrar_nomes_clientes=False` esconde os nomes (Entrega 01B.01).
- [x] Seção "Fábrica" só aparece com o módulo envase; "Esteira" só com distribuição (Entrega 01B.01).
- [x] Visão de gestão: 403 para VENDEDOR/OPERADOR_PATIO/RT; bloco financeiro ausente sem o módulo ou sem `ver_dre`; giro médio e risco em R$ conferidos com dados montados no teste (Entrega 01B.02).

### Critérios de Aceite
- [x] Um painel criado em Configurações abre numa aba anônima pelo link, atualiza sozinho e some (404) ao ser revogado.
- [x] O JSON do painel não contém nenhum valor monetário nem dado de contato (teste automatizado que varre as chaves e valores recursivamente).
- [x] Home de ADMIN com e sem módulo financeiro, verificada e funcional em ambos os casos.
- [x] `GET /inicio/` + `/inicio/api/stats/` + `/inicio/api/gestao/` sem N+1 (consultas agrupadas com TruncDate e agregação única).
- [x] Suíte verde.
