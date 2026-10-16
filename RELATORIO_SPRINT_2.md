# Relatório Técnico - Sprint 2: Catálogo de Gases, Ativos Rastreados e Ledger Imutável com Camada de Serviços

**Projeto:** GasManagementApp (SaaS de Gestão de Distribuidoras de Gases Industriais e Medicinais)  
**Sprint:** 2 de 6  
**Status:** Concluído com Sucesso e 100% dos Testes Aprovados  
**Data de Execução:** Outubro/2026  
**Responsável Técnico:** Engenheiro de Software Sênior (Pair Programming Antigravity)  

---

## 1. Objetivo da Sprint

Resolver a principal particularidade de negócio do setor de gases: a separação conceitual e técnica entre o **insumo/gás consumível** e o **vaso de pressão/cilindro (ativo imobilizado)**.
Construir um catálogo desacoplado, rastreamento físico individual por QR Code e estamparia de ogiva, histórico de auditoria imutável (Ledger Append-Only) e uma camada de serviços estrita para alterações de estado com proteção de concorrência (`select_for_update` e `@transaction.atomic`).

---

## 2. Entregas Técnicas Executadas

### 2.1. Catálogo Desacoplado de Gases e Vasilhames
- **Arquivo Modificado:** [produtos/models.py](file:///c:/Lucas/GasManagementApp/produtos/models.py)
- **Modelos Implementados:**
  1. **`GasQuimico` (Tabela Global de Referência Técnica):**
     - Desvinculada de tenant (compartilhada entre todas as distribuidoras da plataforma).
     - Campos técnicos: `nome`, `sigla` (ex: `O2-MED`, `N2-IND`, `AR-IND`), `categoria` (MEDICINAL, INDUSTRIAL, ALIMENTICIO, ESPECIAL), `numero_onu` (ex: 1072), `classe_risco` (ex: 2.2), `cor_padrao_abnt` (ex: Verde Emblema ABNT NBR 12176), `exige_lote_anvisa` (booleano para controle regulatório farmacêutico).
  2. **`ModeloCilindro` (Engenharia do Casco por Tenant):**
     - Herdando de `TenantAwareModel`.
     - Especificações de segurança: `material` (Aço sem costura, Alumínio 6061-T6, Compósito de Carbono), `volume_hidraulico_litros`, `pressao_servico_bar`, `tara_nominal_kg`, `padrao_valvula_abnt` (ex: ABNT 218-1) e `periodicidade_reteste_anos` (5 anos pela ABNT NBR 12274 / 13243).
  3. **`SkuRecarga` (Unidade de Venda Comercial):**
     - Associação N:N parametrizada entre `GasQuimico` e `ModeloCilindro`.
     - Atributos comerciais e físicos: `quantidade_carga`, `unidade` (m³, kg, litros), `massa_gas_kg` (massa estequiométrica líquida do gás comprimido), `preco_base` e indicador `ativo`.

### 2.2. Ativo Físico Rastreado (`Cilindro`)
- **Campos de Rastreabilidade Individual:**
  - `codigo_qr` (com índice de banco para leitura ultrarrápida por coletores e câmeras).
  - `numero_serie_ogiva` (estamparia física do vaso).
  - `fabricante`, `ano_fabricacao`, `tara_real_kg` (aferida e gravada na tara do casco).
  - `data_ultimo_reteste` e `data_proximo_reteste`.
  - Property `reteste_vencido`: checagem dinâmica se o teste hidrostático obrigatório está expirado.
  - Constraints únicas combinadas por tenant: `unique_tenant_cilindro_qr` e `unique_tenant_cilindro_serie`.
- **Projeção de Estado Operacional:**
  - Status gerenciados: `CHEIO_DISPONIVEL`, `RESERVADO_ROTA`, `EM_POSSE_CLIENTE`, `VAZIO_TRIAGEM`, `EM_ENVASE`, `EM_RETESTE`, `BAIXADO`.
  - Ponteiros de localização: `cliente_posse_atual` e `posse_desde`.

### 2.3. Ledger Imutável de Movimentações (`MovimentacaoCilindro`)
- **Princípio:** O histórico físico de um cilindro nunca pode ser alterado ou deletado. Apenas novos eventos podem ser apensados (*Append-Only*).
- **Mecanismos de Bloqueio em Múltiplas Camadas:**
  - Sobrescrita de `save()`: se não for inserção (`not self._state.adding`), lança `PermissionError`.
  - Sobrescrita de `delete()`: lança `PermissionError`.
  - Custom Managers (`MovimentacaoLedgerManager` e `UnscopedLedgerManager`) com `QuerySet` que sobrescreve `update()` e `delete()`, disparando `PermissionError` caso alguém tente fazer update/delete via ORM em lote.
- **Campos de Auditoria:**
  - `cilindro`, `tipo` (10 tipos operacionais cobrindo todo o ciclo de vida).
  - `cliente`, `entrega`, `lote_envase`.
  - `data_hora_registro` (`auto_now_add=True`).
  - `ocorrido_em` (momento físico real do evento no cliente ou rota).
  - `usuario` (operador responsável).
  - `client_uuid` (para prevenção de duplicação em conexões instáveis / modo offline do app).

### 2.4. Camada de Serviços com Proteção de Concorrência
- **Arquivo Criado:** [produtos/services.py](file:///c:/Lucas/GasManagementApp/produtos/services.py)
- **Funções Atômicas:**
  - `registrar_entrega_cilindro(cilindro_id, cliente, entrega, usuario, ocorrido_em, client_uuid)`
  - `registrar_recolha_cilindro(cilindro_id, cliente, entrega, usuario, ocorrido_em, client_uuid, observacao)`
  - `enviar_para_reteste(cilindro_id, usuario, ocorrido_em, client_uuid, observacao)`
  - `retornar_de_reteste(cilindro_id, nova_data_reteste, usuario, ocorrido_em, client_uuid, laudo_numero)`
- **Garantias:**
  - Decoradas com `@transaction.atomic`.
  - Uso de `select_for_update()` no cilindro durante a mutação para eliminar *race conditions* de operadores bipando o mesmo cilindro simultaneamente.

---

## 3. Testes Automatizados

- **Arquivo:** [produtos/tests_ledger.py](file:///c:/Lucas/GasManagementApp/produtos/tests_ledger.py)
- **Cenários Cobertos:**
  1. `test_ledger_append_only_block_update`: validação de disparo de `PermissionError` em tentativas de alteração.
  2. `test_ledger_append_only_block_delete`: validação de disparo de `PermissionError` em tentativas de exclusão.
  3. `test_fluxo_entrega_e_recolha_com_projecao`: validação de mudança consistente do status do ativo e criação de registros no ledger.
  4. `test_ciclo_reteste_hidrostatico`: envio para inspeção, renovação quinquenal e retorno para o pátio.

**Resultado da Suíte Acumulada (Sprint 1 + Sprint 2):**  
`Ran 10 tests in 7.613s - OK (100% de sucesso)`

---

## 4. Conclusão da Sprint 2

O domínio de rastreabilidade de cilindros e controle de gases atingiu padrão industrial de alta disponibilidade e auditoria imutável. As distribuidoras agora possuem controle individualizado de cada casco, prevenindo perdas patrimoniais e cumprindo os requisitos normativos do INMETRO.
