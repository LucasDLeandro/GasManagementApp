# Relatório da Sprint 01.00 — Lotes e CQ: liberação do lote pelo RT com registro e regras

**Data:** 10/11/2026  
**Branch:** `sprint-01.00/lotes-cq`  
**Status:** Concluída com sucesso

---

## 1. O que foi feito

### Backend
- **Máquina de estados estrita (`TRANSICOES_QUALIDADE_LOTE`):**
  - Implementada constante em `produtos/services/ciclo_cilindro.py`:
    - `QUARENTENA` → `['APROVADO', 'REPROVADO']`
    - `APROVADO` → `['REPROVADO']`
    - `REPROVADO` → `[]` (terminal, imutável)
  - Qualquer transição fora dessas regras lança `ValidationError` (400 Bad Request).
- **Validação de justificativa:**
  - Reprovação (`QUARENTENA → REPROVADO` ou `APROVADO → REPROVADO`) exige justificativa técnica obrigatória com no mínimo 10 caracteres no backend (`ValidationError`).
  - Aprovação (`QUARENTENA → APROVADO`) mantém justificativa opcional.
- **Modelo imutável `HistoricoQualidadeLote`:**
  - Herda de `TenantAwareModel`, campos: `tenant`, `lote`, `status_anterior`, `status_novo`, `justificativa`, `usuario`, `responsavel_tecnico`, `rt_nome_snapshot`, `rt_registro_snapshot` (`CONSELHO-UF NUMERO`), `criado_em`.
  - Imutabilidade garantida: `save` e `delete` lançam `ValidationError` se o registro já possuir chave primária (`pk`).
  - Registrado no Django Admin (`HistoricoQualidadeLoteAdmin`) como estritamente somente leitura (`has_add_permission=False`, `has_change_permission=False`, `has_delete_permission=False`).
  - Migração `0022_historico_qualidade_lote.py` gerada e aplicada.
- **Homologação exclusiva por RT com vínculo ativo:**
  - Implementada função `obter_rt_vinculado_para_liberacao`: exige papel `RESPONSAVEL_TECNICO` (ou superusuário) E um `ResponsavelTecnico` ativo e vigente vinculado ao usuário (`ResponsavelTecnico.user`).
  - Superusuário sem esse vínculo recebe 403 ("Liberação restrita ao Responsável Técnico").
  - Usuário com papel `RESPONSAVEL_TECNICO` sem esse vínculo recebe 403.
  - Snapshots de RT gravados no histórico e em `AuditoriaBloqueioSanitario` sempre vêm do RT vinculado ao usuário atuante.
- **Serializers e Otimização Anti-N+1:**
  - `HistoricoQualidadeLoteSerializer` criado.
  - Em `LoteEnvaseSerializer`: `status_qualidade` marcado como `read_only_fields` (regra 3.7).
  - Adicionado campo `ultima_liberacao` com status, RT, registro, data e justificativa.
  - Para lotes legados sem histórico, `ultima_liberacao.rt` retorna `"Sem registro (anterior ao histórico)"` sem gerar registros retroativos.
  - Adicionado campo `transicoes_permitidas`: lista de transições permitidas para o usuário logado (vazia para não-RT).
  - `LoteEnvaseViewSet`: `get_serializer_context` resolve a capacidade de liberação do RT uma vez por requisição; `get_queryset` inclui `prefetch_related` para `historico_qualidade` ordenado. Executa número fixo de queries independentemente do tamanho da listagem.
- **Tratamento de Exceções e Action de Histórico:**
  - Action `GET /produtos/api/lotes/{id}/historico-qualidade/` adicionada no ViewSet.
  - Removido `except Exception as e` da action `qualidade`, utilizando tratamento explícito (`PermissionError` → 403, `ValidationError` → 400 com chaves `detail` e `error`).

### Frontend (Aba Lotes/CQ)
- **Eliminação de estilos inline:**
  - Removidos todos os 27 atributos `style="` de `_aba_lotes.html` (agora 0 ocorrências).
  - Removidas cores fixas hexadecimais (`#16a34a`, `#dc2626`, `#0284c7`), utilizando variáveis CSS do Design System v1 (`var(--status-...)`, `var(--color-...)`).
- **Cards de Métricas e Tabela Segura:**
  - KPIs de lotes aprovados, em quarentena e reprovados estruturados com `metric-card` do Design System.
  - Tabela reconstruída em `fase3_rampa_recebimento_lotes.js` (`CentralLotesCQ`) com `document.createElement` e `textContent` (zero `innerHTML` com interpolação de dados dinâmicos, zero `onclick` em template string).
  - Badges de status com classes `.badge-status-{approved|quarantine|danger}`.
  - Coluna "Liberado por" exibindo RT, conselho/UF, registro e data, ou "Sem registro (anterior ao histórico)".
- **Controle de Ações por Papel:**
  - Botões "Aprovar" e "Reprovar" renderizados estritamente a partir de `transicoes_permitidas`. Usuários não-RT visualizam a indicação textual `"Liberação restrita ao RT"`.
- **Modais de Confirmação:**
  - **Aprovação:** diálogo `Baros.confirmar` exibindo resumo com código do lote, gás químico, pureza aferida, validade e verificação de laudo PDF (aviso destacado caso o PDF não esteja anexado).
  - **Reprovação:** diálogo `Baros.confirmar({ motivo: 10, perigo: true })` com alerta de bloqueio sanitário imediato dos cilindros.
- **Drawer de Histórico:**
  - Implementado `<dialog id="drawer-historico-lote" class="drawer-dialog">` no padrão de componentes do Baros, acionado pelo botão "Histórico" na tabela.
  - Lista a linha do tempo de alterações com status anterior e novo, badges, RT homologador, operador e justificativa técnica.
- **Rede e Estados de Erro:**
  - Migrado de `fetch` puro para `Baros.api`.
  - Tratamento de erro de carregamento exibindo estado visual de erro (`ds-empty ds-empty--danger`) com botão "Tentar novamente" dentro da tabela.
- **Versionamento de Assets:**
  - Atualizado `?v=20261110_s0100` em `produtos/index.html` para `index.css` e `fase3_rampa_recebimento_lotes.js`.

---

## 2. Bugs encontrados e corrigidos no caminho

1. **Testes de apuração fiscal (`fiscal/tests/test_sprint11b_fiscal_gases.py`):**
   - Dois testes falhavam porque criavam `DocumentoFiscal` com `criado_em` automático de novembro/2026, enquanto a apuração testava período estático `2026-10`.
   - Ajustado `criado_em` no teste para a data do período testado, tornando-o independente da data do sistema, em commit isolado `test(fiscal): independizar teste de apuracao de impostos da data de execucao`.
2. **`TenantNotSet` ao instanciar `HistoricoQualidadeLote` e `ResponsavelTecnico`:**
   - Em operações internas/testes sem tenant ativo no contexto da thread, o isolamento fail-closed exigia `tenant_context`. No service, a criação utiliza `HistoricoQualidadeLote.unscoped.create(tenant=lote.tenant, ...)` para segurança absoluta.
3. **Ausência de usuário RT vinculado em `populate_db.py`:**
   - O Responsável Técnico da empresa de demonstração "Oxigênio Brasília" (`rt_a`) não possuía usuário vinculado (`user=None`), impedindo o teste real de homologação.
   - Atualizado `populate_db.py` para criar o usuário `rt.bsb` (Dra. Camila Rocha) com papel `RESPONSAVEL_TECNICO` vinculado ao registro do RT.

---

## 3. O que ficou de fora e por quê

- **Aba Ativos e drawer 360°:** pertence à Sprint 01.01.
- **Impressão de etiquetas de colarinho e patrimonial:** pertence à Sprint 01.02.
- **Laboratório completo de CQ e análise instrumental:** pertence à Sprint 16.
- **Padrão do lote ao nascer (`APROVADO` com pureza 99,5%):** aguarda decisão do dono do projeto (item 04.5 de `DECISOES_PENDENTES.md`).

---

## 4. Decisões tomadas por premissa

- **Lote reprovado é final:** Uma vez reprovado, o lote não pode transitar para nenhum outro status (`REPROVADO` tem lista vazia de transições). A reabertura de lote reprovado dependerá de processo de retificação formal ou estorno a ser decidido pelo dono.
- **Critério para apuração de impostos fiscais:** Registrado que `calcular_apuracao_imposto` filtra as saídas por `criado_em` e as entradas por `data_emissao`; a padronização definitiva entre `criado_em` e `data_autorizacao` permanece para a Sprint 12.
- **Exigência de RT ativo e vinculado:** Superusuários e administradores não podem homologar lotes sem ter um cadastro ativo de `ResponsavelTecnico` com CRF/CRQ vinculado à sua conta no tenant. Isso atende rigorosamente às exigências da ANVISA (RDC 658/2022).

---

## 5. Resultado da suíte de testes

- **Execução final:** `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- **Total de testes:** **690 passed**, 4 warnings em 2m38s.
- **Zero falhas.**

---

## 6. Lista de commits

1. `36fc4e0`: `test(fiscal): independizar teste de apuracao de impostos da data de execucao`
2. `2b5427d`: `feat(produtos): maquina de estados de qualidade de lotes, modelo imutavel de historico e regras do RT`
3. `797ecb7`: `feat(produtos): redesenho da aba lotes/cq com Design System v1, drawer de historico e confirmacoes do RT`
4. `37d28c9`: `feat(core): usuario rt.bsb vinculado no populate_db e teste de renderizacao da aba lotes`

---

## 7. Notas de deploy

- **Migrações:** Executar `python manage.py migrate produtos` para aplicar a migração `0022_historico_qualidade_lote.py`.
- **Variáveis de ambiente novas:** Nenhuma.
- **Dependências novas:** Nenhuma.
- **Dados iniciais / Povoamento:** Rodar `python populate_db.py` (idempotente). O comando agora garante a criação do usuário `rt.bsb` (Dra. Camila Rocha, senha padrão do ambiente) vinculado ao `ResponsavelTecnico` da empresa "Oxigênio Brasília".
- **Estáticos:** Executar `python manage.py collectstatic --noinput` para atualizar `index.css` e `fase3_rampa_recebimento_lotes.js`.
- **Atenção operacional:** Para que a aba de lotes funcione em produção/staging, o módulo `envase` deve estar habilitado para o tenant contratante (`tenant.modulo_envase_ativo = True`).

---

## 8. Verificação dos Itens da Sprint

### Testes da Sprint
- [x] **Falha antes:** `REPROVADO → APROVADO` responde 400 (respondia 200).
- [x] **Falha antes:** reprovar com justificativa vazia ou de 5 caracteres responde 400 (respondia 200).
- [x] Aprovar cria uma linha em `HistoricoQualidadeLote` com RT e registro do snapshot; reprovar também, e bloqueia os cilindros como antes.
- [x] Usuário GERENTE/OPERADOR recebe 403 e `transicoes_permitidas` vazia; RT recebe as transições certas para cada status.
- [x] Lote de outra empresa: 404 na ação e no histórico.
- [x] Teste estático: o bloco `CentralLotesCQ` não tem `innerHTML` com `${` e não tem `onclick=` em template string.
- [x] Superusuário sem vínculo com `ResponsavelTecnico` ativo recebe 403.
- [x] RT sem vínculo ativo recebe 403; RT vinculado recebe 200 com snapshot próprio.
- [x] Lotes legados sem histórico exibem "Sem registro (anterior ao histórico)".
- [x] Listagem de lotes sem N+1 (testado com contagem constante de queries).
- [x] Imutabilidade do modelo na instância (`save`/`delete`) e no admin (`has_add/change/delete_permission = False`).

### Critérios de Aceite
- [x] Verificado no navegador / simulação completa com usuário RT (`rt.bsb`) e com GERENTE (`gerente.bsb`), numa cópia do banco (`C:/Temp/baros_verificacao.sqlite3`) com o módulo envase ativo:
  - Aprovação exige confirmação detalhada do lote.
  - Reprovação exige justificativa mínima de 10 caracteres.
  - Cilindros ativos entram em bloqueio sanitário imediato.
  - Histórico exibe RT, conselho/UF e data.
  - Gerente visualiza a listagem com `transicoes_permitidas: []` e texto "Liberação restrita ao RT", e recebe 403 em tentativas de POST.
  - Compatibilidade com temas claro, escuro e alto contraste comprovada pelo uso exclusivo de variáveis CSS.
  - Layout responsivo para 375px via flex-wrap e overflow horizontal da tabela.
- [x] Definição de pronto atendida integralmente (seção 9 das regras gerais).
