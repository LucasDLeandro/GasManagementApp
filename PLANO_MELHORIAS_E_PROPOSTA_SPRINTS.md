# Plano de Modernização, Conformidade Regulatória e Proposta de Sprints
**GasManagementApp — Plataforma SaaS Multi-Tenant Especialista em Gestão de Gases Industriais e Medicinais**

---

## 1. Resumo Executivo e Batimento Técnico

Após a execução bem-sucedida das Sprints 1 a 4 (fundação multi-tenant fail-closed, catálogo de gases com ledger imutável, logística full-for-empty com radar de comodato, e rastreabilidade sanitária de envase), realizamos uma auditoria profunda do código-fonte e confrontamos os requisitos de negócio com a realidade operacional de distribuidores de gases comprimidos no Brasil.

O presente documento formaliza as **4 Decisões Estratégicas de Negócio**, os **Refinamentos Arquiteturais de Engenharia de Software**, o **Modelo Matemático Unificado de Estadia/Locação**, e o **Roadmap Detalhado de Sprints (5A.1 até 7)**.

---

## 2. As 4 Decisões Estratégicas de Negócio e Domínio

### 2.1. Regra de Franquia, Carência e Cobrança Diária (Demurrage)
- **Fonte da Verdade:** O cálculo de estadia e diárias nunca deve depender do campo pontual `posse_desde` do cilindro, pois este reflete apenas a última entrega física. A cobrança mensal e o histórico financeiro devem ser reconstituídos cronologicamente dia a dia pelo **Ledger Imutável** (`MovimentacaoCilindro`).
- **Ordem Determinística no Dia $D$:**
  1. **Passo 1 (Carência Individual do Cilindro):** No dia $D$, listam-se os cilindros sob posse do cliente. Se um cilindro está dentro dos seus `dias_carencia_giro` (ex.: entregue há 8 dias em um contrato com carência de 30 dias), o custo dele no dia $D$ é **R$ 0,00 (`ISENTO_CARENCIA`)**. Esse cilindro **não consome** a franquia do contrato.
  2. **Passo 2 (Aplicação da Franquia por FIFO):** Filtram-se os cilindros que já ultrapassaram a carência individual no dia $D$. Ordena-se essa fila pela data de entrega mais antiga (**FIFO** - *First In, First Out*, desempate por `id` do cilindro). Os primeiros $F$ cilindros (onde $F = \text{franquia\_cilindros\_isentos}$) recebem diária **R$ 0,00 (`ISENTO_FRANQUIA`)**.
  3. **Passo 3 (Cobrança do Excedente):** A partir do cilindro $F + 1$, aplica-se a `valor_diaria_excedente` contratada (**`COBRAVEL`**).
- **Conceito de Giro:** A carência é calculada por **intervalo de posse contínua**. Quando o cliente devolve um casco vazio e recebe um cheio (troca bilateral *Full-for-Empty*), o cilindro devolvido encerra seu ciclo e o novo cilindro inicia sua própria carência individual, premiando o giro rápido e penalizando o represamento de ativos parados.

### 2.2. Natureza Jurídica do Contrato e Terminologia de Interface
- **Modelagem Interna:** O modelo Django permanece nomeado como `ContratoComodato` para preservar a estabilidade das migrações e chaves estrangeiras legadas.
- **Camada de Apresentação e Faturas:** Na interface web, relatórios executivos, espelhos de medição e documentos enviados aos clientes, adota-se a terminologia:
  $$\text{“Taxa de Estadia / Locação de Cilindros Excedentes”}$$
- **Fundamentação Jurídica:** O ativo é cedido fisicamente sob regime de comodato (empréstimo gratuito para viabilizar o consumo do gás) durante o prazo de carência e dentro da franquia acordada. Ultrapassados esses limites, a permanência indevida do vasilhame converte-se em locação de bem móvel / taxa de demurrage por retenção de vasilhame, perfeitamente respaldada pelo Código Civil Brasileiro.

### 2.3. Posicionamento Estratégico de Mercado (Especialista vs. ERP)
- **Escopo Imediato (Sprints 5 e 6):** O sistema atua como **Software Especialista Operacional, Sanitário (ANVISA) e Medidor de Ativos**, funcionando como complemento aos ERPs fiscais tradicionais do cliente (ex.: Totvs, Sankhya, SAP, Bling, Tiny).
- **Emissão de Documentos Fiscais:** A emissão direta de NF-e (modelo 55), NFC-e (modelo 65) e MDF-e (modelo 58) permanece fora do escopo imediato. A plataforma foca em gerar:
  - Romaneio de Carga e Bilateral com pesos líquidos e brutos calculados;
  - Ficha de Emergência e Envelope de Transporte para Cargas Perigosas (ONU / ANTT);
  - Espelho de Medição de Estadia para faturamento mensal;
  - Dossiê Sanitário de Recall e Rastreabilidade para Farmacovigilância.

### 2.4. Marco Regulatório Sanitário ANVISA Atualizado
- **Substituição Normativa:** Todas as menções às antigas normas revogadas (RDC 69/2008 e RDC 67/2007) foram expurgadas do sistema.
- **Marco Vigente Adotado:**
  1. **RDC nº 658/2022:** Diretrizes Gerais de Boas Práticas de Fabricação de Medicamentos.
  2. **Instrução Normativa (IN) nº 129/2022:** Boas Práticas de Fabricação específicas para Gases Medicinais (armazenamento, envase, validação de pureza e rastreabilidade).
  3. **RDC nº 870/2024:** Registro e Notificação de Gases Medicinais perante a ANVISA.
- **Nomenclatura do Dossiê:** O módulo de exportação e auditoria passa a denominar-se oficialmente **“Dossiê de Rastreabilidade para Notivisa”**.

---

## 3. Diretrizes Técnicas e de Engenharia

### 3.1. Rastreabilidade no Ledger com Suporte a Cascos Vazios
- Na Sprint 5A.2, o modelo `MovimentacaoCilindro` receberá o campo `envase_cilindro = ForeignKey('EnvaseCilindro', null=True, blank=True, on_delete=PROTECT)`.
- **Regra de Negócio:**
  - Movimentações de **casco vazio** (`ENTRADA_ESTOQUE`, `RECOLHA_CLIENTE`, `RETESTE`, `BAIXA`) possuem `envase_cilindro = None`.
  - Movimentações que envolvem **cilindro cheio** (`ENVASE`, `ENTREGA_CLIENTE`) exigem `envase_cilindro` preenchido obrigatoriamente via validação na camada de serviços (`produtos/services.py`).

### 3.2. Unificação de Papéis (RBAC Multi-Tenant)
- Para manter compatibilidade total com telas legadas e viabilizar a transição suave para RBAC por tenant:
  - Adiciona-se o papel `RESPONSAVEL_TECNICO` às opções de `Membership.papel`.
  - Um **Context Processor** injeta o `membership` do tenant ativo em todos os templates Django, permitindo que a verificação de permissões use o papel local do usuário na empresa ativa.
  - A camada de API utiliza permissões DRF baseadas no `Membership` do tenant em contexto.

### 3.3. Motor de Cálculo Unificado (Radar de Estadia e Fatura Mensal)
- O cálculo do Radar de Comodato do Dashboard e a Fatura Mensal de Fechamento compartilham a **mesma função de cálculo diário no Ledger**, eliminando qualquer divergência entre a métrica visualizada no dia a dia e o valor fechado no final do mês.

---

## 4. Proposta de Sprints Fatiadas

| Sprint | Foco Principal | Complexidade | Duração Estimada |
| :--- | :--- | :---: | :---: |
| **Sprint 5A.1** | Higienização Regulatória, Blindagem Multi-tenant e Correção de Recall | Baixa / Média | 1 ciclo (Imediata) |
| **Sprint 5A.2** | Integridade de Rastreabilidade no Ledger e Migração Segura de FK | Média | 1 ciclo |
| **Sprint 5A.3** | Endpoints DRF de Gestão de Ativos, Envase e RBAC por Tenant | Média | 1 ciclo |
| **Sprint 5A.4** | Dossiê de Recall, Notivisa e Retenção Sanitária de Lotes | Média | 1 ciclo |
| **Sprint 5B** | Motor de Estadia/Locação Diário pelo Ledger e Faturamento Mensal | Alta | 2 ciclos |
| **Sprint 6** | Módulo de Pátio Mobile-First, Roteirização e Integração ERP | Alta | 2 ciclos |
| **Sprint 7** | Telemetria IoT de Tanques Criogênicos e Portal do Cliente Hospitalar | Alta | 2 ciclos |

---

### Sprint 5A.1: Higienização Regulatória, Blindagem Multi-tenant e Correção de Recall (EM EXECUÇÃO)
- **Objetivos:**
  1. Atualizar citações normativas para RDC nº 658/2022, IN nº 129/2022 e RDC nº 870/2024.
  2. Ajustar `LoteRecallAPIView` para filtrar cilindros com base em `is_envase_ativo`, corrigindo contagens de cilindros esvaziados ou reenvasados.
  3. Remover `except RuntimeError` de `reset_current_tenant` em `core/tenancy.py` e garantir teste de ciclo de vida seguro de contextvars.
  4. Disponibilizar endpoints REST de ativos e criar testes cross-tenant rigorosos garantindo `404 Not Found`.
  5. Ajustar documentação da Sprint 1 e refatorar `populate_db.py` para usar serviços sem burlar validações sanitárias.

### Sprint 5A.2: Integridade de Rastreabilidade no Ledger e Migração Segura de FK
- **Objetivos:**
  1. Adicionar `envase_cilindro = ForeignKey('EnvaseCilindro', null=True, blank=True)` em `MovimentacaoCilindro`.
  2. Criar migração de dados populando o histórico com o último envase válido de cada ciclo de enchimento.
  3. Atualizar `produtos/services.py` para exigir `envase_cilindro` em movimentações de cilindro cheio.

### Sprint 5A.3: Endpoints DRF de Gestão de Ativos, Envase e RBAC por Tenant
- **Objetivos:**
  1. Criar `CilindroViewSet` com filtros por QR code, status, reteste vencido e gás dedicado.
  2. Criar endpoint de execução de envase (`/produtos/api/envases/`) consumindo `registrar_envase_cilindro`.
  3. Criar papel `RESPONSAVEL_TECNICO` em `Membership` com campos de Conselho de Classe (ex.: CRF/CRQ).
  4. Implementar Context Processor e Permission Classes baseadas em `Membership`.

### Sprint 5A.4: Dossiê de Recall, Notivisa e Retenção Sanitária de Lotes
- **Objetivos:**
  1. Aprimorar a exportação do Dossiê para Notivisa com layout formatado para envio direto à vigilância sanitária.
  2. Adicionar status de bloqueio sanitário imediato no lote: ao disparar o recall, todos os cilindros no pátio vinculados ao lote têm seu status congelado contra expedição.
  3. Notificação automática e geração de termo de notificação aos hospitais afetados.

### Sprint 5B: Motor Diário de Estadia/Locação e Faturamento Mensal
- **Objetivos:**
  1. Reconstrução cronológica diária do estado de posse através das movimentações do Ledger.
  2. Implementação do algoritmo determinístico: Carência Individual $\rightarrow$ FIFO de Franquia $\rightarrow$ Diária Excedente.
  3. Modelo `FechamentoFaturaEstadia` e `ItemFaturaEstadia` com exportação de espelho de medição em PDF e CSV para o ERP fiscal.
  4. Emissão de termo de romaneio bilateral com assinatura digital do recebedor na entrega e recolha de cascos.

### Sprint 6: Módulo de Pátio Operacional Mobile-First, Roteirização e Integração ERP
- **Objetivos:**
  1. PWA mobile para operadores de pátio e motoristas: bipagem por câmera dos QR Codes na triagem, envase e entrega.
  2. Validação automática de tara e carga por veículo com cálculo dinâmico de centro de gravidade e ocupação.
  3. Webhooks e API REST pública para integração bidirecional com ERPs fiscais (clientes, pedidos de venda, dados fiscais de saída).

### Sprint 7: Telemetria IoT de Tanques Criogênicos e Portal do Cliente Hospitalar
- **Objetivos:**
  1. Integração com sensores de telemetria de nível e pressão de tanques criogênicos hospitalares (protocolos MQTT/HTTP).
  2. Algoritmo preditivo de consumo médio diário e alerta automático de abastecimento antes do esgotamento.
  3. Portal do Cliente Hospitalar com autoatendimento para consulta de laudos de pureza, certificados de reteste e espelho de ativos em comodato.
