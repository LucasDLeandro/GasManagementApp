# Sprint 15: Preparação para produção (go-live)

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), a "FASE 9" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md`, `docs/seguranca/REVISAO_SEGURANCA_OWASP_RBAC.md`, `docs/performance/RELATORIO_PERFORMANCE_SLAS.md`, `docs/runbooks/` e `docs/implantacao/GUIA_IMPLANTACAO.md`.
**Branch:** `sprint-15/go-live` a partir de `sprint-14/campo-b2b`.

## Objetivo
Deixar o sistema pronto para a primeira empresa real: segurança revisada sobre as telas novas, infraestrutura de produção documentada e testada, performance das telas principais e documentação para os usuários.

## Tarefas

### 15.1 Segurança
- Refazer a revisão OWASP de `docs/seguranca/REVISAO_SEGURANCA_OWASP_RBAC.md` sobre as telas das Sprints 01 a 14 e atualizar o documento:
  - XSS: procurar `innerHTML`, `|safe` e `mark_safe` com dado de usuário;
  - CSRF em todos os POSTs;
  - permissões por papel em todos os endpoints de escrita (script ou teste que percorre o router e confere que cada ViewSet com escrita tem permissão além de `IsTenantMember`, ou que está numa lista de exceções justificada);
  - segredos *write-only*;
  - rate limit no login do app, no backoffice e no portal.
- `python manage.py check --deploy` sem avisos com as configurações de produção (HSTS, cookies seguros, `SECURE_*`); documentar as variáveis de ambiente obrigatórias em `.env.example`.
- **CDN:** `grep` por `googleapis`, `unpkg`, `cdnjs` e `jsdelivr` em templates deve dar zero (decisão D5).
- Revisar o acesso livre de superusuário às empresas (decidido em 27/10/2026: continua livre). Confirmar que **toda entrada** de superusuário numa empresa por break-glass fica no `LogAuditoriaSaaS`, e registrar no relatório os riscos remanescentes para o dono decidir.

### 15.2 Infraestrutura
- Configuração de produção com **PostgreSQL gerenciado (RDS, se escolhido pelo dono para produção)** — o PostgreSQL 16 local e a suíte no PostgreSQL já foram concluídos na Sprint D01 —, **Celery + Redis** (tasks e beat em `config/celery.py`), arquivos estáticos (`collectstatic` com `ManifestStaticFilesStorage`, o que dispensa o `?v=` manual; avalie e documente) e media protegida.
- Backup e restauração: seguir `core/services/backup_continuidade_service.py` e os runbooks (incluindo `docs/runbooks/RUNBOOK_MIGRACAO_POSTGRESQL.md`); documentar o teste de restauração.

### 15.3 Performance
- Medir as 10 telas e endpoints mais usados (lista de cilindros, vendas, entregas, receber, DRE, recall) com dados volumosos (crie um comando `popular_carga_teste` que gere, por exemplo, 50 mil cilindros e 200 mil movimentos num banco de teste, **nunca no banco de desenvolvimento do dono**). Corrigir N+1 (`select_related`/`prefetch_related`), índices faltantes e paginação. Atualizar `RELATORIO_PERFORMANCE_SLAS.md` com o antes e o depois.

### 15.4 Documentação e UAT
- Atualizar `docs/treinamento/MANUAL_POR_PERFIL.md` (um capítulo por papel, com as telas novas) e `docs/uat/ROTEIRO_UAT_DISTRIBUIDORAS.md` (roteiro de aceite passo a passo, por módulo).
- Atualizar `docs/GUIA_MODULOS_BAROS.md` com as telas e rotas finais.

## Critérios de aceite
- `check --deploy` limpo; suíte verde em SQLite e em PostgreSQL.
- Documentos de segurança, performance, manual e UAT atualizados.
- Relatório com a lista de riscos que dependem de decisão do dono (pagamento, gateway fiscal, acesso de superusuário).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_15.md`.
