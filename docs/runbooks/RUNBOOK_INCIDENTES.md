# Runbook de Gestão de Incidentes, Backup e Continuidade Operacional (BCP / DRP)

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Go-Live)  
**Classificação:** Interno / Operações & Engenharia  
**Última Revisão:** 2026-10-27  

---

## 1. Objetivos de Continuidade e SLAs de Recuperação

Em conformidade com a política corporativa de governança e proteção patrimonial de dados dos tenants do Baros SaaS, as metas operacionais de recuperação são estritamente fixadas em:

| Indicador | Meta / SLA | Descrição |
| :--- | :--- | :--- |
| **RPO (Recovery Point Objective)** | **$\le$ 15 minutos** | Perda máxima tolerável de dados transacionais em caso de desastre catastrófico. Garantido via *Continuous WAL Archiving* no PostgreSQL. |
| **RTO (Recovery Point Objective)** | **$\le$ 4 horas** | Tempo máximo tolerável para restauração completa da infraestrutura, validação de integridade contábil e liberação aos tenants. |
| **MTTR (Mean Time to Resolve - P1)** | **$\le$ 2 horas** | Tempo médio de mitigação operacional para incidentes de severidade crítica sem perda de infraestrutura física. |
| **Retenção de Backups** | **30 dias (PITR) + 5 anos (Cold)** | Snapshots diários e WALs contínuos mantidos por 30 dias em armazenamento redundante (S3/GCS); fechamentos fiscais anuais mantidos por 5 anos (Art. 173 CTN). |

---

## 2. Matriz de Severidade e Escalonamento

| Severidade | Critério de Disparo | Tempo de Resposta Inicial | Responsáveis |
| :--- | :--- | :--- | :--- |
| **P1 - Crítico** | Banco de dados indisponível, perda de isolamento multi-tenant, corrupção no razão contábil, falha generalizada de emissão fiscal. | $\le$ 15 minutos | Tech Lead, DevOps/SRE, DPO (se LGPD), CPO |
| **P2 - Alto** | Degradação de latência p95 > 2s, falha no gateway bancário (bloqueio de cobrança PIX/Boleto), fila fiscal represada > 50 docs. | $\le$ 30 minutos | SRE On-call, Engenheiro Backend Especialista |
| **P3 - Médio** | Falha pontual de envio de webhook, alerta de divergência em tanque isolado, falha de importação CNAB em tenant específico. | $\le$ 2 horas | Equipe de Suporte N2 / Engenharia |
| **P4 - Baixo** | Dúvida operacional de usuário, lentidão em relatório não-crítico, ajuste cosmético de interface. | $\le$ 8 horas | Suporte N1 / Atendimento ao Cliente |

---

## 3. Arquitetura de Backup e Recuperação em Ponto no Tempo (PITR)

### 3.1. Componentes da Solução
1. **PostgreSQL Base Backups (pgBackRest / WAL-G):**
   - Snapshot completo semanal (domingo às 02:00 BRT).
   - Snapshot incremental diário (segunda a sábado às 02:00 BRT).
   - Arquivamento contínuo de Write-Ahead Logs (`archive_command`) enviando segmentos de WAL cifrados para bucket S3 com Cross-Region Replication (CRR).
2. **Armazenamento de Mídia e Certificados:**
   - Storage blob com Versioning ativado e Object Lock (WORM - Write Once, Read Many).
   - Certificados digitais A1 cifrados em repouso com chave simétrica via `seguranca_service.py`.

### 3.2. Procedimento de Restauração em Ponto no Tempo (Passo a Passo)

Em caso de corrupção lógica de dados ou falha irrecuperável do host primário:

#### Passo 1: Isolar a Instância Comprometida
```bash
# Encerrar imediatamente conexões de aplicação para evitar escrita concorrente
systemctl stop baros-gunicorn
systemctl stop baros-celery-worker
systemctl stop baros-celery-beat

# Colocar rota pública em página de contingência (HTTP 503 com retry-after)
cp /etc/nginx/contingency.html /usr/share/nginx/html/index.html
systemctl reload nginx
```

#### Passo 2: Definir o Ponto no Tempo Alvo (Target Recovery Time)
Identificar o timestamp exato do incidente (ex: `2026-10-27 14:32:00-03` antes da execução de comando destrutivo).

#### Passo 3: Provisionar Instância e Restaurar WALs
```bash
# Executar restore via pgBackRest com target time
pgbackrest --stanza=baros_prod \
  --type=time \
  --target="2026-10-27 14:32:00-03" \
  --target-action=promote \
  restore

# Iniciar o PostgreSQL restaurado
systemctl start postgresql
```

#### Passo 4: Executar Auditoria de Sanidade Automatizada
Antes de liberar o tráfego aos usuários, rodar o script de auditoria de consistência do Baros:
```bash
python manage.py shell -c "
from core.services.observabilidade_service import verificar_integridade_razao_contabil
resultado = verificar_integridade_razao_contabil()
assert resultado['integro'], f'Inconsistência contábil detectada: {resultado}'
print('Razão íntegro. Verificação concluída com sucesso.')
"
```

#### Passo 5: Restabelecer Aplicação e Validar Conexões
```bash
systemctl start baros-gunicorn
systemctl start baros-celery-worker
systemctl start baros-celery-beat
systemctl reload nginx
```

---

## 4. Teste Trimestral de Restauração (Quarterly Restore Drill)

A cada trimestre (março, junho, setembro, dezembro), a equipe de engenharia e infraestrutura executa o simulacro formal de restauração em ambiente isolado (Sandbox de Disaster Recovery):

1. **Provisionamento:** Ambiente efêmero sem conexão com a internet pública nem com serviços fiscais reais.
2. **Carga do Backup:** Restauração do snapshot do dia anterior + replicação de WALs até as 12:00.
3. **Métricas Aferidas:**
   - Duração da restauração (deve cumprir $\text{RTO} \le 4\text{h}$).
   - Delta temporal do último registro recuperado (deve cumprir $\text{RPO} \le 15\text{min}$).
   - Integridade das partidas contábeis dobradas ($\sum D = \sum C$).
4. **Evidência Formal:** Emissão e arquivamento do relatório assinado pelo Tech Lead e pelo DPO/Auditor Interno em `docs/auditoria/DR_DRILL_YYYY_QX.pdf`.

---

## 5. Contingência e Falha de Serviços Críticos

### 5.1. Indisponibilidade de Gateway Bancário (Cobrança e PIX)
- **Comportamento do Sistema:**
  - O sistema captura a exceção de rede/timeout e chaveia para modo assíncrono.
  - A parcela é mantida com status `AGUARDANDO_SINCRONIZACAO_GATEWAY`.
  - Um job Celery com backoff exponencial (`retry_backoff=True`, `max_retries=10`) reprocessa a solicitação assim que o provedor restabelecer o serviço.
  - Vendas presenciais no caixa de rota do PWA geram comprovante offline e registram cobrança pendente.

### 5.2. Indisponibilidade de Provedor Fiscal (SEFAZ / Gateway Focus / Nuvem Fiscal)
- **Comportamento do Sistema:**
  - NF-e chaveia automaticamente para emissão em Contingência EPEC (Evento Prévio de Emissão em Contingência) ou Contingência FS-DA, quando configurado no tenant.
  - Para entregas de gás, o DANFE simplificado em contingência acompanha a carga com chave única.
  - Ao restabelecer a comunicação, o job `sincronizar_contingencia_fiscal` transmite os arquivos XML e valida as autorizações de forma transparente e ordenada.

### 5.3. Indisponibilidade de Redis (Cache e Message Broker)
- **Comportamento do Sistema:**
  - O backend degrada elegantemente: operações críticas de banco persistem diretamente no PostgreSQL via transações ACID.
  - Fila de mensageria chaveia para *database-backed fallback queue* para eventos prioritários de pedidos e faturamento.
  - Sessões de usuário ativas utilizam fallback de cache em banco se o cluster Redis não responder em 3000 ms.

---

## 6. Procedimento Pós-Incidente (Post-Mortem Blameless)

Todo incidente de severidade P1 ou P2 exige realização de reunião de Post-Mortem em até **48 horas úteis** após a resolução:

1. **Linha do Tempo Factual:** Registro cronológico de todos os alertas, comandos e intervenções efetuadas.
2. **Análise de Causa-Raiz (5 Porquês):** Foco em falhas de processo, monitoramento ou automação (sem culpabilização individual).
3. **Ações Corretivas com Prazo e Dono:** Criação obrigatória de tickets no backlog com prioridade máxima para mitigar recorrência da vulnerabilidade.
4. **Comunicação aos Clientes:** Emissão de SLA Report transparente para tenants afetados com detalhamento das medidas preventivas adotadas.
