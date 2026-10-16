# ADR 001: Motor Determinístico de Cálculo Diário de Estadia/Locação de Cilindros e Demurrage pelo Ledger Imutável

**Status:** Aprovado  
**Data:** 15 de Outubro de 2026  
**Contexto de Negócio:** Gestão Comercial, Comodato, Estadia e Faturamento de Ativos Excedentes  
**Decisores:** Arquiteto de Software, Especialista em Operações de Gases Comprimidos, Engenheiro de Dados  

---

## 1. Contexto e Problema

Na distribuição de gases industriais e medicinais, os cilindros de alta pressão (vasos de pressão certificados pelo INMETRO) representam o ativo físico de maior valor patrimonial da distribuidora. Esses ativos são cedidos aos clientes (hospitais, indústrias, clínicas) sob regime contratual de comodato gratuito durante o período estimado de consumo do gás (prazo de giro/carência).

Entretanto, dois problemas graves ocorriam nos modelos computacionais simplificados:
1. **Perda de Histórico por Dependência de Estado Pontual:** Utilizar apenas a coluna `Cilindro.posse_desde` inviabilizava fechar o faturamento de meses anteriores caso o cilindro tivesse sido recolhido ou movimentado após o fechamento do período.
2. **Conflito entre Carência Individual e Franquia Global:** Se um hospital tem franquia de 5 cilindros isentos e recebe 3 cilindros hoje (que já possuem 30 dias de carência contratual individual), abater esses cilindros recém-chegados da franquia global esgotaria a franquia injustamente, penalizando cilindros mais antigos que de fato precisavam da cobertura.
3. **Divergência entre Dashboard e Fatura Final:** Telas de acompanhamento em tempo real (Radar) e rotinas de faturamento financeiro calculavam métricas por caminhos lógicos diferentes, gerando atrito e contestação de faturas hospitalares.

---

## 2. Decisão Arquitetural

Decidimos instituir um **Motor de Cálculo Diário Unificado**, executado sobre o **Ledger Imutável** (`MovimentacaoCilindro`), sem qualquer dependência do campo estático `posse_desde`.

### 2.1. Princípio da Reconstituição Cronológica Dia a Dia
Para qualquer competência ou intervalo de datas $[D_{inicio}, D_{fim}]$, o estado de posse de cada cilindro em cada dia calendário $D$ é reconstituído a partir da linha do tempo imutável de eventos:
$$\text{Status}(C, D) = \text{último evento no Ledger do cilindro } C \text{ até o final do dia } D$$

### 2.2. Algoritmo Determinístico de Cobrança Diária no Dia $D$
Para cada cliente com contrato ativo no dia $D$:

1. **Definição da Idade de Posse:**
   Para cada cilindro $C$ em posse do cliente no dia $D$:
   $$\text{idade}(C, D) = D - \text{data\_entrega}(C)$$
   *(onde $\text{data\_entrega}$ é a data do evento `ENTREGA_CLIENTE` do ciclo contínuo atual).*

2. **Passo 1 — Filtro de Carência Individual de Giro:**
   Se $\text{idade}(C, D) \le \text{dias\_carencia\_giro}$ do contrato:
   $$\text{Status Diário} = \text{ISENTO\_CARENCIA} \quad \implies \quad \text{Diária} = \text{R\$\,0,00}$$
   *Cilindros em carência **NÃO consomem** a franquia do contrato.*

3. **Passo 2 — Aplicação da Franquia por Agrupamento de Modelo e FIFO:**
   Entre os cilindros que já ultrapassaram a carência ($\text{idade} > \text{dias\_carencia\_giro}$):
   - Ordenam-se por ordem cronológica de entrega mais antiga (**FIFO** — *First In, First Out*), com desempate estrito por `Cilindro.id`.
   - Os primeiros $F$ cilindros (onde $F = \text{franquia\_cilindros\_isentos}$ contratada para a categoria/modelo):
     $$\text{Status Diário} = \text{ISENTO\_FRANQUIA} \quad \implies \quad \text{Diária} = \text{R\$\,0,00}$$
   *(Suporte opcional a LIFO configurável por cláusula contratual específica).*

4. **Passo 3 — Cobrança de Estadia do Excedente:**
   Do cilindro $F + 1$ em diante na fila ordenada:
   $$\text{Status Diário} = \text{COBRAVEL} \quad \implies \quad \text{Diária} = \text{valor\_diaria\_excedente}$$

### 2.3. Fechamento por Snapshot Imutável e Ajustes Posteriores
- No último dia de cada mês (competência fiscal), o sistema consolida o somatório das diárias cobráveis e grava uma fatura com status `FECHADA`, acompanhada do **Espelho de Medição Diária** em anexo imutável (PDF/CSV).
- Caso ocorra registro retroativo autorizado de recolha ou substituição física após a fatura ter sido fechada, o sistema **NÃO altera** a fatura fechada; o ajuste a crédito ou débito é lançado automaticamente como **Item de Ajuste / Compensação** na competência subsequente.

---

## 3. Consequências

### Positivas
- **Auditabilidade Absoluta:** O cliente pode consultar o espelho diário e auditar exatamente quais cilindros estavam no hospital em cada dia, quais foram isentos por carência, quais entraram na franquia e quais geraram diária.
- **Unificação Lógica:** O Radar de Estadia no Dashboard Operacional e o Módulo de Faturamento utilizam exatamente o mesmo motor matemático, eliminando qualquer discrepância.
- **Segurança Jurídica:** A cobrança deixa de ser tratada como aluguel genérico e passa a caracterizar juridicamente taxa de demurrage / estadia de bem móvel excedente à franquia de comodato.

### Limitações e Mitigações
- **Volume de Processamento:** Calcular dia a dia via Ledger para dezenas de milhares de cilindros pode consumir I/O excessivo se feito em queries ingênuas.
- **Mitigação:** Índices compostos cobrindo `(tenant, cilindro, tipo, ocorrido_em)` e agregações vetoriais em banco via SQL/Window Functions na Sprint 5B.
