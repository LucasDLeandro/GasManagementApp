# Relatório de Conclusão - Sprint 5A.4
**Plano Consolidado de Engenharia v5 — Rastreabilidade Medicinal ANVISA, Recall Operacional e Qualidade Sanitária**

---

## 1. Resumo Executivo

A **Sprint 5A.4** implementou a blindagem sanitária de cilindros e a separação arquitetural estrita do motor de Recall farmacêutico exigido pela **RDC nº 658/2022**, **IN nº 129/2022**, **RDC nº 870/2024**, **RDC nº 887/2024 (ANVISA)** e **Resolução CFF nº 731/2022**.

A evolução resolveu um dos desafios mais críticos de rastreabilidade física industrial: **a eliminação de falsos positivos na contenção ativa** quando cilindros históricos são devolvidos vazios, purgados e reenvasados com novos lotes, mantendo a notificação compulsória para hospitais que foram expostos ao lote reprovado no passado.

### Principais Entregas:
1. **Flag Ortogonal `bloqueio_sanitario`:** Independente do status operacional (`CHEIO_DISPONIVEL`, `EM_POSSE_CLIENTE`, `VAZIO_TRIAGEM`), bloqueia envase, alocação de rota e entrega a novos clientes, mas **permite irrestritamente a recolha/retorno de cascos vazios do cliente para a fábrica**.
2. **Regras de Reteste Vencido:** Bloqueia expedição e envase, mas **nunca impede o retorno/recolha** do ativo do hospital para requalificação.
3. **Qualidade do Lote (`status_qualidade`):** Controle de qualidade em três estágios (`QUARENTENA`, `APROVADO`, `REPROVADO`). A reprovação de um lote pelo Responsável Técnico (RT) aciona **automaticamente o bloqueio sanitário** de todos os cilindros com carga física ativa daquele lote.
4. **Separação Arquitetural do Recall:**
   - **Contenção Operacional (Risco Ativo):** Cilindros que contêm carga física ativa do lote alvo (localização física exata: cliente, trânsito ou pátio, com ação imediata indicada).
   - **Dossiê de Exposição Histórica:** Registro auditável de todas as entregas passadas no Ledger vinculadas àquele lote, incluindo cilindros consumidos e reenvasados posteriormente (garantia de zero falso positivo na recolha física e 100% de conformidade de notificação aos hospitais).
5. **Campanhas Formais de Recall (`RecallCampanha` e `ItemRecallCliente`):** Abertura de dossiê, texto de notificação padrão, homologação formal exclusiva do RT e exportação em CSV estruturado em duas seções oficiais.

---

## 2. Matriz de Conformidade e Mudanças de Modelagem

### 2.1 Modelos e Migrations (`produtos/models.py`)
- **`LoteEnvase.status_qualidade`:** Choices `[('QUARENTENA', 'Em Quarentena / Análise'), ('APROVADO', 'Aprovado pelo CQ/RT'), ('REPROVADO', 'Reprovado pelo CQ/RT')]`, com default `'APROVADO'` para preservar compatibilidade de dados e testes anteriores.
- **`AuditoriaBloqueioSanitario`:** Modelo imutável (*append-only*) vinculado a `Cilindro`, gravando `acao` (`BLOQUEIO`/`DESBLOQUEIO`), `motivo`, usuário responsável e snapshots do RT (`rt_nome_snapshot`, `rt_registro_snapshot`). Bloqueia `.update()` e `.delete()`.
- **`RecallCampanha`:** Controle da campanha de recall (`ABERTO`, `HOMOLOGADO_RT`, `EM_NOTIFICACAO`, `CONCLUIDO`, `CANCELADO`), com vínculo de lote, homologação pelo RT e restrição por tenant.
- **`ItemRecallCliente`:** Detalhamento por cliente e cilindro, discriminando `tipo_exposicao` (`CONTENCAO_ATIVA` vs. `EXPOSICAO_PASSADA`) e status de notificação/recolhimento.
- **Migration:** Aplicada com sucesso `produtos.0007_loteenvase_status_qualidade_and_more`.

### 2.2 Camada de Serviços (`produtos/services.py`)
| Serviço | Regra Sanitária / Validação Aplicada |
| :--- | :--- |
| `acionar_bloqueio_sanitario` | Privativo do `RESPONSAVEL_TECNICO` (ou superuser). Trava concorrente de linha (`select_for_update`). Grava auditoria imutável. |
| `liberar_bloqueio_sanitario` | Privativo do `RESPONSAVEL_TECNICO`. Exige justificativa técnica de liberação. Grava auditoria imutável. |
| `atualizar_qualidade_lote` | Privativo do RT. Se alterado para `REPROVADO`, dispara automaticamente o bloqueio sanitário de todos os cilindros com carga ativa do lote. |
| `alocar_cilindro_rota` | Bloqueia se `bloqueio_sanitario=True`, `reteste_vencido=True` ou `lote.status_qualidade != 'APROVADO'`. |
| `registrar_entrega_cilindro` | Bloqueia se `bloqueio_sanitario=True`, `reteste_vencido=True` ou `lote.status_qualidade != 'APROVADO'`. |
| `registrar_recolha_cilindro` | **Permite irrestritamente** a recolha mesmo com `bloqueio_sanitario=True` ou `reteste_vencido=True`. |
| `abrir_campanha_recall` | Popula automaticamente `ItemRecallCliente` divididos em Contenção Ativa e Exposição Passada. |
| `homologar_campanha_recall` | Homologação formal do RT antes do disparo das notificações aos clientes. |
| `obter_dossie_recall_lote` | Gera estrutura bi-partida: Contenção Operacional vs. Exposição Histórica. |

---

## 3. Critério de Aceite Definitivo (Definition of Done)

Foi implementado e aprovado com sucesso o teste automatizado em `produtos/tests_sprint5a4.py` demonstrando:

- **Exposição Histórica:** O Hospital X consta formalmente no dossiê como tendo recebido o Lote A, com nota fiscal, data da entrega e operador (satisfazendo a auditoria da ANVISA e notificação farmacêutica).
- **Contenção Operacional:** O Cilindro C1 **não** aparece como risco ativo de recolha, pois seu conteúdo físico atual é o Lote B (eliminando recall indevido e pânico no Hospital Y). Zero falso positivo matematicamente comprovado.

---

## 4. Resultados da Suíte de Testes Automatizados

A suíte completa de testes foi executada e aprovada com **100% de sucesso**:

```text
Ran 85 tests in 59.131s

OK
Destroying test database for alias 'default'...
Found 85 test(s).
System check identified no issues (0 silenced).
```

### Detalhamento dos Testes da Sprint 5A.4:
- `test_bloqueio_sanitario_impede_envase_rota_e_entrega`: Aprovado.
- `test_bloqueio_sanitario_e_reteste_vencido_permitem_recolha_de_casco`: Aprovado.
- `test_bloqueio_sanitario_exclusivo_responsavel_tecnico`: Aprovado.
- `test_endpoint_bloqueio_sanitario_drf`: Aprovado.
- `test_lote_em_quarentena_impede_reserva_e_entrega`: Aprovado.
- `test_reprovar_lote_aciona_bloqueio_sanitario_automatico_nos_cilindros`: Aprovado.
- `test_criterio_aceite_zero_falso_positivo_reenvase`: Aprovado (Zero falso positivo comprovado).
- `test_ciclo_completo_campanha_recall_e_homologacao`: Aprovado.

---

## 5. Próximos Passos (Sprint 5A.5)

Conforme o **Plano Consolidado v5**, a próxima sprint é:
- **Sprint 5A.5: Fechamento do Bloco 5A — Dossiê Regulatório Unificado, Certificados de Análise e Auditoria Consolidada ANVISA.**
  - Geração de PDF oficial do Dossiê de Recall com selos sanitários, assinatura digital do RT e trilha de auditoria completa.
  - Conexão e conciliação do Dossiê com o ERP / NF-e (`documento_fiscal_ref`).
