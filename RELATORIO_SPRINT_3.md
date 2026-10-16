# Relatório Técnico - Sprint 3: Ponte com Vendas, Logística Full-for-Empty e Dashboard Radar de Comodato

**Projeto:** GasManagementApp (SaaS de Gestão de Distribuidoras de Gases Industriais e Medicinais)  
**Sprint:** 3 de 6 (MVP Comercial)  
**Status:** Concluído com Sucesso e 100% dos Testes Aprovados  
**Data de Execução:** Outubro/2026  
**Responsável Técnico:** Engenheiro de Software Sênior (Pair Programming Antigravity)  

---

## 1. Objetivo da Sprint

Entregar o **MVP Comercial** do SaaS, conectando as pontas comercial e operacional:
1. Migração gradual das vendas para o catálogo de gases via *Strangler Fig Pattern*.
2. Parametrização contratual de comodato por cliente com cobrança de diárias após carência.
3. Logística de troca bilateral (*Full-for-Empty*) com cálculo exato de peso embarcado para conformidade veicular e fiscal.
4. Painel gerencial de alto impacto visual ("Radar de Comodato & Pátio") com métricas patrimoniais e regulatórias em tempo real.

---

## 2. Entregas Técnicas Executadas

### 2.1. Strangler Pattern em Vendas
- **Arquivo Modificado:** [vendas/models.py](file:///c:/Lucas/GasManagementApp/vendas/models.py)
- **Alterações no Modelo `ItemVenda`:**
  - `produto` ([Produto](file:///c:/Lucas/GasManagementApp/produtos/models.py#L18)) tornado opcional: `null=True, blank=True, on_delete=models.PROTECT`.
  - Inclusão da chave estrangeira `sku` para `produtos.SkuRecarga` (`null=True, blank=True`).
  - Inclusão de `preco_unitario_congelado` (`max_digits=10, decimal_places=2, null=True, blank=True`).
  - **Método `ItemVenda.save()` Atualizado:**
    - Se informado `sku`, congela `preco_unitario_congelado` a partir de `sku.preco_base` e preenche `peso_unitario` com `sku.quantidade_carga`.
    - Se informado `produto` legado, congela o valor com `produto.preco` e capacidade legada.
    - Preserva integralmente o histórico de pedidos passados e telas legadas.

### 2.2. Contrato de Comodato e Motor Analítico do Radar
- **Arquivos:**
  - [clientes/models.py](file:///c:/Lucas/GasManagementApp/clientes/models.py) (`ContratoComodato`)
  - [clientes/services.py](file:///c:/Lucas/GasManagementApp/clientes/services.py) (`calcular_radar_comodato_tenant`)
- **Atributos Contratuais do `ContratoComodato`:**
  - `cliente`: `OneToOneField(Cliente, related_name='contrato_comodato')`.
  - `franquia_cilindros_isentos` (default 0).
  - `dias_carencia_giro` (default 30 dias para consumo e rotação).
  - `valor_diaria_excedente` (default R$ 3,50 por dia após a carência).
  - `custo_reposicao_casco` (default R$ 1.800,00 por cilindro extraviado ou retido).
- **Mecanismo de Cálculo do Radar (`calcular_radar_comodato_tenant`):**
  - Identifica todos os cilindros com `status='EM_POSSE_CLIENTE'`.
  - Compara a data/hora do evento (`posse_desde`) com `timezone.now()`.
  - Subtrai a carência contratual para obter os `dias_excedentes`.
  - Totaliza receita de locação acumulada e segrega a frota em faixas etárias de permanência:
    - **0 a 29 dias:** Dentro da carência (Normal / Sem cobrança).
    - **30 a 59 dias:** Atenção inicial (1ª faixa faturável).
    - **60 a 89 dias:** Retenção prolongada (Alerta de giro lento).
    - **90+ dias:** Risco crítico de evasão/perda de casco patrimonial.

### 2.3. Logística Full-for-Empty e Pesagem Física Real
- **Arquivos:**
  - [logistica/models.py](file:///c:/Lucas/GasManagementApp/logistica/models.py) (`Entrega.peso_total_carregado`)
  - [logistica/views.py](file:///c:/Lucas/GasManagementApp/logistica/views.py) (Ação `romaneio_bilateral` em `EntregaViewSet`)
  - [logistica/templates/logistica/index.html](file:///c:/Lucas/GasManagementApp/logistica/templates/logistica/index.html) e [logistica/static/logistica/js/index.js](file:///c:/Lucas/GasManagementApp/logistica/static/logistica/js/index.js)
- **Cálculo Físico de Peso:**
  - Cilindros Entregues Cheios (`ENTREGA_CLIENTE` ou `SAIDA_ROTA`): soma da `tara_real_kg` com a `massa_gas_kg` do SKU correspondente.
  - Cilindros Recolhidos Vazios (`RECOLHA_CLIENTE`): soma apenas da `tara_real_kg` do casco despressurizado.
  - Disponibilidade de carga e percentual de lotação recalculados em tempo real (`capacidade_disponivel`, `percentual_lotacao`).
- **Endpoint e Interface do Romaneio Bilateral:**
  - `GET /logistica/api/entregas/{id}/romaneio-bilateral/`: retorna cilindros entregues, recolhidos, peso carregado e saldo de comodato do cliente.
  - `POST /logistica/api/entregas/{id}/romaneio-bilateral/`: rota unificada para acionamento dos serviços de bipagem (`acao='entregar'` ou `acao='recolher'`).

### 2.4. Dashboard Matador: "Radar de Comodato & Pátio"
- **Arquivos:**
  - [core/views.py](file:///c:/Lucas/GasManagementApp/core/views.py) (`DashboardStatsAPIView`)
  - [core/templates/core/home.html](file:///c:/Lucas/GasManagementApp/core/templates/core/home.html)
- **Componentes do Painel Executivo:**
  1. **4 Cards de KPIs em Destaque:**
     - **Frota Total de Cilindros** (Índice geral de ativos).
     - **Cilindros Sem Giro > 30d** (Volume de ativos estagnados em clientes).
     - **Receita de Locação Acumulada (R$)** (Potencial financeiro de faturamento de diárias).
     - **Alertas de Reteste INMETRO** (Cilindros vencidos ou vencendo nos próximos 30 dias).
  2. **Gráfico Donut ApexCharts:**
     - Distribuição da frota por status operacional: Cheios no Pátio, Em Comodato, Em Rota, Vazios em Triagem e Em Reteste.
  3. **Barras Analíticas de Permanência:**
     - Segmentação percentual e volumétrica das faixas de 0-29d, 30-59d, 60-89d e 90+d com indicador de risco financeiro de reposição de cascos.
  4. **DataTable Dinâmico de Cilindros Retidos:**
     - Colunas: Nº Série/QR, Gás Dedicado, Cliente em Posse, Data da Entrega, Dias Parado, Valor Acumulado e Badge de Criticidade.
     - Campo de busca instantânea no frontend por cliente, código QR ou tipo de gás.

---

## 3. Povoamento e Cenários de Teste no Banco de Dados

O script [populate_db.py](file:///c:/Lucas/GasManagementApp/populate_db.py) gerou dados realistas nos tenants de demonstração ("Oxigênio Brasília" e "Gases Goiás"), demonstrando a precisão do motor:

| Ativo | Tempo em Posse | Carência | Dias Faturáveis | Diária | Valor Calculado | Faixa |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Cilindro 2 (`O2-MED`) | **15 dias** | 30 dias | 0 dias | R$ 3,50 | R$ 0,00 | 0-29 dias (Isento) |
| Cilindro 3 (`N2-IND`) | **45 dias** | 30 dias | 15 dias | R$ 3,50 | R$ 52,50 | 30-59 dias (Alerta) |
| Cilindro 4 (`AR-IND`) | **95 dias** | 30 dias | 65 dias | R$ 3,50 | R$ 227,50 | 90+ dias (Crítico) |

- **Total Acumulado de Diárias por Tenant:** **R$ 280,00**
- **Risco Patrimonial de Reposição (3 cascos a R$ 1.800):** **R$ 5.400,00**

---

## 4. Testes Automatizados

- **Arquivo Criado:** [core/tests_sprint3.py](file:///c:/Lucas/GasManagementApp/core/tests_sprint3.py)
- **Cenários Cobertos:**
  1. `test_strangler_pattern_item_venda_com_sku_e_preco_congelado`: Criação de item com SKU e congelamento de preço.
  2. `test_strangler_pattern_item_venda_compatibilidade_legada`: Preservação de pedidos com produto legado.
  3. `test_motor_radar_comodato_faixas_e_locacao_acumulada`: Exatidão matemática do motor de comodato para 15, 45 e 95 dias.
  4. `test_logistica_peso_real_full_for_empty`: Pesagem de cheios com gás e recolha de vazios apenas tara.
  5. `test_drf_romaneio_bilateral_endpoint`: Operações de entrega e recolha via REST API.
  6. `test_dashboard_stats_api_view_kpis_e_radar`: Integridade dos 4 KPIs e payload do ApexCharts.

**Resultado da Suíte Completa da Aplicação (Sprint 1 + Sprint 2 + Sprint 3):**  
`Ran 16 tests in 10.213s - OK (100% de sucesso)`

---

## 5. Conclusão da Sprint 3

O MVP Comercial do GasManagementApp está totalmente operacional. Ele entrega a principal proposta de valor para distribuidoras de gases: estancar o prejuízo invisível de cilindros retidos sem giro em clientes e transformar a retenção em faturamento adicional através de contratos de comodato automatizados.
