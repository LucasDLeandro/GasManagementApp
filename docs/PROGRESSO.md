# Progresso do Baros

Arquivo curto e atualizado a cada sprint (pelo agente, no fim da sprint, e pelo dono quando fizer merge ou deploy). Para o histórico completo, veja `docs/sprints/relatorios/` e `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.

## Onde estamos (10/11/2026)
- Fases 0 e 1 concluídas; Fase 2 (Produtos) em andamento na branch `sprint-01.00/lotes-cq`.
- Sprint 01.00 concluída; **próxima sprint:** `docs/sprints/S01_01_ativos_drawer.md`.

## Ambiente de teste (AWS)
- EC2 t3.small, Ubuntu 24.04, Python 3.14, gunicorn + nginx + HTTPS (Let's Encrypt), SQLite, `DEBUG=False`.
- Endereço: `https://3-146-201-236.sslip.io/`. Código em `/home/ubuntu/baros` (clone da branch `fase-2/produtos`); serviço `baros` (systemd).
- Usado por um Responsável Técnico real (usuário com papel `RESPONSAVEL_TECNICO` na empresa de demonstração "Oxigênio Brasília").
- Atualizado pelo dono a partir de branches revisadas. O agente não tem acesso.

## Sprints
| Sprint | Status | Branch | Relatório |
|---|---|---|---|
| 01.00 Lotes e CQ | concluída | `sprint-01.00/lotes-cq` | `docs/sprints/relatorios/SPRINT_01_00.md` |
| 01.01 Ativos e drawer | a fazer | `sprint-01.01/ativos-drawer` | — |
| 01.02 Etiquetas | a fazer | `sprint-01.02/etiquetas` | — |
| 01B Painéis | a fazer (dividir antes de começar) | — | — |
