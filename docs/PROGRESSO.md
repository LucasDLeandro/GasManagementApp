# Progresso do Baros

Arquivo curto e atualizado a cada sprint (pelo agente, no fim da sprint, e pelo dono quando fizer merge ou deploy). Para o histórico completo, veja `docs/sprints/relatorios/` e `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.

## Onde estamos (12/11/2026)
- Fases 0 e 1 concluídas; Fase 2 (Produtos) em andamento.
- Sprint 01 (Lotes, Ativos, Etiquetas) e Sprint 01B (Histórico, Monitor, Home de Gestão) concluídas.
- **Sprint 02 (Produtos, telas de Patrimônio) concluída** na branch `sprint-02/produtos-patrimonio`.
- **Sprint 03 (Produtos, retestes hidrostáticos e baixa patrimonial) concluída** na branch `sprint-03/produtos-retestes-baixa`.
- **Próxima entrega:** Sprint 04 (Granel, tanques criogênicos e custos) na branch `sprint-04/produtos-granel`.

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
| 01B.02 Home de gestão | concluída | `sprint-01b.02/home-gestao` | `docs/sprints/relatorios/SPRINT_01B_02.md` |
| 02 Produtos, telas de Patrimônio | concluída | `sprint-02/produtos-patrimonio` | `docs/sprints/relatorios/SPRINT_02.md` |
| 03 Retestes e baixa patrimonial | concluída | `sprint-03/produtos-retestes-baixa` | `docs/sprints/relatorios/SPRINT_03.md` |
| H01 Hotfix tela inicial | concluída | `hotfix-h01/tela-inicial` | `docs/sprints/relatorios/SPRINT_H01.md` |
| U01 Interface: layout, abas e rolagem | concluída | `sprint-u01/interface-layout` | `docs/sprints/relatorios/SPRINT_U01.md` |
| U02 Financeiro: primeiros passos | concluída | `sprint-u02/financeiro-primeiros-passos` | `docs/sprints/relatorios/SPRINT_U02.md` |
| C01 Correções (02, 03, H01, U01, U02) | concluída | `correcao-c01/patrimonio-retestes-financeiro` | `docs/sprints/relatorios/SPRINT_C01.md` |
