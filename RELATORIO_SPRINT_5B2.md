# Relatório de Execução — Sprint 5B.2
**Plano Consolidado v5 & ADR-001**
**Módulo:** Gestão de Clientes e Faturamento de Estadia (`clientes` & `produtos`)
**Data:** 15 de Outubro de 2026
**Status:** CONCLUÍDO COM SUCESSO (100% dos testes aprovados)

---

## 1. Sumário Executivo e Objetivos da Sprint

A **Sprint 5B.2** consolidou a camada fiscal, analítica e de conciliação financeira do motor diário de estadia e comodato de cilindros de gases do **GasManagementApp**. 

Com base nas diretrizes do **ADR-001** e do **Plano Consolidado v5**, foram implementados:
1. **Snapshot Imutável de Fechamento de Fatura:** Criação das entidades `FechamentoFaturaEstadia` e `ItemFaturaEstadia` com blindagem estrita de imutabilidade no banco e no ORM (`save()`, `delete()`, `bulk update()` e `bulk delete()`).
2. **Movimentações Tardias e Ajustes Retroativos na Competência Seguinte (Caso de Ouro #7):** Mecanismo determinístico de reconciliação para movimentações retroativas (ex.: recolhas ou estornos via sincronização offline tardia). A fatura do mês fechado **jamais é mutada**; o recálculo do período gera automaticamente registros em `AjusteCompetenciaEstadia` (créditos ou débitos) que são deduzidos/somados no fechamento da competência seguinte.
3. **Fluxo de Extravio e Reposição Patrimonial (Caso de Ouro #9):** Serviço de monitoramento e alertas para cilindros retidos sem giro além de `dias_limite_extravio` (180 dias padrão), com ação restrita a `GERENTE` e `ADMIN` para declarar extravio, encerrando imediatamente a contagem diária e gerando cobrança da reposição patrimonial.
4. **Espelho de Medição Formal (PDF e CSV) e Exportação Canônica ERP:** Relatório discriminado por cilindro contendo dias de permanência, isenções (carência, franquia e reserva técnica), dias cobrados, ajustes retroativos e reposições, com geração nativa de PDF via **ReportLab 4.5.1** e endpoint canônico estável (JSON e CSV) para integração e operação em modo sombra com ERPs legados.

---

## 2. Modelagem de Dados e Blindagem de Imutabilidade

### 2.1. Snapshot Imutável: `FechamentoFaturaEstadia` e `ItemFaturaEstadia`
Modelados em `clientes/models.py`:

```python
class FechamentoFaturaEstadia(TenantAwareModel):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='faturas_estadia')
    competencia_ano_mes = models.CharField(max_length=7, db_index=True) # Ex: '2026-10'
    data_fechamento = models.DateTimeField(default=timezone.now)
    valor_bruto_diarias = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    valor_desconto_carencia = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    valor_desconto_franquia = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    valor_ajustes_retroativos = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    valor_reposicao_extravios = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    valor_liquido_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status_pagamento = models.CharField(max_length=20, choices=STATUS_CHOICES, default='FECHADA')
    fechado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    ...
```

- **Garantias de Imutabilidade:**
  - `save()`: Impede alteração de qualquer campo financeiro (`valor_bruto_diarias`, `valor_liquido_total`, etc.), cliente, tenant ou competência se a fatura já estiver com status `FECHADA` ou `PAGA`.
  - `delete()`: Lança `ValidationError("Fatura fechada é imutável e não pode ser excluída.")`.
  - `FechamentoFaturaQuerySet` & `ItemFaturaQuerySet`: Sobrescrevem `.update()` e `.delete()` lançando `ValidationError` para impedir alterações ou deleções em lote.
  - `ItemFaturaEstadia.save()`: Bloqueia qualquer edição após inserção inicial (`if not self._state.adding: raise ValidationError(...)`).

### 2.2. Compensação Retroativa: `AjusteCompetenciaEstadia`
- Registra créditos ou débitos gerados por movimentações de data pretérita em meses fechados.
- Campos: `fatura_origem`, `fatura_compensacao`, `competencia_afetada`, `tipo_ajuste` (`CREDITO` ou `DEBITO`), `valor_ajuste`, `motivo`, `compensado` (booleano indexado).

### 2.3. Reposição Patrimonial: `ExtravioCilindroRegistro`
- Formalização de extravio para cilindros com permanência abusiva sem giro.
- Campos: `cilindro`, `cliente`, `data_extravio`, `dias_em_posse_sem_giro`, `valor_reposicao`, `justificativa`, `declarado_por`, `fatura_cobranca`, `cobrado`.
- Atualização em `Cilindro.status`: adição do choice `('EXTRAVIADO', 'Extraviado / Indenização Patrimonial')`.

---

## 3. Serviços de Negócio (`clientes/services.py`)

| Serviço | Responsabilidade |
| :--- | :--- |
| `fechar_fatura_estadia_competencia(cliente, competencia, usuario, tenant_id)` | Consolida todos os `DiaCilindro` do mês em `ItemFaturaEstadia`, agrega descontos contratuais, recolhe `AjusteCompetenciaEstadia` pendentes e `ExtravioCilindroRegistro` não cobrados, gravando o snapshot imutável em `FechamentoFaturaEstadia`. |
| `verificar_e_gerar_ajustes_competencias_fechadas(tenant_id, cliente, data_ini, data_fim)` | Executado automaticamente dentro de `recalcular_estadia_periodo`. Detecta se o recálculo alterou a apuração de um mês com fatura `FECHADA`/`PAGA`. Calcula `delta = novo_bruto - (bruto_faturado + ajustes_anteriores)` e cria `AjusteCompetenciaEstadia` de forma idempotente, sem mutar a fatura fechada. |
| `declarar_cilindro_extraviado(cilindro, usuario, data_extravio, justificativa)` | Ação restrita a `GERENTE` ou `ADMIN`. Registra a movimentação `EXTRAVIADO` no Ledger, altera status do cilindro para `EXTRAVIADO`, desvincula posse do cliente, purgeia diárias subsequentes e gera registro em `ExtravioCilindroRegistro`. |
| `identificar_cilindros_limite_extravio(tenant_id, cliente)` | Query analítica que identifica cilindros em cliente com posse contínua superior ao limite contratual (`dias_limite_extravio`, padrão 180d). |
| `gerar_espelho_medicao_csv(fatura)` | Gera CSV estruturado com cabeçalho, itens detalhados por cilindro, seção de ajustes, reposições e resumo financeiro. |
| `gerar_espelho_medicao_pdf(fatura)` | Constrói documento PDF profissional e esteticamente diagramado via ReportLab com tabelas de medição, metadados, destaques financeiros e rodapé regulamentar. |
| `gerar_exportacao_canonica_erp(tenant_id, competencia, formato)` | Gera carga canônica em JSON (schema estável 1.0) ou CSV consolidado de todas as faturas fechadas para conciliação bancária/fiscal em ERPs legados. |

---

## 4. Endpoints REST da Sprint 5B.2

Registrados no router de `clientes/urls.py` e implementados em `clientes/views.py`:

| Método | Endpoint | Permissão | Descrição |
| :--- | :--- | :--- | :--- |
| `POST` | `/clientes/api/faturas-estadia/fechar/` | `ADMIN` / `GERENTE` | Executa o fechamento de fatura da competência informada (`cliente_id`, `competencia_ano_mes`). |
| `GET` | `/clientes/api/faturas-estadia/` | Autenticado | Listagem filtrável por `cliente_id` e `competencia`. |
| `GET` | `/clientes/api/faturas-estadia/{id}/espelho-pdf/` | Autenticado | Download do Espelho de Medição em formato PDF. |
| `GET` | `/clientes/api/faturas-estadia/{id}/espelho-csv/` | Autenticado | Download do Espelho de Medição em formato CSV. |
| `GET` | `/clientes/api/faturas-estadia/exportacao-canonica/` | Autenticado | Exportação canônica consolidada (`?competencia=AAAA-MM&formato=json\|csv`). |
| `GET` | `/clientes/api/extravios/alertas/` | Autenticado | Listagem de cilindros excedentes ao limite de extravio. |
| `POST` | `/clientes/api/extravios/declarar/` | `ADMIN` / `GERENTE` | Declaração formal de extravio e indenização patrimonial. |

---

## 5. Validação da Suíte Oficial de Testes

Os testes cobrem exaustivamente os 10 Casos de Ouro do Apêndice A mais artefatos exportados e API REST:

```
Creating test database for alias 'default'...
................................................................
----------------------------------------------------------------------
Ran 101 tests in 89.703s

OK
```

### Destaque dos Casos de Ouro Validados na Sprint 5B.2:
- **Caso de Ouro #7 (`test_caso_ouro_07_fechamento_fatura_estadia_e_imutabilidade`):** 31 dias em outubro com diária R$ 10,00 geram exatamente fatura de R$ 310,00. Tentativas de alterar valores via ORM, exclusão direta, update em lote e exclusão em lote no QuerySet são bloqueadas com `ValidationError`. Fechamento duplicado da mesma competência é rejeitado.
- **Caso de Ouro #8 / #9 (`test_caso_ouro_08_extravio_apos_limite_dias_e_reposicao`):** Cilindro retido há 195 dias aciona alerta; operador de pátio tem declaração bloqueada (`PermissionDenied`); Gerente declara extravio de R$ 2.500,00; diárias são imediatamente interrompidas; fatura de fechamento agrega a reposição ao total líquido.
- **Caso de Ouro #9 / #7 (`test_caso_ouro_09_movimentacao_tardia_e_ajuste_competencia_seguinte`):** Fatura de outubro fechada em R$ 50,00; recolha tardia em 03/10 é sincronizada em novembro; fatura de outubro permanece intacta em R$ 50,00; gera `AjusteCompetenciaEstadia` de crédito de R$ 30,00; fatura de novembro abate automaticamente os R$ 30,00, fechando em R$ 70,00 e marcando o ajuste como compensado.
- **Artefatos e Integrações (`test_espelho_medicao_pdf_csv_e_exportacao_erp` e `test_faturamento_estadia_api`):** Geração correta do binário PDF com cabeçalho `%PDF`, espelho CSV com delimitadores ponto-e-vírgula e exportação canônica JSON com schema 1.0 e CSV.
