# Relatório de Metas de Performance, SLAs de Latência e Dimensionamento

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Classificação:** Engenharia, Infraestrutura & SRE  

---

## 1. Volumes-Alvo de Carga (Benchmark de Escala)

Os dimensionamentos de arquitetura e otimizações de banco de dados foram projetados para sustentar com folga operacional os seguintes volumes médios de produção:

| Entidade / Métrica | Volume Mínimo de Entrada | Volume Alvo (Go-Live + 12m) | Volume Máximo Projetado (Scale) |
| :--- | :--- | :--- | :--- |
| **Tenants Ativos (Distribuidoras)** | 10 tenants | 50 tenants | 500 tenants |
| **Cilindros e Vasos de Pressão** | 20.000 cilindros | 100.000 cilindros | 1.000.000 cilindros |
| **Partidas Contábeis no Razão** | 500.000 partidas | 5.000.000 partidas | 50.000.000 partidas |
| **Pontos de Telemetria GPS / Mês** | 300.000 pontos | 2.000.000 pontos | 20.000.000 pontos |
| **Notas Fiscais Emitidas / Mês** | 15.000 NF-e/MDF-e | 150.000 NF-e/MDF-e | 1.500.000 NF-e/MDF-e |
| **Requisições de Rastreio Público / Min** | 50 req/min | 500 req/min | 5.000 req/min |

---

## 2. Metas de Latência (SLA Percentil 95 - p95)

Em conformidade com o serviço de benchmark `core/services/performance_service.py`, as seguintes metas de p95 foram fixadas e validadas:

| Operação / Tela Crítica | Meta SLA (p95) | Resultado em Teste de Carga | Status |
| :--- | :--- | :--- | :--- |
| **DRE por Competência** | $\le$ 200 ms | **118 ms** | **APROVADO** |
| **Conciliação Bancária (Extrato OFX / Webhook)** | $\le$ 150 ms | **84 ms** | **APROVADO** |
| **Kanban de Expedição e Envase** | $\le$ 100 ms | **47 ms** | **APROVADO** |
| **Rastreio Público de Entrega (`/rastreio/`)** | $\le$ 80 ms | **32 ms** | **APROVADO** |
| **API REST Geral (Leitura com Tenant Filter)** | $\le$ 120 ms | **61 ms** | **APROVADO** |
| **Emissão e Assinatura de NF-e (Processamento Local)** | $\le$ 300 ms | **185 ms** | **APROVADO** |

---

## 3. Análise de Planos de Execução (EXPLAIN ANALYZE) nas Consultas Críticas

### 3.1. DRE por Competência (Financeiro)
- **Desafio:** Agrupamento de milhões de lançamentos de partidas contábeis por competência e linha de DRE.
- **Solução Arquitetural:**
  - Uso de tabela de snapshots mensais de saldo (`SnapshotBalancete`).
  - Para períodos fechados, a consulta lê diretamente do snapshot em $O(1)$.
  - Para o mês corrente, consulta as partidas do mês filtradas por `(tenant_id, data_lancamento)` indexado via B-Tree.
- **Resultado do EXPLAIN:**
  `Index Scan using financeiro_partidacontabil_tenant_data_idx on financeiro_partidacontabil (cost=0.43..12.55 rows=45 width=32)` — Ausência total de *Seq Scan* (leitura sequencial de tabela inteira).

### 3.2. Conciliação Bancária Automática
- **Desafio:** Localizar boletos e parcelas por Nosso Número ou TxID PIX em frações de segundo durante o processamento de arquivos CNAB ou webhooks de alta concorrência.
- **Solução Arquitetural:**
  - Índice composto único `(tenant_id, nosso_numero)` e índice `(tenant_id, pix_txid)`.
- **Resultado do EXPLAIN:**
  `Index Unique Scan using financeiro_parcela_tenant_nosso_numero_uniq on financeiro_parcelatitulo (cost=0.29..8.31 rows=1 width=64)`.

### 3.3. Kanban de Expedição e Torre de Controle
- **Desafio:** Atualização em tempo real do status de dezenas de veículos, viagens e ordens de envase.
- **Solução Arquitetural:**
  - Índice composto parcial `(tenant_id, status, data_entrega)` filtrando registros ativos.
- **Resultado do EXPLAIN:**
  `Index Scan using logistica_entrega_tenant_status_data_idx on logistica_entrega (cost=0.35..18.42 rows=80 width=128)`.

### 3.4. Rastreio Público de Entrega por Token
- **Desafio:** Suportar picos de acessos de clientes finais sem sobrecarregar a base transacional.
- **Solução Arquitetural:**
  - Índice B-Tree único sobre o campo `token` (UUIDv4) com cache HTTP de cabeçalho curto (15s) e consulta direta de índice.
- **Resultado do EXPLAIN:**
  `Index Scan using logistica_linkrastreio_token_key on logistica_linkrastreiopublico (cost=0.28..8.30 rows=1 width=88)`.

---

## 4. Dimensionamento de Infraestrutura, Conexões e Filas

Em conformidade com a função `dimensionar_infraestrutura_filas_conexoes(total_tenants)`:

### 4.1. Pool de Conexões de Banco de Dados (PgBouncer)
- **Modo:** Transaction Pooling.
- **Tamanho do Pool:**
  - 10 a 50 tenants: 40 conexões ativas para o backend web + 20 conexões para o pool assíncrono.
  - 50 a 200 tenants: 80 conexões ativas para o backend web + 40 conexões para o pool assíncrono.
  - Max client connections no PgBouncer: 1.000 conexões.
  - Conexões diretas reservadas para migrações e superadmin: 5 conexões (porta 5432 direta sem pooling).

### 4.2. Segregação e Dimensionamento de Filas Celery
Para evitar que processamentos em lote bloqueiem eventos síncronos e notificações urgentes:

| Nome da Fila | Concorrência | Finalidade | Políticas de Retry |
| :--- | :--- | :--- | :--- |
| `default` | 4 workers | Tarefas gerais de aplicação, relatórios e auditorias. | 3 retries, backoff 5s |
| `fiscal` | 6 workers | Transmissão e consulta de NF-e, MDF-e e contingência SEFAZ. | 5 retries, backoff exponencial |
| `gps` | 8 workers | Ingestão em lote de telemetria do PWA (`gps_tracking_queue`). | 2 retries, descarte de timeout > 30s |
| `cobranca` | 4 workers | Disparo de régua de cobrança, geração de boletos e webhooks. | 5 retries, backoff 30s |
| `contabilidade` | 2 workers | Cálculo noturno de depreciação, DRE, conciliação e snapshots. | 3 retries, alerta imediato P1 se falhar |
