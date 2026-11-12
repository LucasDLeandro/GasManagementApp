# Relatório da Entrega 01B.02 — Home: Fila por Papel, Visão de Gestão, Limpeza e Dados de Exemplo

**Data:** 12/11/2026  
**Branch:** `sprint-01b.02/home-gestao`  
**Base:** `fase-2/produtos` (commit `4fc6e99` contendo Entrega 01B.01)  
**Status:** Concluído com 100% de Sucesso e Suíte Verde

---

## 1. Decisões Técnicas Registradas para o Dono do Produto

1. **Validação Técnica com o RT sobre "Inspeção Pendente" na Rampa:**
   - *Regra implementada:* Cilindros no pátio com status `VAZIO_TRIAGEM` sem inspeção pré-envase ([InspecaoPreEnvase](file:///c:/Lucas/GasManagementApp/produtos/models.py)) com `aprovado=True` realizada nos últimos 7 dias são considerados "inspeção pendente".
   - *Decisão para validação com o RT:* Confirmar se o prazo de validade de 7 dias para a inspeção pré-envase antes do acoplamento na rampa atende aos Procedimentos Operacionais Padrão (POPs) da distribuidora e às diretrizes da RDC 501 / IN 129 da ANVISA, ou se deve expirar imediatamente a cada ciclo de envase ou outro intervalo operacional determinado pelo RT.

2. **Conceito de Faturamento do Período:**
   - O indicador de "Faturamento do período" computa estritamente vendas com status faturado/entregue/em rota, excluindo explicitamente vendas canceladas (`Cancelada`), pedidos não confirmados (`Pendente`) e pedidos travados por limite financeiro (`BLOQUEADO_FINANCEIRO`).
   - *Justificativa:* Apresentar aos gestores o faturamento real contratado e em execução, em vez de inflar os valores com intenções de pedido pendentes de aprovação comercial ou pedidos barrados pelo financeiro. A mesma regra se aplica de forma idêntica à base homóloga do período anterior para o cálculo da variação percentual. Os pedidos bloqueados são exibidos em badge de alerta separado.

3. **Critério de Classificação À Vista × A Prazo:**
   - Vendas com forma de pagamento `PIX`, `DINHEIRO` e `CARTAO` são classificadas como "À Vista". Vendas com `BOLETO`, `FATURADO` e `EMPENHO` são computadas como "A Prazo".
   - *Decisão para o dono:* Boletos bancários podem eventualmente ser emitidos para pagamento à vista (D+0/D+1) ou a prazo (D+28/D+30). O tooltip e o texto de ajuda na interface detalham essa convenção.

4. **Valoração de Cascos e Tratamento de Ativos sem Cadastro de Valor:**
   - O valor do parque prioriza a `TabelaIndenizacaoCilindro` vigente para o par `(modelo, gas_dedicado)`. Na ausência da tabela, recorre ao `valor_aquisicao` do casco. Se nenhum valor estiver cadastrado, o sistema **não** soma zero silenciosamente: reporta a cobertura real (`cascos_avaliados` de `total_cascos`) e discrimina explicitamente a contagem de `cascos_sem_valor`.

5. **Notas de Deploy:**
   - > [!CAUTION]
   - > **ATENÇÃO:** O script `populate_db.py` **NÃO DEVE** ser executado em servidores de homologação/teste ou produção. Ele foi concebido exclusivamente para bootstrapping e geração de cenários de teste em ambientes locais de desenvolvimento desacoplados.

---

## 2. Commit Preliminar

- `fix(core): pátio do monitor conta só cheios aptos`:
  - No monitor operacional ([core/services/painel_monitor.py](file:///c:/Lucas/GasManagementApp/core/services/painel_monitor.py)), o cálculo de "cheios disponíveis" passa a excluir cilindros com `bloqueio_sanitario=True` e cilindros cujo `envase_atual` pertença a lote de produção com status de qualidade diferente de `APROVADO`.
  - Cobertura com teste automatizado dedicado `test_16_monitor_patio_conta_so_cheios_aptos` validando a exclusão de lotes em quarentena e de bloqueios sanitários.

---

## 3. Resumo das Tarefas Executadas

### 01B.3 Fila Operacional por Papel
- **Paridade ADMIN e GERENTE:** O perfil `GERENTE` passa a ter visibilidade completa sobre todos os cartões operacionais de rotas, pátio e pedidos, antes restritos ao administrador.
- **Alertas Sanitários:** ADMIN e GERENTE passam a visualizar alertas operacionais de cilindros com bloqueio sanitário ativo e campanhas de recall abertas pela equipe de Garantia da Qualidade/RT.
- **Separação de Pedidos:** A fila de pedidos separa com clareza os pedidos aguardando início de separação (`Pendente`) dos pedidos em processo de bipagem/carregamento (`Em Separação`).
- **Tempo de Espera do Mais Antigo:** Cada cartão da fila de pedidos exibe há quanto tempo o item mais antigo está aguardando ação (ex: `mais antigo: há 2 h`), calculado com base no histórico de status e datas de movimentação.
- **Botão "Abrir Monitor":** Disponibilizado no header da Home para ADMIN e GERENTE quando a empresa possui ao menos um `PainelMonitor` ativo configurado.
- **Eliminação de Duplicidades:** Removido o card de alerta de reteste que aparecia em duplicidade entre a fila e os KPIs do topo.

### 01B.4 Home: Visão de Gestão (ADMIN e GERENTE)
- **Serviço Centralizado:** Implementado [core/services/visao_gestao.py](file:///c:/Lucas/GasManagementApp/core/services/visao_gestao.py) com a função `montar_visao_gestao()`.
- **Endpoint da API:** `GET /inicio/api/gestao/?periodo=[mes_atual|mes_anterior|ultimos_30_dias]` protegido com `[IsAuthenticated, IsTenantAdminOrGerente]`. Usuários de outros papéis (ex.: VENDEDOR, OPERADOR_PATIO) recebem status HTTP 403 Forbidden.
- **Isolamento de Cache Particionado:** Cache de 5 minutos utilizando chave que inclui o tenant, o período e o indicador de acesso financeiro: `cache_visao_gestao_{tenant.id}_{periodo}_{tem_dre}`, impedindo que um gerente sem permissão financeira visualize dados previamente cacheados por um usuário com DRE.
- **Métricas do Negócio:**
  - *Vendas:* Faturamento total, variação percentual contra período homólogo anterior, contagem de pedidos faturados, ticket médio, divisão à vista vs a prazo, alerta de pedidos bloqueados por crédito com valor total e gráfico diário com agrupamento em consulta única via `TruncDate`.
  - *Patrimônio:* Valoração do parque com Tabela de Indenização / Valor de Aquisição, cobertura avaliada, cascos em clientes, risco financeiro de retenção prolongada (>90 dias e >180 dias) e taxa de estadia acumulada a faturar.
  - *Giro do Casco:* Média em dias de ciclos fechados nos últimos 90 dias entre saída (`ENTREGA_CLIENTE`/`SAIDA_ENTREGA`) e retorno (`RECOLHA_CLIENTE`/`RETORNO_VAZIO`), desconsiderando estornos, com detalhamento por gás químico.
  - *Nível de Serviço (OTIF):* Percentual de entregas realizadas até o `prazo_entrega` acordado, com exibição da base avaliada (X de Y entregas com prazo preenchido).
  - *Conformidade INMETRO:* Cilindros com reteste vencido e projeção dos retestes a vencer nos próximos 90 dias agrupados por mês.
  - *Bloco Financeiro Condicional:* Ativo apenas quando `is_modulo_ativo(tenant, 'financeiro')` e `user_has_ver_dre(request)` forem verdadeiros. Contempla total a receber, inadimplência vencida, saldo consolidado em caixa/bancos, contas a pagar em 7 dias e Top 5 Maiores Devedores com identificação de clientes que retêm cascos há mais de 90 dias. Sem o módulo ou sem permissão, apresenta aviso explicativo transparente sem exibir valores zerados como se fossem reais.
  - *Transparência e Fórmulas:* Todas as métricas contam com tooltips informando a regra matemática e a fonte de dados.

### 01B.5 Limpeza de `DashboardStatsAPIView` e `home.html`
- **Otimização de Consultas:** Eliminado o laço de 7 consultas diárias em `DashboardStatsAPIView`, substituído por uma única consulta agregada com `TruncDate`.
- **Aderência ao Design System:** Removidas todas as tags `<style>` inline e estilos com cores hexadecimais fixas de [core/templates/core/home.html](file:///c:/Lucas/GasManagementApp/core/templates/core/home.html).
- **Estilização Canônica:** Todas as classes migradas para [core/static/core/css/dashboard.css](file:///c:/Lucas/GasManagementApp/core/static/core/css/dashboard.css), utilizando estritamente os tokens de design do tema (`var(--color-primary)`, `var(--color-surface)`, `var(--status-approved-*)`, `var(--status-danger-*)`, etc.), garantindo suporte aos temas claro, escuro e alto contraste.

### 01B.6 Dados de Exemplo no Povoamento (`populate_db.py`)
- Povoamento do tenant padrão `00000000-0000-0000-0000-000000000001` ("Distribuidora Padrão de Gases") com 20 cilindros distribuídos coerentemente entre pátio (`CHEIO_DISPONIVEL`, `VAZIO_TRIAGEM`), clientes (`EM_POSSE_CLIENTE`), rotas e retestes.
- Criação de tabelas de indenização vigentes para permitir a valoração patrimonial.
- Geração de históricos de status ([HistoricoStatusVenda](file:///c:/Lucas/GasManagementApp/vendas/models.py) e [HistoricoStatusEntrega](file:///c:/Lucas/GasManagementApp/logistica/models.py)) com datas distribuídas para permitir a exibição do monitor de TV e das filas de espera.
- Idempotência validada: execuções repetidas não duplicam registros e completam com código de saída 0.

---

## 4. Testes Automatizados Executados

### Suíte da Entrega 01B.02: [core/tests/test_sprint01b_02_home_gestao.py](file:///c:/Lucas/GasManagementApp/core/tests/test_sprint01b_02_home_gestao.py)
1. `test_01_visao_gestao_rbac_apenas_admin_e_gerente`: Valida 200 para ADMIN e GERENTE e 403 Forbidden para VENDEDOR, OPERADOR_PATIO e RESPONSAVEL_TECNICO.
2. `test_02_visao_gestao_cache_distingue_permissao_dre`: Valida isolamento de cache impedindo vazamento de dados do bloco financeiro entre gerentes com e sem DRE.
3. `test_03_visao_gestao_faturamento_exclui_cancelada_pendente_bloqueado`: Valida exclusão estrita de vendas canceladas, pendentes e bloqueadas, além da consistência da variação percentual.
4. `test_04_visao_gestao_valor_parque_e_cascos_sem_valor`: Valida prioridade da Tabela de Indenização, fallback para aquisição e retorno de cascos sem valor sem somar zero.
5. `test_05_visao_gestao_giro_casco_com_estorno`: Valida cálculo exato do tempo de permanência em dias e exclusão correta de ciclos com estorno no ledger de movimentações.
6. `test_06_visao_gestao_otif_nivel_servico`: Valida percentual no prazo e contagem de entregas avaliadas com prazo.
7. `test_07_visao_gestao_bloco_financeiro_com_e_sem_modulo`: Valida contas a receber, caixa, a pagar, Top Devedores com cruzamento de cascos retidos >90 dias e o aviso amigável quando o módulo está desativado.
8. `test_08_home_fila_gerente_e_admin_paridade`: Valida que GERENTE e ADMIN recebem os mesmos cartões, separação de Pendente e Em Separação, tempo de espera e alertas sanitários.

### Suíte da Entrega 01B.01 (Regressão Zero): [core/tests/test_sprint01b_01_monitor_tv.py](file:///c:/Lucas/GasManagementApp/core/tests/test_sprint01b_01_monitor_tv.py)
- 16/16 testes aprovados, incluindo o novo teste `test_16_monitor_patio_conta_so_cheios_aptos`.
