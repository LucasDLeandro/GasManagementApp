# Progresso do Baros

Arquivo curto e atualizado a cada sprint (pelo agente, no fim da sprint, e pelo dono quando fizer merge ou deploy). Para o histórico completo, veja `docs/sprints/relatorios/` e `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.

## Onde estamos (12/11/2026)
- Fases 0 e 1 concluídas; Fase 2 (Produtos) em andamento na branch `sprint-01b.01/monitor`.
- Sprint 01B dividida em 3 entregas (01B.00, 01B.01, 01B.02).
- Entregas 01B.00 e 01B.01 concluídas; **próxima entrega:** `01B.02 Home: fila por papel, visão de gestão, limpeza e dados de exemplo` na branch `sprint-01b.02/home-gestao`.

## Ambiente de teste (AWS)
- EC2 t3.small, Ubuntu 24.04, Python 3.14, gunicorn + nginx + HTTPS (Let's Encrypt), SQLite, `DEBUG=False`.
- Endereço: `https://3-146-201-236.sslip.io/`. Código em `/home/ubuntu/baros` (clone da branch `fase-2/produtos`); serviço `baros` (systemd).
- Usado por um Responsável Técnico real (usuário com papel `RESPONSAVEL_TECNICO` na empresa de demonstração "Oxigênio Brasília").
- Atualizado pelo dono a partir de branches revisadas. O agente não tem acesso.

## Sprints
| Sprint | Status | Branch | Relatório |
|---|---|---|---|
| 01.00 Lotes e CQ | concluída | `sprint-01.00/lotes-cq` | `docs/sprints/relatorios/SPRINT_01_00.md` |
| 01.01 Ativos e drawer | concluída | `sprint-01.01/ativos-drawer` | `docs/sprints/relatorios/SPRINT_01_01.md` |
| 01.02 Etiquetas | concluída | `sprint-01.02/etiquetas` | `docs/sprints/relatorios/SPRINT_01_02.md` |
| 01B.00 Histórico de status | concluída | `sprint-01b.00/historico-status` | `docs/sprints/relatorios/SPRINT_01B_00.md` |
| 01B.01 Monitor de TV | concluída | `sprint-01b.01/monitor` | `docs/sprints/relatorios/SPRINT_01B_01.md` |
| 01B.02 Home de gestão | a fazer | `sprint-01b.02/home-gestao` | — |
