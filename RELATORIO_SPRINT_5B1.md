# Relatório de Conclusão — Sprint 5B.1
**Plano Consolidado de Engenharia v5 — Motor Diário de Estadia/Locação e Casos de Ouro (Demurrage Determinístico)**

---

## 1. Resumo Executivo

A **Sprint 5B.1** implementou o núcleo matemático e a modelagem do **Motor Determinístico de Estadia e Demurrage de Cilindros**, conforme estabelecido na **Seção 3.1**, no **Apêndice A** do Plano Consolidado v5 e no [ADR-001](file:///c:/Lucas/GasManagementApp/docs/adr/ADR-001-motor-estadia-demurrage.md).

Esta entrega elimina definitivamente as distorções comerciais e litígios hospitalares decorrentes de cálculos pontuais baseados em campos estáticos (como `posse_desde`), substituindo-os por uma **tabela derivada imutável e auditável (`DiaCilindro`)**, reconstituída dia a dia **estritamente a partir do Ledger imutável de movimentações (`MovimentacaoCilindro`)** no fuso horário oficial `America/Sao_Paulo`.

### Principais Entregas:
1. **Contrato Versionado e Franquia por Grupo de Modelo:**
   - `ContratoComodato`: Evoluído para versionamento por data de vigência (`vigencia_inicio`, `vigencia_fim`), critério de desempate de franquia (`criterio_franquia`: `FIFO` ou `LIFO`), agrupamento de filiais (`agrupar_franquia_filiais=True`) e limite de retenção antes de extravio (`dias_limite_extravio=180`).
   - `FranquiaModeloContrato`: Parametrização granular por modelo/capacidade física de cilindro (`T-50`, `PP`, etc.), definindo `franquia_cilindros_isentos`, `dias_carencia_giro`, `taxa_diaria` e `valor_reposicao_extravio` específicos.
   - Atributos ortogonais em `Cilindro`: Suporte a `is_reserva_tecnica` e distinção patrimonial em `propriedade` (`DISTRIBUIDORA`, `PROPRIO`, `CLIENTE`, `PARCEIRO`, `TERCEIRO_INTERCAMBIO`).
2. **Tabela Derivada `DiaCilindro` e Algoritmo Determinístico (Seção 3.1):**
   - Criação da tabela `DiaCilindro` com restrição de unicidade por `(tenant, cliente, cilindro, data_referencia)`.
   - Motor determinístico de 5 passos com fonte da verdade no Ledger imutável (sem depender de `posse_desde`):
     - **Passo 1 (Posse no Dia D):** Reconstrução do estado às 23:59:59. Entrega e recolha no mesmo dia resulta em 0 diárias.
     - **Passo 2 (Elegibilidade):** Cascos do cliente/terceiro (`NAO_COBRAVEL_PROPRIEDADE`) e reservas técnicas (`ISENTO_RESERVA`) recebem R$ 0,00 e não disputam a franquia.
     - **Passo 3 (Carência Individual):** `idade = D - data_entrega` (dia da entrega = 0). Enquanto `idade < carencia_dias`, classificado como `ISENTO_CARENCIA` (R$ 0,00) e **NUNCA consome** a franquia do modelo.
     - **Passo 4 (Franquia por Modelo):** Cilindros com `idade >= carencia_dias` são agrupados por modelo e ordenados por `criterio_franquia` (`FIFO` ou `LIFO`), desempate por `cilindro.id ASC`. Os primeiros $F$ recebem `ISENTO_FRANQUIA` (R$ 0,00).
     - **Passo 5 (Excedente Cobrável):** Cilindros restantes recebem `COBRAVEL` com `taxa_diaria` vigente com precisão `Decimal`.
3. **Recálculo Incremental Automático:**
   - Disparo incremental automático a partir da data de qualquer entrega ou recolha inserida via `registrar_entrega_cilindro` e `registrar_recolha_cilindro`.
4. **Unificação do Radar do Dashboard:**
   - `calcular_radar_comodato_tenant` e a view do Dashboard unificados para consumir a inteligência do novo motor, exibindo a estimativa da competência aberta ("Taxa de Estadia / Locação de Cilindros Excedentes").
5. **Suíte Oficial dos 10 Casos de Ouro e Prova de Equivalência:**
   - 11 novos testes automatizados cobrindo os 10 Casos de Ouro do Apêndice A e a prova matemática de que o recálculo incremental produz resultado idêntico ao recálculo do zero.

---

## 2. Detalhamento Arquitetural e Modelagem

### 2.1. Modelos de Contrato e Franquia (`clientes/models.py`)

```mermaid
erDiagram
    Cliente ||--o{ ContratoComodato : "possui contratos vigentes"
    ContratoComodato ||--o{ FranquiaModeloContrato : "parametriza por modelo"
    ModeloCilindro ||--o{ FranquiaModeloContrato : "modelo de casco"
    Cliente ||--o{ DiaCilindro : "diárias consolidadas"
    Cilindro ||--o{ DiaCilindro : "ativo auditado"
```

1. **`ContratoComodato`:**
   - `vigencia_inicio` (`DateField`, default `timezone.now`): Marco inicial da vigência contratual.
   - `vigencia_fim` (`DateField`, null=True, blank=True): Término da vigência (ou `None` para contratos por prazo indeterminado).
   - `criterio_franquia` (`CharField`, choices `FIFO`/`LIFO`, default `'FIFO'`): Ordem de prioridade para concessão da isenção de franquia entre cascos retidos.
   - `agrupar_franquia_filiais` (`BooleanField`, default `True`): Facilita rateio entre matriz e filiais hospitalares.
   - `dias_limite_extravio` (`PositiveIntegerField`, default `180`): Prazo limite antes de disparar processo de indenização por perda do casco.
   - Campos legados preservados como fallback seguro caso o modelo específico não possua `FranquiaModeloContrato`.
2. **`FranquiaModeloContrato`:**
   - Vínculo direto `(contrato, modelo)` com `UniqueConstraint` por tenant.
   - `franquia_cilindros_isentos`: Quantidade de cascos deste modelo isentos após a carência.
   - `dias_carencia_giro`: Prazo individual de consumo/giro do modelo (ex.: 30d para T-50, 15d para PP).
   - `taxa_diaria`: Valor diário de demurrage com precisão `Decimal('0.00')`.
   - `valor_reposicao_extravio`: Custo de reposição do casco em caso de não devolução.
3. **`DiaCilindro`:**
   - Colunas: `tenant`, `cliente`, `cilindro`, `data_referencia`, `data_entrega`, `idade_posse_dias`, `classe_cobranca`, `valor_diaria`, `contrato_versao`, `algoritmo_versao`.
   - `UniqueConstraint`: `(tenant, cliente, cilindro, data_referencia)` garantindo idempotência e ausência de duplicidade.
   - Classes de Cobrança:
     * `ISENTO_CARENCIA`: Dentro do prazo individual de giro.
     * `ISENTO_FRANQUIA`: Coberto pela cota contratual do modelo.
     * `ISENTO_RESERVA`: Casco destinado a contingência/reserva técnica.
     * `NAO_COBRAVEL_PROPRIEDADE`: Cilindro de terceiro, cliente ou intercâmbio.
     * `COBRAVEL`: Estadia excedente com taxa diária aplicada.

---

## 3. Matriz dos 10 Casos de Ouro (Apêndice A)

A suíte implementada em [clientes/tests/test_motor_estadia_casos_ouro.py](file:///c:/Lucas/GasManagementApp/clientes/tests/test_motor_estadia_casos_ouro.py) valida as 10 regras de ouro com 100% de precisão matemática `Decimal`:

| Caso | Cenário / Regra | Resultado Esperado | Status |
| :---: | :--- | :--- | :---: |
| **01** | **Carência Individual sem Consumo de Franquia** | Cilindros recém-entregues em carência individual não consomem a franquia do modelo, permitindo que cascos antigos excedentes usufruam da cota isenta. | **APROVADO** |
| **02** | **Franquia por Modelo (T-50 vs PP)** | Parâmetros de franquia, carência e taxas são independentes entre modelos físicos (ex.: T-50 taxa R$ 5,00 vs PP taxa R$ 2,50). | **APROVADO** |
| **03** | **Critério de Franquia: FIFO vs LIFO** | Sob `FIFO`, o casco entregue há mais tempo é isento primeiro; sob `LIFO`, o casco mais recente fora da carência é isento primeiro. | **APROVADO** |
| **04** | **Cascos de Terceiros e Reserva Técnica** | Cascos de propriedade do cliente (`CLIENTE`), de parceiro (`TERCEIRO_INTERCAMBIO`) e Reserva Técnica (`is_reserva_tecnica=True`) geram R$ 0,00 e não consomem a franquia. | **APROVADO** |
| **05** | **Entrega e Recolha no Mesmo Dia Calendário** | Cilindro entregue às 09:00 e recolhido às 15:00 não consta em posse às 23:59:59 (0 diárias de permanência geradas). | **APROVADO** |
| **06** | **Equivalência: Incremental vs. Completo do Zero** | O recálculo incremental executado a cada nova movimentação produz registros 100% idênticos ao recálculo integral a partir do zero. | **APROVADO** |
| **07** | **Fechamento de Competência Mensal (Stub 5B.2)** | Somatório de diárias cobráveis de uma competência fechada bate exatamente com o total dos itens de medição. | **APROVADO** |
| **08** | **Extravio após `dias_limite_extravio`** | Cilindro retido além de 180 dias é sinalizado e habilita cobrança de reposição (`valor_reposicao_extravio`). | **APROVADO** |
| **09** | **Compensação / Ajuste Retroativo (Stub 5B.2)** | Recolha lançada com data retroativa ajusta o histórico da competência recalculada, excluindo diárias indevidas. | **APROVADO** |
| **10** | **Precisão Matemática com `Decimal`** | 31 dias calculados com taxa R$ 3,33 somam exatamente `Decimal('103.23')`, sem imprecisões de ponto flutuante IEEE-754. | **APROVADO** |
| **Bonus**| **Integração Radar do Dashboard** | Reconciliação do motor de comodato com o Dashboard Operacional, provendo estimativa da competência aberta. | **APROVADO** |

---

## 4. Resultados da Execução de Testes Automatizados

O comando `python manage.py test` foi executado cobrindo a totalidade das aplicações do sistema:

```
Ran 96 tests in 74.977s

OK
Destroying test database for alias 'default'...
Found 96 test(s).
System check identified no issues (0 silenced).
```

- **Total de Testes:** 96 testes automatizados.
- **Taxa de Sucesso:** 100% (0 erros, 0 falhas).
- **Cobertura Integrada:**
  - Sprints 1 a 4 (Catálogo, Vendas, Rastreabilidade, Logística, Recall Farmacêutico).
  - Sprints 5A.0 a 5A.4 (Isolamento Cross-Tenant, Imutabilidade do Ledger, RBAC RT, Bloqueio Sanitário).
  - Sprint 5B.1 (Modelagem de Contratos, Franquia por Modelo, Motor Determinístico `DiaCilindro`, Casos de Ouro).

---

## 5. Matriz de Arquivos Modificados e Criados

| Arquivo | Ação | Finalidade |
| :--- | :---: | :--- |
| [clientes/models.py](file:///c:/Lucas/GasManagementApp/clientes/models.py) | Modificado | Evolução de `ContratoComodato` (vigências, FIFO/LIFO, extravio) e criação de `FranquiaModeloContrato` e `DiaCilindro`. |
| [produtos/models.py](file:///c:/Lucas/GasManagementApp/produtos/models.py) | Modificado | Inclusão de `is_reserva_tecnica`, escolhas `DISTRIBUIDORA`/`PARCEIRO` em `Cilindro.propriedade` e `EXTRAVIADO` no Ledger. |
| [clientes/services.py](file:///c:/Lucas/GasManagementApp/clientes/services.py) | Reescrito | Implementação do motor determinístico pelo Ledger, recálculo incremental e unificação do Radar. |
| [produtos/services.py](file:///c:/Lucas/GasManagementApp/produtos/services.py) | Modificado | Gatilho automático de recálculo incremental em `registrar_entrega_cilindro` e `registrar_recolha_cilindro`. |
| [core/views.py](file:///c:/Lucas/GasManagementApp/core/views.py) | Modificado | Enriquecimento da API do Dashboard com rótulo e valor de estimativa de estadia de cilindros excedentes. |
| [clientes/tests/test_motor_estadia_casos_ouro.py](file:///c:/Lucas/GasManagementApp/clientes/tests/test_motor_estadia_casos_ouro.py) | Criado | Suíte dos 10 Casos de Ouro do Apêndice A e teste de propriedade de equivalência incremental vs do zero. |
| [clientes/migrations/0005_alter_contratocomodato_options_and_more.py](file:///c:/Lucas/GasManagementApp/clientes/migrations/0005_alter_contratocomodato_options_and_more.py) | Criado | Migração de banco para evolução de contratos, franquias por modelo e tabela `DiaCilindro`. |
| [produtos/migrations/0008_remove_movimentacaocilindro_check_movimentacao_envase_coerente_and_more.py](file:///c:/Lucas/GasManagementApp/produtos/migrations/0008_remove_movimentacaocilindro_check_movimentacao_envase_coerente_and_more.py) | Criado | Migração de banco para reserva técnica, propriedade e suporte a extravio no Ledger. |
