# Relatório de Execução — SPRINT 5A.2
**Módulo:** Integridade do Ledger, Imutabilidade e Refatoração do Seed  
**Status:** CONCLUÍDO COM 100% DE SUCESSO E 58/58 TESTES APROVADOS  
**Data:** 15/10/2026  
**Responsável:** Engenheiro de Software Sênior (Pair Programming Antigravity)  

---

## 1. Resumo Executivo

A **Sprint 5A.2** consolidou a inviolabilidade contábil, sanitária e transacional do **GasManagementApp**. Foram implementadas camadas redundantes de proteção (no ORM, nos Services e em CheckConstraints de banco de dados) que transformam as entidades regulatórias em registros estritamente append-only.

Principais realizações da sprint:
1. **Imutabilidade Estrita de `EnvaseCilindro` e `MovimentacaoCilindro`:**
   - Bloqueio de qualquer tentativa de `.save()` em update (`if not self._state.adding: raise ValidationError(...)`) e `.delete()` em instâncias existentes de `EnvaseCilindro`.
   - Implementação de `EnvaseQuerySet`, `EnvaseManager`, `UnscopedEnvaseQuerySet` e `UnscopedEnvaseManager` que bloqueiam terminantemente chamadas a `.update()` e `.delete()` em lote.
2. **Vínculo de Envase/Carregamento e `documento_fiscal_ref` no Ledger:**
   - `MovimentacaoCilindro` agora possui `envase_cilindro` como ForeignKey (`models.PROTECT`) para `EnvaseCilindro` e `documento_fiscal_ref` (`CharField(max_length=60)`) para conciliação contábil/fiscal de NF-e com ERPs.
   - **Proteção do Legado:** Criação do campo `is_legado` e da tabela auxiliar `VinculoLegadoInferido`. Registros históricos anteriores permanecem intocados com `envase_cilindro = NULL` no ledger oficial.
   - **`CheckConstraint` Condicional no Banco de Dados:** A constraint `check_movimentacao_envase_coerente` garante no motor relacional que movimentações cheias exigem `envase_cilindro IS NOT NULL`, enquanto movimentações vazias exigem `envase_cilindro IS NULL`.
3. **Máquina de Estados Finita (FSM) e Concorrência Segura:**
   - Regras de transição de status centralizadas em `TRANSIÇÕES_PERMITIDAS_CILINDRO` e `validar_transicao_status_cilindro()` em [produtos/services.py](file:///c:/Lucas/GasManagementApp/produtos/services.py). O estado `BAIXADO` é estritamente terminal (`set()`), impedindo reativação de cilindros condenados.
   - Todas as mutações de status ocorrem dentro de `transaction.atomic()` com travamento pessimista via `Cilindro.objects.select_for_update()`.
4. **Refatoração Completa e Idempotente de `populate_db.py`:**
   - O seed foi totalmente refatorado com credenciais seguras lidas via `.env` (`DEFAULT_USER_PASSWORD`), dados geopolíticos e sanitários coerentes (DF/GO, CRM/CRF/CRQ), e geração de chaves determinísticas (`uuid.uuid5`).
   - Todos os 8 cilindros de cada tenant são criados e movimentados **exclusivamente através das funções de serviço de `services.py`**, obedecendo à risca as travas da ANVISA e INMETRO.

Todos os **58 testes automatizados** do projeto foram executados e aprovados com sucesso.

---

## 2. Entregas Técnicas Executadas

### 2.1. Imutabilidade de `EnvaseCilindro` ([produtos/models.py](file:///c:/Lucas/GasManagementApp/produtos/models.py))

Para espelhar o comportamento append-only do Ledger de movimentações, `EnvaseCilindro` recebeu proteção integral:

- **Na Instância:**
  ```python
  def save(self, *args, **kwargs):
      if not self._state.adding:
          raise ValidationError(
              "Histórico de envase imutável: registros de envase não podem ser alterados após a criação."
          )
      super().save(*args, **kwargs)

  def delete(self, *args, **kwargs):
      raise ValidationError(
          "Histórico de envase imutável: registros de envase não podem ser excluídos."
      )
  ```
- **No QuerySet e Managers:**
  - `EnvaseQuerySet(TenantQuerySet)`: Sobrescreve `update()` e `delete()` lançando `ValidationError`.
  - `EnvaseManager(TenantManager)`: Conecta o queryset protegido ao gerenciador padrão com escopo multi-tenant.
  - `UnscopedEnvaseQuerySet` e `UnscopedEnvaseManager`: Garantem que mesmo tentativas administrativas via `.unscoped` não consigam atualizar ou deletar envases em lote.

---

### 2.2. Vínculo de Envase, Chave Fiscal e CheckConstraint Condicional

Em [produtos/models.py](file:///c:/Lucas/GasManagementApp/produtos/models.py), o modelo `MovimentacaoCilindro` foi enriquecido:

- **Novos Campos:**
  - `envase_cilindro`: `models.ForeignKey(EnvaseCilindro, on_delete=models.PROTECT, null=True, blank=True, related_name='movimentacoes')`.
  - `documento_fiscal_ref`: `models.CharField(max_length=60, null=True, blank=True)` — armazena chaves de acesso de NF-e (44 dígitos), números de romaneio ou documentos de devolução fiscal.
  - `is_legado`: `models.BooleanField(default=False)` — identifica registros preexistentes à Sprint 5A.2.

- **CheckConstraint `check_movimentacao_envase_coerente`:**
  Garante a nível de banco de dados:
  1. Se `is_legado=True`, a linha é isenta de verificação retroativa.
  2. Movimentações cheias (`ENVASE`, `SAIDA_ROTA`, `ENTREGA_CLIENTE`, `SAIDA_ENTREGA`, `RESERVA_ROTA`) **exigem** `envase_cilindro IS NOT NULL`.
  3. Movimentações de casco vazio (`RECOLHA_CLIENTE`, `ENVIO_RETESTE`, `RETORNO_RETESTE`, `BAIXA`, `ENTRADA_ESTOQUE`, `COMPRA`, `RETORNO_VAZIO`) **exigem** `envase_cilindro IS NULL`.
  4. Movimentações administrativas (`RECLASSIFICACAO`, `ESTORNO`) permitem flexibilidade conforme o caso.

- **Proteção do Histórico Legado e Tabela `VinculoLegadoInferido`:**
  - Nenhuma linha anterior de `MovimentacaoCilindro` foi alterada com dados inventados.
  - A migração `produtos/migrations/0005_vinculolegadoinferido_and_more.py` executou `UPDATE produtos_movimentacaocilindro SET is_legado = 1;` antes de registrar a restrição no banco.
  - Criado o modelo `VinculoLegadoInferido` com vínculo `OneToOneField(MovimentacaoCilindro)` e `ForeignKey(EnvaseCilindro)` com justificativa explícita para conciliações auditoriais fora do dossiê oficial.

---

### 2.3. Máquina de Estados Finita (FSM) e Concorrência ([produtos/services.py](file:///c:/Lucas/GasManagementApp/produtos/services.py))

As regras de ciclo de vida foram centralizadas na matriz `TRANSIÇÕES_PERMITIDAS_CILINDRO`:

```python
TRANSIÇÕES_PERMITIDAS_CILINDRO = {
    'VAZIO_TRIAGEM': {'CHEIO_DISPONIVEL', 'EM_ENVASE', 'EM_RETESTE', 'BAIXADO'},
    'EM_ENVASE': {'CHEIO_DISPONIVEL', 'VAZIO_TRIAGEM', 'BAIXADO'},
    'CHEIO_DISPONIVEL': {'RESERVADO_ROTA', 'EM_POSSE_CLIENTE', 'VAZIO_TRIAGEM', 'BAIXADO'},
    'RESERVADO_ROTA': {'EM_POSSE_CLIENTE', 'CHEIO_DISPONIVEL', 'VAZIO_TRIAGEM', 'BAIXADO'},
    'EM_POSSE_CLIENTE': {'VAZIO_TRIAGEM', 'CHEIO_DISPONIVEL', 'BAIXADO'},
    'EM_RETESTE': {'VAZIO_TRIAGEM', 'BAIXADO'},
    'BAIXADO': set(),  # ESTADO TERMINAL: Nenhuma transição permitida
}
```

- **Validação de Transição:** `validar_transicao_status_cilindro(cilindro, novo_status)` é chamada em todos os serviços. Se o status atual for `BAIXADO`, qualquer alteração é abortada com `ValidationError`.
- **Concorrência e Locks:**
  Todas as operações transacionais (`registrar_envase_cilindro`, `registrar_entrega_cilindro`, `registrar_recolha_cilindro`, `enviar_para_reteste`, `retornar_de_reteste`, `alocar_cilindro_rota` e `baixar_cilindro`) operam com `@transaction.atomic` e invocam `Cilindro.objects.select_for_update().get(id=cilindro_id)`, eliminando race conditions de dupla entrega ou envase concorrente.

---

### 2.4. Refatoração Idempotente de `populate_db.py`

O script [populate_db.py](file:///c:/Lucas/GasManagementApp/populate_db.py) foi reescrito integralmente:

1. **Segurança de Credenciais:** Removidas senhas fixas inseguras (`senha123`). As senhas de gerentes agora são parametrizadas via `os.getenv("DEFAULT_USER_PASSWORD", "Agy@Gas2026!Segura")`, aplicando hashing seguro (`check_password` e `set_password`).
2. **Idempotência Determinística:** Criada a função `get_deterministic_uuid(tenant_id, key)` baseada em `uuid.uuid5(uuid.NAMESPACE_DNS)`. Em execuções sucessivas, os serviços detectam o registro por `client_uuid` e retornam a instância existente imediatamente sem duplicar eventos no Ledger.
3. **Ciclo de Vida 100% via Services:**
   - **Cilindro 1 (O2-MED):** Envasado com lote hospitalar válido -> `CHEIO_DISPONIVEL` no pátio.
   - **Cilindro 2 (O2-MED):** Envasado -> Entregue há 15 dias com `NFE-BRA-002` no Hospital Santa Lúcia -> `EM_POSSE_CLIENTE` (dentro da carência).
   - **Cilindro 3 (N2-IND):** Envasado com lote N2 -> Entregue há 45 dias com `NFE-BRA-003` na Metalúrgica -> `EM_POSSE_CLIENTE` (comodato excedente).
   - **Cilindro 4 (AR-IND):** Envasado com lote Argônio -> Entregue há 95 dias com `NFE-BRA-004` na Clínica Vida -> `EM_POSSE_CLIENTE` (comodato crítico).
   - **Cilindro 5 (O2-MED):** Envasado -> Entregue -> Recolhido vazio há 2h via `registrar_recolha_cilindro` -> `VAZIO_TRIAGEM` (Full-for-Empty bilateral).
   - **Cilindro 6 (N2-IND):** Requalificação quinquenal vencida -> Enviado para reteste via `enviar_para_reteste` -> `EM_RETESTE`.
   - **Cilindro 7 (O2-MED):** Envasado com lote submetido a Recall ANVISA (pureza 98.10%) -> Entregue há 50 dias com `NFE-BRA-007` no Hospital Santa Lúcia -> `EM_POSSE_CLIENTE`.
   - **Cilindro 8 (O2-MED):** Condenado por avaria estrutural na ogiva via `baixar_cilindro` -> `BAIXADO` (estado terminal).
4. **Verificação de Reexecução:** O script foi executado duas vezes consecutivas do terminal com retorno de código de saída `0` e integridade inalterada.

---

### 2.5. Suíte Automatizada de Testes ([produtos/tests_sprint5a2.py](file:///c:/Lucas/GasManagementApp/produtos/tests_sprint5a2.py))

Foram desenvolvidos 13 novos testes automatizados focados estritamente nos critérios de aceite da sprint:

| Caso de Teste | Objetivo | Resultado |
| :--- | :--- | :---: |
| `test_envase_cilindro_bloqueia_edicao_em_instancia` | Valida que `.save()` em update em `EnvaseCilindro` lança `ValidationError` | **Aprovado** |
| `test_envase_cilindro_bloqueia_delete_em_instancia` | Valida que `.delete()` em `EnvaseCilindro` lança `ValidationError` | **Aprovado** |
| `test_envase_cilindro_bloqueia_update_e_delete_em_lote_no_queryset` | Valida bloqueio de `.update()` e `.delete()` em `EnvaseQuerySet` e `UnscopedEnvaseQuerySet` | **Aprovado** |
| `test_registrar_envase_vincula_envase_cilindro_no_ledger` | Valida que `registrar_envase_cilindro` vincula `envase_cilindro` na `MovimentacaoCilindro` | **Aprovado** |
| `test_registrar_entrega_vincula_envase_e_documento_fiscal_ref` | Valida propagação do envase ativo e persistência de NF-e na entrega | **Aprovado** |
| `test_bloqueio_entrega_cilindro_cheio_sem_envase_ativo_no_service` | Valida recusa do serviço de entrega caso cilindro não tenha envase associado | **Aprovado** |
| `test_alocar_cilindro_rota_vincula_envase_corretamente` | Valida transição para `RESERVADO_ROTA` e vínculo do envase ativo | **Aprovado** |
| `test_check_constraint_rejeita_movimentacao_cheia_sem_envase` | Valida que `CheckConstraint` rejeita entrega sem `envase_cilindro` a nível de banco | **Aprovado** |
| `test_check_constraint_rejeita_movimentacao_vazia_com_envase` | Valida que `CheckConstraint` rejeita recolha de casco vazio com `envase_cilindro` | **Aprovado** |
| `test_check_constraint_permite_registro_legado_sem_envase` | Valida que `is_legado=True` isenta registros históricos da restrição | **Aprovado** |
| `test_tabela_auxiliar_vinculo_legado_inferido` | Valida persistência de vínculos legados inferidos sem tocar o ledger histórico | **Aprovado** |
| `test_fsm_transicao_ilegal_rejeitada` | Valida rejeição de saltos de estado não mapeados na matriz da FSM | **Aprovado** |
| `test_fsm_estado_baixado_e_estritamente_terminal` | Valida que cilindro `BAIXADO` não pode retornar a nenhum outro status | **Aprovado** |

---

## 3. Matriz de Rastreabilidade dos Critérios de Aceite

| Requisito do Plano Consolidado v5 | Implementação | Evidência de Validação |
| :--- | :--- | :--- |
| **Imutabilidade Estrita de `EnvaseCilindro`** | `save()` e `delete()` bloqueados; `EnvaseQuerySet` e `EnvaseManager` bloqueiam `.update()` e `.delete()` | 3 testes em `tests_sprint5a2.py` aprovados |
| **Vínculo `envase_cilindro` e `documento_fiscal_ref` no Ledger** | Campos adicionados em `MovimentacaoCilindro`; propagação automática nas funções de serviço | 3 testes em `tests_sprint5a2.py` aprovados |
| **CheckConstraint Condicional no Banco** | `check_movimentacao_envase_coerente` aplicada via migração `0005` | Testes diretos com `IntegrityError` aprovados |
| **Proteção do Histórico Legado** | Flag `is_legado` aplicada em migração; modelo `VinculoLegadoInferido` criado | Testes de isenção de legado aprovados |
| **FSM com Estado Terminal `BAIXADO`** | `TRANSIÇÕES_PERMITIDAS_CILINDRO` com `BAIXADO: set()` e `validar_transicao_status_cilindro` | 2 testes em `tests_sprint5a2.py` aprovados |
| **Travamento Concorrente com `select_for_update`** | Aplicado em todos os métodos transacionais de mutação em `services.py` | Homologado nos serviços |
| **Refatoração Idempotente de `populate_db.py`** | Criação determinística via UUIDv5, senhas por `.env`, 100% via `services.py` | Reexecução dupla no terminal com código `0` |

---

## 4. Resultado da Suíte de Testes do Projeto

Execução de todos os testes da aplicação via `python manage.py test`:

```text
Found 58 test(s).
Creating test database for alias 'default'...
..........................................................
----------------------------------------------------------------------
Ran 58 tests in 28.139s

OK
Destroying test database for alias 'default'...
```

**Resultado:** 58 testes executados, 0 falhas, 0 erros (100% de aprovação).
