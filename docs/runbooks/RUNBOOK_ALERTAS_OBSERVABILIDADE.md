# Runbook de Alertas de Observabilidade e Monitoramento Ativo

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Go-Live)  
**Classificação:** Operações, SRE & Suporte Técnico  
**Última Revisão:** 2026-10-27  

---

## 1. Visão Geral da Observabilidade

O Baros dispõe de um módulo unificado de diagnóstico em tempo real (`core.services.observabilidade_service`) que inspeciona de forma automatizada a saúde dos pilares vitais do sistema:
1. **Integridade do Razão Contábil (Partidas Dobradas: $\sum D = \sum C$)**
2. **Fila de Jobs Assíncronos e Tarefas Falhas (Celery / Redis)**
3. **Pendências de Contabilização (`PendenciaContabilizacao`)**
4. **Fila de Documentos Fiscais Represados (NF-e, MDF-e, CT-e)**
5. **Certificados Digitais A1 a Vencer**
6. **Entrega de Webhooks e Eventos de Integração**

Este documento detalha o significado, criticidade e o procedimento operacional de remediação para cada alerta disparado pelo sistema.

---

## 2. Catálogo de Alertas e Procedimentos de Remediação

### ALERTA 01: `RAZAO_CONTABIL_DESBALANCEADO`
- **Severidade:** **CRÍTICA (P1)**
- **Gatilho:** A auditoria contábil identifica qualquer desbalanceamento onde a soma dos débitos difere da soma dos créditos ($\sum D \ne \sum C$).
- **Impacto:** Distorção no Balanço Patrimonial e DRE. Risco de inconformidade fiscal perante a Receita Federal / ECD / ECF.
- **Procedimento Imediato:**
  1. Identificar o tenant e período afetado através da função de diagnóstico:
     ```bash
     python manage.py shell -c "
     from core.services.observabilidade_service import verificar_integridade_razao_contabil
     print(verificar_integridade_razao_contabil())
     "
     ```
  2. Localizar o lançamento com assimetria:
     ```sql
     SELECT lancamento_id, SUM(CASE WHEN tipo = 'DEBITO' THEN valor ELSE -valor END) AS diferenca
     FROM financeiro_partidacontabil
     GROUP BY lancamento_id
     HAVING SUM(CASE WHEN tipo = 'DEBITO' THEN valor ELSE -valor END) <> 0;
     ```
  3. Acionar o Tech Lead e o Contador responsável.
  4. Executar estorno contábil auditado ou lançamento de correção com chave de auditoria. Jamais editar diretamente o registro no banco via SQL.

---

### ALERTA 02: `JOBS_CELERY_FALHOS_CRITICOS`
- **Severidade:** **ALTA (P2)**
- **Gatilho:** Uma ou mais tarefas assíncronas do Celery falharam após esgotamento de retentativas (`max_retries`).
- **Impacto:** Atraso em conciliações automáticas, régua de cobrança, cálculo de DRE ou sincronização de telemetria.
- **Procedimento Imediato:**
  1. Acessar o painel Flower ou consultar o log estruturado do worker:
     ```bash
     celery -A config inspect active
     journalctl -u baros-celery-worker -n 100 --no-pager
     ```
  2. Verificar a causa da falha (ex: timeout de rede em gateway terceiro, lock de concorrência).
  3. O Baros possui chave de idempotência em todas as tarefas. É seguro reprocessar os jobs falhos individualmente:
     ```bash
     python manage.py shell -c "
     from core.services.observabilidade_service import diagnosticar_painel_observabilidade
     diag = diagnosticar_painel_observabilidade()
     print('Falhas detectadas:', diag['metricas']['jobs_falhos'])
     "
     ```

---

### ALERTA 03: `PENDENCIAS_CONTABILIZACAO_ACUMULADAS`
- **Severidade:** **MÉDIA (P3) / ALTA (P2 se > 20 pendências)**
- **Gatilho:** Eventos operacionais (vendas, baixas, compras, estadias) geraram registros em `PendenciaContabilizacao` com `resolvido=False`.
- **Impacto:** DRE ou Balanço provisório sem reconhecimento tempestivo de receitas ou despesas.
- **Procedimento Imediato:**
  1. Inspecionar o motivo das pendências via painel ou terminal:
     ```bash
     python manage.py shell -c "
     from financeiro.models import PendenciaContabilizacao
     for p in PendenciaContabilizacao.unscoped.filter(resolvido=False)[:10]:
         print(f'ID: {p.id} | Evento: {p.evento} | Erro: {p.erro_mensagem}')
     "
     ```
  2. Causas frequentes:
     - Falta de amarração de conta contábil no cadastro do produto ou centro de custo.
     - Período contábil fechado com status `FECHADO` ou `BLOQUEADO`.
  3. Remediação: Cadastrar a conta contábil faltante ou reabrir o período com aprovação da controladoria, e executar o serviço de reprocessamento:
     ```bash
     python manage.py shell -c "
     from financeiro.services.contabilidade_service import resolver_pendencias_contabilizacao
     resolvidos = resolver_pendencias_contabilizacao()
     print(f'Pendências reprocessadas com sucesso: {resolvidos}')
     "
     ```

---

### ALERTA 04: `FILA_FISCAL_REPRESADA`
- **Severidade:** **ALTA (P2)**
- **Gatilho:** Mais de 10 notas fiscais (NF-e/MDF-e) com status `'PROCESSANDO'` ou `'EM_TRANSMISSAO'` por mais de 5 minutos, ou SEFAZ com tempo de resposta > 10s.
- **Impacto:** Caminhões retidos na expedição aguardando DANFE para transporte de carga perigosa.
- **Procedimento Imediato:**
  1. Verificar o status da SEFAZ autorizadora da UF de origem (Disponibilidade SEFAZ).
  2. Se a SEFAZ estiver fora do ar:
     - Chavear a filial para modo Contingência EPEC / FS-DA no painel fiscal.
     - Emitir DANFEs em contingência para liberar os veículos de carga perigosa.
  3. Se o gateway fiscal intermediário estiver instável:
     - Verificar credenciais cifradas via `seguranca_service.py`.
     - Reiniciar o pool de workers dedicados à fila fiscal (`queue=fiscal`).

---

### ALERTA 05: `CERTIFICADO_DIGITAL_A_VENCER`
- **Severidade:** **ALERTA PREVENTIVO (30 dias) / ALTA (7 dias) / CRÍTICA ($\le$ 48h)**
- **Gatilho:** Data de expiração de certificado A1 (`certificado_valido_ate`) inferior a 30 dias.
- **Impacto:** Paralisação total de emissão de NF-e, CT-e e MDF-e no tenant se o certificado expirar.
- **Procedimento Imediato:**
  1. Notificar automaticamente o gestor e o financeiro do tenant via WhatsApp/E-mail com o link de upload seguro no portal.
  2. Obter o novo arquivo `.pfx` ou `.p12` emitido pela Autoridade Certificadora (ICP-Brasil).
  3. Fazer o upload com a senha do certificado; o sistema valida a cadeia criptográfica, armazena cifrado via Fernet e atualiza a data de validade.

---

### ALERTA 06: `WEBHOOKS_INTEGRACAO_ATRASADOS`
- **Severidade:** **MÉDIA (P3)**
- **Gatilho:** Webhooks de pagamento (PIX/Boleto do Asaas) ou eventos de rastreamento com tentativas pendentes há mais de 30 minutos.
- **Impacto:** Baixa demorada de títulos de clientes ou atraso no tracking em tempo real.
- **Procedimento Imediato:**
  1. Verificar a conectividade externa e DNS do cluster.
  2. Inspecionar se o payload do provedor sofreu alteração de schema ou quebra de assinatura HMAC.
  3. Disparar a rotina de reprocessamento de webhooks com chave de idempotência.
