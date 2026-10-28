# Guia dos Módulos do Baros

**O que é o Baros:** um SaaS B2B multi-tenant para empresas de **envase e distribuição de gases** industriais e medicinais. Ele controla o ciclo de vida de cada cilindro, o envase com rastreabilidade sanitária (ANVISA), vendas, entregas, frota, cobrança de estadia (comodato), financeiro, fiscal e um portal de autoatendimento para os clientes da distribuidora.

Este guia explica **o que cada módulo trata** e **qual é o seu fluxo**. Ele foi gerado a partir do código em 27/10/2026. Os nomes de modelos e funções são os reais, para facilitar a busca no código.

---

## Sumário

1. [Visão geral e como os módulos se conectam](#1-visão-geral)
2. [Core — plataforma, tenants e governança](#2-core)
3. [Accounts — usuários e acesso](#3-accounts)
4. [Clientes — cadastro, comodato e estadia](#4-clientes)
5. [Produtos — cilindros, envase, sanitário, patrimônio e granel](#5-produtos)
6. [Vendas — pedidos](#6-vendas)
7. [Logística — entregas, frota e rentabilidade](#7-logística)
8. [Financeiro — contábil, contas, cobrança e gestão](#8-financeiro)
9. [Fiscal — documentos fiscais e tributos](#9-fiscal)
10. [Faturamento — NF-e e cobrança (legado da Sprint 7)](#10-faturamento)
11. [Portal B2B — autoatendimento do cliente final](#11-portal-b2b)
12. [Analytics — inteligência comercial](#12-analytics)
13. [Backoffice Baros (`/baros-admin/`)](#13-backoffice-baros)
14. [Glossário](#14-glossário)

---

## 1. Visão geral

### 1.1 Os três "mundos" do sistema

| Mundo | Quem usa | Onde |
|---|---|---|
| **App da distribuidora** | Funcionários da empresa cliente do Baros (admin, gerente, pátio, motorista, vendedor, RT) | `/inicio/`, `/clientes/`, `/produtos/`, ... |
| **Portal B2B** | Clientes da distribuidora (hospitais, indústrias) | `/portal-b2b/` |
| **Backoffice Baros** | Vocês, donos do SaaS | `/baros-admin/` |

Também há páginas **públicas** sem login: rastreio de entrega (`/rastreio/<token>/`), passaporte sanitário do cilindro (`/v/cilindro/<id>/`) e link público de cobrança (`/faturamento/cobranca/<uuid>/`).

### 1.2 Módulos SaaS contratáveis

Cada empresa (tenant) liga ou desliga módulos. As dependências estão em `core/modulos.py`:

| Módulo SaaS | Requer | O que libera |
|---|---|---|
| `patrimonio` | — | Cilindros, lotes, rastreabilidade |
| `comercial` | patrimonio | Clientes, contratos de comodato |
| `vendas` | patrimonio | Pedidos |
| `envase` | patrimonio | Rampa de envase, lotes, CQ |
| `logistica` | vendas | Entregas, frota, rotas, rastreio |
| `fiscal` | vendas | NF-e, MDF-e, CT-e, apuração |
| `b2b` | comercial + vendas | Portal do cliente final |
| `financeiro` | — (recomenda comercial e vendas) | Contábil, contas, cobrança, DRE |
| `analytics` | — | Previsão de recompra, churn |

### 1.3 O fluxo de ponta a ponta

```
 Fornecedor de gás ──► [Produtos] Entrada a granel no tanque / recebimento de cilindro cheio
                                   │
          Cilindro vazio (VAZIO_TRIAGEM) ──► Inspeção pré-envase ──► Envase em lote (LoteEnvase + CQ/RT)
                                   │                                         │
                                   ▼                                         ▼
 [Vendas] Pedido ──► avaliação de crédito ──► Faturada ──► [Logística] Entrega/romaneio ──► validação de carga (ANTT)
                                   │                                         │
                                   │                         Motorista no App de Campo (PWA, offline)
                                   │                                         │
                                   ▼                                         ▼
                [Fiscal] NF-e de venda + remessa de comodato    Entrega do cheio / recolha do vazio (ledger)
                                   │                                         │
                                   ▼                                         ▼
       [Financeiro] Título a receber ◄── evento ──  [Clientes] Diárias de posse → Fatura de estadia mensal
                     │
                     ▼
       Cobrança (boleto/PIX) ─► régua de cobrança ─► baixa ─► conciliação bancária ─► Razão / DRE
```

### 1.4 Padrões transversais (valem para todos os módulos)

- **Multi-tenant fail-closed:** os modelos herdam de `TenantAwareModel` e o tenant ativo fica num contextvar (`core/tenancy.py`). Recurso de outra empresa sempre responde **404**.
- **RBAC por empresa:** o papel do usuário vem de `Membership.papel` (ADMIN, GERENTE, OPERADOR_PATIO, MOTORISTA, VENDEDOR, RESPONSAVEL_TECNICO).
- **Ledger imutável:** cilindros (`MovimentacaoCilindro`) e contabilidade (`LancamentoContabil`/`PartidaContabil`) nunca são editados, só **estornados**.
- **Eventos de domínio** (`core/eventos.py`): ações operacionais disparam eventos que `financeiro/contabilizacao.py` transforma em lançamentos contábeis. Se uma contabilização falha, vira uma `PendenciaContabilizacao`.
- **Auditoria** (`LogAuditoriaDados`, append-only), **idempotência** (`IdempotencyKey`) e **outbox de webhooks**.
- **Dinheiro sempre em `Decimal`**, nunca em float (`core/money.py`, com teste próprio).

---

## 2. Core

**O que trata:** a fundação da plataforma. Empresas (tenants), filiais, papéis, perfil regulatório, integrações (webhooks e ERP), auditoria, jobs, LGPD, governança SaaS e o dashboard inicial.

### Entidades principais
| Modelo | Para quê |
|---|---|
| `Tenant` | A empresa cliente do Baros: plano, status da assinatura, flags de módulos, cotas |
| `Filial` | Unidades da empresa (matriz criada automaticamente), com CNPJ e código IBGE |
| `Membership` | Liga um usuário a um tenant com um papel |
| `ResponsavelTecnico` | Farmacêutico ou químico responsável (CRF/CRQ, vigência) |
| `PerfilRegulatorioTenant` | Modo regulatório (industrial / medicinal), RT vigente |
| `WebhookEndpoint` / `WebhookDeliveryLog` | Integração de saída por webhooks com HMAC (PENDENTE → PROCESSANDO → SUCESSO/FALHA) |
| `PlanoSaaS` / `FaturaSaaS` | Planos e mensalidades cobradas por vocês |
| `AcessoSuporte` | Acesso de suporte (break-glass) de um superusuário à conta de um tenant |
| `LogAuditoriaDados` / `LogAuditoriaSaaS` | Trilhas de auditoria imutáveis |
| `JobExecucao`, `IdempotencyKey` | Controle de tarefas assíncronas e de requisições repetidas |
| `SolicitacaoTitularLGPD` | Pedidos de titulares (acesso, eliminação, revogação) |

### Fluxos
1. **Onboarding de empresa** (`core/services/onboarding.py`): cria o tenant, a filial matriz, o plano, os módulos e o usuário administrador.
2. **Assinatura** (`core/services/assinatura.py`):
   `TRIAL → ATIVO | SUSPENSO | CANCELADO` · `ATIVO → SUSPENSO | CANCELADO` · `SUSPENSO → ATIVO | CANCELADO` · `CANCELADO → ATIVO` (só superusuário, com motivo). Toda transição gera log.
3. **Cotas** (`core/services/cotas.py`): bloqueiam a criação acima do limite do plano (ex.: número de cilindros).
4. **Troca de empresa ativa:** o seletor na topbar muda o tenant da sessão; o middleware valida o `Membership`.
5. **Webhooks:** o evento grava `PENDENTE` na mesma transação e o envio acontece após o commit (ou via `python manage.py processar_webhooks_outbox`).
6. **Busca global (Ctrl+K):** `/api/busca-global/` procura cilindros, lotes, clientes e veículos.
7. **Serviços de operação:** observabilidade, backup/PITR, rollout por piloto (`rollout_service`), criptografia e rotação de chaves, LGPD, carga de dados legados (`carga_legado_service`).

### Telas
`/inicio/` (painel operacional, que muda conforme os módulos ativos), `/integracoes/`, `/perfil-regulatorio/`.

---

## 3. Accounts

**O que trata:** usuários, login, primeiro acesso, perfil pessoal e dados de RH.

| Modelo | Para quê |
|---|---|
| `User` | Usuário customizado do Django |
| `UserProfile` | Dados pessoais |
| `DadosTrabalhistas` | Dados de RH do funcionário |

### Fluxo
1. O admin cadastra o funcionário (`/accounts/` → "Pessoal") e define o papel via `Membership`.
2. **Primeiro login:** troca de senha obrigatória (`first_login_password.html`).
3. **Autoatendimento:** "Meu perfil" e troca de senha (⚠️ hoje com bug; ver o plano).

---

## 4. Clientes

**O que trata:** cadastro de clientes (matriz e filiais), contratos de comodato, o **motor de estadia** (cobrança por dia de posse do cilindro), fechamento mensal, extravio e usuários B2B.

| Modelo | Para quê |
|---|---|
| `Cliente` | PF/PJ, IE, endereço geocodificado, matriz/filial, bloqueios |
| `ContratoComodato` | Regras de carência, franquia e diária excedente ("Taxa de Estadia / Locação") |
| `FranquiaModeloContrato` | Franquia específica por modelo de cilindro |
| `DiaCilindro` | Uma linha por cilindro × dia de posse, com classe: `ISENTO_CARENCIA`, `ISENTO_FRANQUIA`, `ISENTO_RESERVA`, `NAO_COBRAVEL_PROPRIEDADE`, `COBRAVEL` |
| `FechamentoFaturaEstadia` / `ItemFaturaEstadia` | Fatura mensal de estadia |
| `AjusteCompetenciaEstadia` | Correção de meses já fechados (compensa no mês seguinte) |
| `ExtravioCilindroRegistro` | Cilindro dado como perdido, com cobrança de reposição |
| `UsuarioClienteB2B` | Acesso do cliente ao portal (COMPRADOR, FINANCEIRO, LEITOR) |

### Fluxo do motor de estadia (`clientes/services.py`)
1. **Reconstrução diária** (`reconstruir_posse_cliente_no_dia`): a partir do ledger `MovimentacaoCilindro`, descobre quais cilindros estavam com o cliente no dia D.
2. **Classificação do dia** (`calcular_diarias_cliente_data`):
   - **Passo 1, carência individual:** cilindro dentro de `dias_carencia_giro` → R$ 0 (`ISENTO_CARENCIA`), e não consome franquia.
   - **Passo 2, franquia FIFO:** dos que passaram da carência, os F mais antigos → R$ 0 (`ISENTO_FRANQUIA`).
   - **Passo 3, excedente:** do F+1 em diante → `valor_diaria_excedente` (`COBRAVEL`).
3. **Radar de comodato** (`calcular_radar_comodato_tenant`): mostra no dashboard quanto está sendo acumulado. Usa o mesmo cálculo da fatura.
4. **Fechamento mensal** (`fechar_fatura_estadia_competencia`): gera a fatura e dispara o evento contábil.
5. **Espelho de medição** em PDF/CSV e exportação para ERP.
6. **Correções retroativas** (`verificar_e_gerar_ajustes_competencias_fechadas`): movimentações lançadas depois do fechamento geram um ajuste no mês seguinte.
7. **Extravio** (`identificar_cilindros_limite_extravio` → `declarar_cilindro_extraviado`): após `dias_limite_extravio` (180 dias por padrão), GERENTE/ADMIN declara o extravio, a diária para de contar e a reposição é cobrada.

### Tela
`/clientes/`: lista com métricas, cadastro em etapas, contratos, radar de comodato. **É a tela de referência do redesign.**

---

## 5. Produtos

O maior módulo de domínio. Tem quatro blocos: **catálogo**, **ciclo do cilindro**, **sanitário (ANVISA)**, **patrimônio** e **granel/custos**.

### 5.1 Catálogo
| Modelo | Para quê |
|---|---|
| `GasQuimico` | O gás (O₂, N₂, CO₂, Ar...), medicinal ou industrial |
| `ClasseRiscoGas` | Classe ONU/ANTT para transporte de carga perigosa |
| `ModeloCilindro` | Capacidade, tara, pressão |
| `SkuRecarga` | O que se vende: gás × modelo de cilindro, com preço |
| `Produto` | **Legado**, a ser substituído por `SkuRecarga` |

### 5.2 Ciclo de vida do cilindro
`Cilindro.status` é uma máquina de estados (`TRANSIÇÕES_PERMITIDAS_CILINDRO` em `produtos/services.py`):

```
VAZIO_TRIAGEM ──► EM_ENVASE ──► CHEIO_DISPONIVEL ──► RESERVADO_ROTA ──► EM_POSSE_CLIENTE
      ▲                                                                         │
      └──────────────────────────── recolha do vazio ◄──────────────────────────┘
VAZIO_TRIAGEM ──► EM_REQUALIFICACAO / EM_RETESTE ──► (retorno) VAZIO_TRIAGEM
qualquer ──► BAIXADO (terminal, só reabre por estorno) · EXTRAVIADO
```

Todas as mudanças passam por serviços que gravam no **ledger** `MovimentacaoCilindro`. Os tipos de movimentação são: ENTRADA_ESTOQUE, ENVASE, RESERVA_ROTA, SAIDA_ROTA, ENTREGA_CLIENTE, RECOLHA_CLIENTE, ENVIO/RETORNO_RETESTE, RECLASSIFICACAO, BAIXA, EXTRAVIADO, ESTORNO, RECEBIMENTO_FORNECEDOR...

| Ação | Serviço |
|---|---|
| Inspeção antes de envasar | `InspecaoPreEnvase`, `validar_cilindro_para_rampa` |
| Envase (unitário ou em batelada na rampa) | `registrar_envase_cilindro`, `registrar_envase_batelada` |
| Distribuidora sem rampa: recebe cheio do fornecedor | `receber_cilindro_cheio_fornecedor`, `receber_cilindros_fornecedor_batelada` |
| Alocar na rota / entregar / recolher | `alocar_cilindro_rota`, `registrar_entrega_cilindro`, `registrar_recolha_cilindro` |
| Corrigir um lançamento | `estornar_movimentacao_ledger` |
| Sincronizar movimentações feitas offline | `sincronizar_movimentacoes_offline` |

### 5.3 Sanitário (ANVISA: RDC 658/2022, IN 129/2022, RDC 870/2024)
- **Lote de envase** (`LoteEnvase`): pureza, laudo de CQ, RT que libera. A RT aprova a qualidade via `atualizar_qualidade_lote`.
- **Bloqueio sanitário** (`acionar_bloqueio_sanitario` / `liberar_bloqueio_sanitario`): congela o cilindro contra expedição, com auditoria (`AuditoriaBloqueioSanitario`).
- **Recall** (`RecallCampanha`): `ABERTO → HOMOLOGADO_RT → EM_NOTIFICACAO → CONCLUIDO` (ou `CANCELADO`). Lista os clientes e cilindros afetados (`ItemRecallCliente`) e gera o **Dossiê de Rastreabilidade para Notivisa** em PDF.
- **Reclassificação de gás** (`ReclassificacaoCilindro`): trocar o gás dedicado de um cilindro exige homologação da RT.
- **Passaporte de conformidade:** página pública acessada pelo QR code do cilindro.
- **Etiquetas:** patrimonial (60×40 mm) e de colarinho do lote.

### 5.4 Patrimônio (Sprints 8A/8B)
- `FabricanteCilindro`, `ClasseAtivo` (com contas contábeis), `LoteAquisicaoCilindros`, `AtivoImobilizado`.
- **Reteste hidrostático:** `enviar_cilindros_para_reteste` (`EnvioReteste`) → `registrar_retorno_reteste` (`HistoricoRetesteHidrostatico`, que verifica expansão permanente e variação de tara) → `retificar_reteste`.
- **Baixa patrimonial** (`BaixaPatrimonial`): inutilização técnica, extravio, venda ou sinistro, com estorno.
- **Indenização** (`TabelaIndenizacaoCilindro`, `calcular_indenizacao`): valor cobrado do cliente que perde o cilindro.
- **Cilindros de propriedade do cliente** (`cliente_proprietario`): não geram diária (`NAO_COBRAVEL_PROPRIEDADE`).

### 5.5 Granel, estoque e custo (Sprint 8C)
- `TanqueCriogenico` → `EntradaGasGranel` (compra, NF × pesagem, com tolerância) → `MedicaoTanque` → `MovimentoEstoqueGas` (ENTRADA, CONSUMO_ENVASE, PERDA_EVAPORACAO, PERDA_PURGA, AJUSTE, TRANSFERENCIA) → `FechamentoPeriodoTanque` (apura o boil-off).
- **Custo do lote** (`fechar_lote_envase` → `CustoLoteEnvase`): gás consumido + energia da rampa (`CustoEnergiaRampa`).
- **Estoque de produto acabado** (`MovimentoEstoqueProduto`): a venda faturada baixa o estoque e calcula o CPV (`baixar_estoque_venda_faturada`).

### Telas
`/produtos/` (frota de cilindros com drawer 360°, entradas de fornecedor, catálogo, rampa `?aba=rampa`), `/produtos/recall-anvisa/`, etiquetas, passaporte público. **Patrimônio, tanques e granel ainda não têm tela.**

---

## 6. Vendas

**O que trata:** pedidos de venda de recarga de gás.

| Modelo | Para quê |
|---|---|
| `Venda` / `ItemVenda` | Pedido e itens (por `SkuRecarga`) |
| `LiberacaoBloqueio` | Liberação manual de pedido bloqueado por crédito |
| `AlertaComercial` | Risco de churn, retenção, inadimplência |

### Fluxo
```
Pendente ──(crédito reprovado)──► BLOQUEADO_FINANCEIRO ──(liberação c/ motivo)──► Pendente
Pendente ──► Faturada ──► Em Separação ──► Em Rota ──► Entregue ──► Finalizada
                                                         └──► Cancelada
```
> ⚠️ Este é o fluxo **pretendido**. Hoje o endpoint `alterar_status` (`vendas/views.py`) aceita qualquer status, sem validar a transição nem o papel do usuário. Na prática, dá para levar um pedido de `BLOQUEADO_FINANCEIRO` direto para `Faturada`. A correção está no plano (tarefa 0.3.2).
1. **Criação** (`vendas/serializers.py`): calcula o total e chama `financeiro.services.credito_service.avaliar_credito`. Se reprovar, o pedido fica `BLOQUEADO_FINANCEIRO`. Existe uma regra de segurança assistencial: gás medicinal para hospital tem tratamento especial.
2. **Liberação** (`vendas/services/liberacao_service.py`): só ADMIN ou GERENTE, com log (`LiberacaoBloqueio`).
3. **Faturamento:** baixa o estoque de produto (CPV) e dispara o evento contábil `venda_faturada`. A NF-e é emitida pelo módulo Fiscal.
4. **Entrega:** a venda entra numa `Entrega` (Logística) e acompanha o status dela.

### Tela
`/vendas/`: dashboard, fila ativa, concluídas, canceladas, nova venda e recibo.

---

## 7. Logística

**O que trata:** tudo o que se move. Entregas e romaneio, App de Campo do motorista, rastreio, validação de carga perigosa, frota (veículos, documentos, FIPE), combustível, manutenção, seguros e sinistros, e rentabilidade/TCO.

### 7.1 Entregas e expedição
| Modelo | Para quê |
|---|---|
| `Entrega` | Romaneio: veículo, motorista, rota. `Agendada → Em Produção → Em Rota → Concluída` (ou `Cancelada`) |
| `ParadaEntrega` | Cada cliente na rota: `PENDENTE → A_CAMINHO → CHEGOU → ENTREGUE` (ou `FALHA`) |
| `ValidacaoCarga` + `ConfiguracaoValidacaoCarga` | Conferência de carga: `Registrada → Pendente de Aprovação → Aprovada / Rejeitada` |
| `RegraIncompatibilidadeCarga` / `LiberacaoCarga` | Regras ANTT/NBR 14619 de gases incompatíveis (BLOQUEAR ou AVISAR) e liberação justificada |
| `ComprovanteEntrega` | Assinatura digital do recebedor + foto |
| `CoordenadaRastreamento` / `TrajetoEntrega` / `TokenRastreio` | GPS e rastreio público |
| `Motorista`, `AlocacaoMotoristaVeiculo`, `CapacidadeVeiculoTipoCilindro` | Equipe e capacidade de carga |

**Fluxo da entrega:**
1. O gerente monta a entrega com vendas e cilindros (`alocar_cilindro_rota` → `RESERVADO_ROTA`).
2. `validar_carga` verifica incompatibilidade, peso e capacidade. Se bloquear, só sai com `liberar_carga_bloqueada`.
3. `otimizar_ordem_paradas` define a ordem das paradas (API externa com fallback 2-opt + haversine).
4. `despachar_entrega_para_rota` → `Em Rota`. Gera o token de rastreio e avisa o cliente, se ele consentiu.
5. **App de Campo (PWA, `/campo/`)**: o motorista bipa os QR codes, entrega o cheio, recolhe o vazio e coleta a assinatura. Funciona **offline** (IndexedDB) e sincroniza depois (`/api/movimentacoes/sync-offline/`). Ele também envia GPS em lote (`sincronizar_lote_gps`).
6. Cada parada atualiza os ETAs (`recalcular_etas_subsequentes`). O cliente acompanha em `/rastreio/<token>/`.
7. Conclusão → custos da viagem → rentabilidade.

### 7.2 Frota
- `Veiculo` (status `Ativo / Em Manutenção / Sinistrado / Inativo`), fotos, documentos (CRLV, RNTRC, CIPP/CIV...), `DocumentoObrigatorioVeiculo`, histórico FIPE (`atualizar_fipe`), leituras de odômetro.
- **Combustível:** `Abastecimento` → `processar_abastecimento` valida odômetro e tanque, calcula consumo e compara com o preço de referência da ANP (`importar_precos_anp`), gerando alertas antifraude.
- **Manutenção:** `PlanoManutencao` (preventiva por km/tempo) → `OrdemServico` (`Aberta → Orçada → Aprovada → Em Execução → Concluída`, tipos Preventiva/Corretiva/Preditiva/Recall), `OSItem`, `OSAnexo`, `ChecklistModelo` / `ChecklistExecucao` (checklist que pode gerar OS), `Fornecedor` (oficinas).
- **Seguros e sinistros:** `ApoliceSeguro` (+ coberturas e veículos) e `Sinistro`, que segue `Rascunho → Registrado → Comunicado à Seguradora → Em Análise → Em Vistoria → Aprovado/Negado → Indenizado → Encerrado`, com linha do tempo, anexos, itens de carga (ajusta o estoque) e OS vinculada.

### 7.3 Rentabilidade
`CustoViagem` (pedágio, diária, comissão...), `TabelaFrete`/`TabelaFreteInterno`, `ConfiguracaoRentabilidade`. Serviços: `consolidar_custo_viagem`, `obter_tco_frota`, `calcular_margem_contribuicao_veiculo`, alertas de baixa ocupação e de averbação.

### Telas
`/logistica/` (abas: Quadro de Entregas, Frota, Rotas/Fretes, Combustível, Manutenção, Seguros & Sinistros, Rentabilidade, Histórico), `/campo/` (PWA), `/rastreio/<token>/` (público).

---

## 8. Financeiro

O maior módulo (50 modelos). Tem seis blocos.

### 8.1 Base contábil (Sprint 9A)
- `PlanoContas` (árvore sintética/analítica, mapeada nas 12 linhas da DRE), `CentroCusto`, `PeriodoContabil` (`ABERTO ↔ FECHADO`, `fechar_periodo` / `reabrir_periodo`).
- **Razão:** `LancamentoContabil` + `PartidaContabil` (débito = crédito, dimensões: centro de custo, veículo, gás, cliente, entrega). `razao.lancar` / `razao.estornar`; nunca se edita.
- **Contabilização automática** (`financeiro/contabilizacao.py`): venda faturada, fatura de estadia, entrada granel, lote envasado, perda de gás, compra de imobilizado, reteste, baixa patrimonial, extravio, caução. Falhas viram `PendenciaContabilizacao` (aba Pendências) e podem ser reprocessadas.
- `ImportacaoSaldoAbertura`: simular → confirmar → estornar.
- `SaldoMensalConta`: snapshots mensais para relatórios rápidos.

### 8.2 Contas a pagar e a receber (Sprint 9B)
- `TituloFinanceiro` (RECEBER/PAGAR): `RASCUNHO → EM_APROVACAO → ABERTO → PARCIAL → LIQUIDADO` (ou `CANCELADO`), com retenções (ISS, IRRF, PIS, COFINS, CSLL, INSS), rateio por centro de custo e condição de pagamento.
- `ParcelaFinanceira`: `PENDENTE → PARCIAL → PAGA` (ou `RENEGOCIADA`, `CANCELADA`, `EM_PROTESTO`).
- **Aprovação por alçada** (`AlcadaAprovacao`, `aprovar_titulo`), **baixa** (`baixar_parcela`, `baixar_em_lote`, `estornar_baixa`), **juros e multa** (`calcular_encargos`), **renegociação**.
- `ContaFinanceira` (conta corrente, investimento, **caixa de rota do motorista**, **cartão combustível**) com `MovimentoConta` e transferências.

### 8.3 Operação de campo antifraude (Sprint 9C)
- **Despesa de campo** (`PreLancamentoDespesaCampo`): o motorista lança abastecimento, pedágio etc. → `PENDENTE_CONFERENCIA → APROVADO / REJEITADO → CONSOLIDADO`.
- **Fatura de posto/cartão** (`FaturaConsolidadaPosto`): importar CSV → conciliar com os pré-lançamentos → aprovar.
- **Caixa de rota** (`FechamentoCaixaRota`): saldo esperado → **contagem cega** pelo motorista → conferência → `CONFERIDO / DIVERGENTE → FECHADO`, com `QuebraCaixa` (sobra/falta) e `ChequeRecebido`.

### 8.4 Banco e cobrança (Sprint 10A)
- **Conciliação bancária:** `importar_extrato` (OFX/CNAB) → `ExtratoBancarioItem` (`NAO_CONCILIADO → SUGERIDO → CONCILIADO / IGNORADO`) com regras automáticas (`RegraConciliacao`), conciliação manual, divisão de item e lançamento direto.
- **Cobrança registrada:** `emitir_cobranca_parcela` (boleto/PIX via adaptador do PSP), retorno por webhook (`processar_webhook_cobranca`).
- **Régua de cobrança:** `ReguaCobranca` (etapas antes e depois do vencimento) → `executar_regua_cobranca` respeita a janela comercial e o consentimento LGPD (`ConsentimentoContato`) → `EnvioCobranca`.

### 8.5 Fechamento e gestão contábil (Sprint 10B)
Depreciação mensal (`DepreciacaoMensal`, CPC 23, `RevisaoVidaUtil`), **DRE por competência** (`dre_service`), **orçamento anual** (`Orcamento` RASCUNHO → APROVADO, importável por CSV), **PDD** por faixa de atraso, **lançamentos manuais** com aprovação (`LancamentoManualPendente`), provisão de IRPJ/CSLL (`ParametroTributarioLucro`), exportações (balancete, razão, DRE em CSV).

### 8.6 Gestão do dono e crédito (Sprints 10C/11C)
- **Fluxo de caixa:** realizado + **projeção de 90 dias em cenários** (`projetar_fluxo_caixa_cenarios`) usando o perfil de pagamento de cada cliente (`PerfilPagamentoCliente`), recorrências (`RecorrenciaFinanceira`) e `AlertaCaixa`.
- **Crédito:** `ParametroCredito`, `LimiteCreditoCliente`, `avaliar_credito` (exposição total = títulos em aberto + pedidos + estadia) → bloqueio da venda. `PromessaPagamento`: `ATIVA → CUMPRIDA / QUEBRADA / CANCELADA`, atualizada diariamente.

### Telas
`/financeiro/` (abas: Contas & Saldos, Receber, Pagar, Fila de Aprovação, Despesas de Campo, Faturas de Posto, Caixas de Rota, Plano de Contas, Balancete, Razão, Saldo de Abertura, Pendências, Períodos, Apoio), `/financeiro/conciliacao/`, detalhe do fechamento de caixa. **Sem tela:** régua de cobrança, depreciação, DRE, orçamento, PDD, lançamentos manuais, fluxo de caixa projetado, crédito e promessas, recorrências.

---

## 9. Fiscal

**O que trata:** emissão e gestão de documentos fiscais específicos do setor de gases (Sprints 11A/11B).

| Modelo | Para quê |
|---|---|
| `ConfiguracaoFiscalFilial` | Emissor por filial: certificado A1 (cifrado), série, ambiente |
| `RegraTributaria` + `RegraTributariaTributo` | Motor tributário: regra escolhida pela mais específica (UF, NCM, operação...), com aprovação |
| `DocumentoFiscal` / `Item` / `ItemDocumentoTributo` / `Evento` | NF-e/CT-e/MDF-e: `RASCUNHO → VALIDANDO → ENVIADO → AUTORIZADO` (ou `REJEITADO`, `CANCELADO`, `INUTILIZADO`, `CONTINGENCIA`) |
| `TarefaInutilizacaoNumeracao` | Lacunas de numeração a inutilizar |
| `MovimentoComodatoFiscal` | Remessa e retorno de cilindro em comodato (NF-e própria) |
| `ConfiguracaoMDFe` | Manifesto de transporte |
| `DocumentoFiscalEntrada` | XML de compra importado → título a pagar |
| `ApuracaoImposto` | Apuração gerencial: `ABERTO → FECHADO → GUIA_GERADA` (gera título a pagar) |
| `OrdemRecargaTerceiro` | Envase do cilindro do próprio cliente: `RECEBIDO → EM_ENVASE → ENVASADO → DEVOLVIDO → FATURADO` |

### Fluxos
1. **NF-e de venda:** `validar_pre_emissao` (inclui o bloqueio de gás medicinal sem laudo de CQ liberado) → `calcular_tributos_item` → `reservar_proximo_numero` → `emitir_nfe_venda` → evento → DANFE/XML. Depois: `cancelar_nfe` (dentro do prazo), `carta_correcao_nfe`, `processar_inutilizacao`.
2. **Comodato fiscal:** a entrega do cilindro gera a NF-e de remessa (`gerar_nfe_remessa_comodato`) e a recolha gera a de retorno. `relatorio_divergencias_comodato` cruza o fiscal com o físico.
3. **Locação/estadia:** `gerar_fatura_locacao` (PIS/COFINS de locação).
4. **Transporte:** `emitir_cte_transporte` (quando presta serviço de transporte), `montar_e_emitir_mdfe` → `encerrar_mdfe_entrega`, alerta de MDF-e aberto.
5. **Entrada:** `importar_xml_nfe_compra` → `DocumentoFiscalEntrada` → título a pagar.
6. **Apuração:** `calcular_apuracao_imposto` → `fechar_apuracao_e_gerar_guia`.
7. **Contador:** `gerar_lote_xmls_contador`. Alerta de certificado vencendo.

### Tela
`/fiscal/`: hoje só mostra a lista de NF-e e o cancelamento.

---

## 10. Faturamento

**O que trata:** a primeira versão do hub fiscal e de cobrança (Sprint 7), que hoje está **sobreposta** pelos módulos Fiscal e Financeiro.

| Modelo | Para quê |
|---|---|
| `ConfiguracaoFiscalTenant` | Certificado e ambiente por tenant (o Fiscal faz isso por filial) |
| `NotaFiscal` | NF-e simples (o Fiscal tem o `DocumentoFiscal`) |
| `FaturaCobranca` | Boleto/PIX: `ABERTA → PAGA / VENCIDA / CANCELADA`, com link público |

### Fluxo
Solicitar emissão (`/faturamento/nfe/solicitar-emissao/`) → task Celery `emitir_nfe_task` (payload Focus NFe) → webhook com HMAC atualiza o status. Webhook do gateway de pagamento → `FaturaCobranca` paga. `MovimentoConta.baixa` ainda aponta para `FaturaCobranca`.

> **Decisão pendente:** unificar com o Fiscal (`DocumentoFiscal`) e com o Financeiro (`emitir_cobranca_parcela`) e aposentar este app. Ver o plano.

---

## 11. Portal B2B

**O que trata:** o autoatendimento dos clientes da distribuidora, com isolamento forte (sessão separada `b2b_sessionid`).

| Modelo | Para quê |
|---|---|
| `ConviteB2B` | Convite por e-mail para criar acesso |
| `LogAcessoB2B` / `DownloadDocumentoB2B` | Auditoria de acesso e de downloads |
| `SolicitacaoReposicao` | Pedido "1 clique": `CRIADA` ou `BLOQUEADA_CREDITO` |
| `NotificacaoB2B` | Avisos de reteste vencendo, estadia crescente e boleto a vencer |

### Fluxo
1. A distribuidora cria um `UsuarioClienteB2B` (papel COMPRADOR, FINANCEIRO ou LEITOR) e envia o **convite**.
2. O cliente aceita o convite → define a senha (com regras de complexidade) → aceita o **termo** → **MFA**. Há bloqueio por tentativas.
3. No **dashboard**, vê os cilindros em seu poder, a estadia acumulada, as faturas e boletos e os laudos de pureza (download por **URL assinada de uso único**, `gerar_laudo_quimico_pdf`).
4. **Reposição em 1 clique** → `avaliar_credito` → vira uma `Venda` ou fica bloqueada.
5. A distribuidora pode revogar o acesso (`acesso_revogado_em`).

**Regra de ouro:** os ViewSets do portal são próprios e filtram sempre por `request.user.usuarioclienteb2b.cliente`. Os do sistema administrativo nunca são reaproveitados.

---

## 12. Analytics

**O que trata:** inteligência comercial e preditiva (Sprints 10, 10C, 12C).

| Serviço | O que faz |
|---|---|
| `previsao_recompra_service` | Estima quando cada cliente deve recomprar cada gás (mediana + MAD, sem outliers) |
| `kaplan_meier` | Probabilidade de um cilindro **não retornar** |
| `alertas_service.gerar_alertas_demand_churn` | Cria `AlertaOportunidadeComercial`: RECOMPRA_ATRASADA, CHURN_RISCO, CILINDRO_NAO_RETORNA, ESTADIA_CRESCENTE |
| `funil_service` | Métricas do funil `NOVO → EM_CONTATO → CONVERTIDO / DESCARTADO` (com período de espera após descarte) |
| `indicadores_service` | Indicadores executivos do dono |
| `backtest_service` | Mede a precisão das previsões |

### Fluxo
Job diário gera os alertas → o vendedor trabalha o funil em `/analytics/api/funil-alertas/` → conversão em venda. **A tela existe, mas não está no menu.**

---

## 13. Backoffice Baros

**O que trata:** a operação do SaaS por vocês. Fica em `core/views_baros_admin.py`, `core/urls_baros_admin.py` e `templates/baros_admin/`.

### Fluxo
1. Login com usuário superusuário + **MFA TOTP**, sessão de 30 minutos e restrição por IP (`BAROS_ADMIN_ALLOWED_IPS`).
2. **Dashboard:** MRR, empresas por status, inadimplência, uso de cotas.
3. **Empresas:** onboarding → ligar/desligar módulos (respeitando as dependências) → transicionar a assinatura.
4. **Planos e faturas SaaS:** criar plano, gerar fatura, marcar como paga/vencida/cancelada.
5. **Suporte (break-glass):** iniciar acesso com motivo (máximo de 30 minutos, banner vermelho no app do cliente, tudo registrado) → encerrar.

Hoje só os passos 2 e a lista de empresas têm tela. Ver o plano, Fase 1.

---

## 14. Glossário

| Termo | Significado |
|---|---|
| **Tenant** | Empresa cliente do Baros (a distribuidora) |
| **Comodato** | Empréstimo gratuito do cilindro ao cliente, dentro da carência e da franquia |
| **Estadia / Locação / Demurrage** | Cobrança por dia de cilindro retido além da carência e da franquia |
| **Carência de giro** | Dias grátis de cada cilindro desde a entrega |
| **Franquia** | Quantos cilindros o cliente pode reter sem pagar diária |
| **Full-for-empty** | Troca do vazio pelo cheio na entrega |
| **Ledger** | Registro imutável de movimentações (só se estorna) |
| **RT** | Responsável Técnico (farmacêutico/químico) que libera lotes e homologa recall |
| **Reteste hidrostático** | Requalificação periódica obrigatória do cilindro |
| **Boil-off** | Perda natural de gás criogênico por evaporação no tanque |
| **Break-glass** | Acesso emergencial de suporte, auditado e com tempo limitado |
| **Notivisa** | Sistema da ANVISA para notificações sanitárias |
| **PDD** | Provisão para Devedores Duvidosos |
| **TCO** | Custo total de propriedade do veículo |
