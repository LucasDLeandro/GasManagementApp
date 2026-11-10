# Baros (GasManagementApp)

SaaS B2B multi-tenant para empresas de **envase e distribuição de gases** industriais e medicinais: ciclo de vida de cada cilindro, envase com rastreabilidade sanitária (ANVISA), vendas, entregas e frota, cobrança de estadia (comodato), financeiro, fiscal, portal do cliente final e backoffice para os donos do SaaS.

Stack: **Python 3.14, Django 6.0, DRF**, SQLite em desenvolvimento (PostgreSQL previsto para produção), Celery/Redis previstos. Front em templates Django + JS puro, sem build.

## Leia antes de mudar qualquer coisa
| Documento | Para quê |
|---|---|
| `docs/GUIA_MODULOS_BAROS.md` | O que cada módulo faz e seus fluxos (modelos, serviços, telas) |
| `docs/PLANO_CORRECAO_E_EVOLUCAO.md` | Plano em fases, com o **status** do que já foi feito |
| `docs/DESIGN_SYSTEM.md` | Regras de interface (stepper, estados, temas, `window.Baros`) |
| `docs/sprints/00_REGRAS_GERAIS.md` | Regras obrigatórias de backend, frontend e testes, incluindo erros que já aconteceram |
| `docs/PROGRESSO.md` | Onde estamos, próxima sprint e ambiente de teste na AWS |
| `docs/sprints/README.md` | Ordem das sprints (01.00, 01.01, 01.02, 01B, 02 a 16) e formato (`_MODELO_SPRINT.md`) |
| `docs/DECISOES_PENDENTES.md` | Premissas de negócio, fiscais e sanitárias já adotadas |
| `docs/ANALISE_SISTEMA_2026-10-27.md` | Raio-X inicial do sistema |

## Rodar o projeto
```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe populate_db.py        # dados de exemplo (pode rodar de novo, não duplica)
.venv/Scripts/python.exe manage.py runserver
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider   # suíte completa, ~5 min, precisa ficar verde
```
- **Nesta estação o ambiente virtual é `venv/` (Python 3.13)**: troque `.venv` por `venv` nos comandos acima. O servidor de teste usa Python 3.14.
- Definição de pronto de toda sprint: seção 9 de `docs/sprints/00_REGRAS_GERAIS.md`.
- O `.env` **não** está no git (SECRET_KEY, DEBUG, superusuário, banco): copie-o de outra máquina ou crie a partir das chaves usadas em `config/settings.py`.
- `db.sqlite3` e `media/` também não estão no git.
- Rotas: app da distribuidora em `/inicio/`; backoffice dos donos em `/baros-admin/` (superusuário + MFA TOTP obrigatório; o 1º acesso cadastra o autenticador); portal do cliente em `/portal-b2b/`.

## Git
- Branches: `main` (antiga) ← `fase-0/estabilizacao` ← `fase-1/backoffice` ← **`fase-2/produtos` (atual, a mais recente)**. Nenhuma foi mergeada na `main` ainda.
- Um commit por tarefa, com mensagem em português (`feat(app): ...`, `fix(app): ...`). Não fazer push nem merge sem o dono pedir.

## Onde estamos (atualizado em 10/11/2026)
- **Fase 0 (estabilização):** concluída. Código todo versionado, 10 testes que falhavam corrigidos, MFA do backoffice, máquina de estados da venda, Design System v1.
- **Fase 1 (backoffice):** concluída. Empresas, onboarding em etapas, módulos, assinatura, planos, faturas SaaS, suporte (break-glass) e auditoria.
- **Fase 2 (Produtos):** em andamento.
  - Feito: catálogo (gases, modelos, SKUs) e cadastro de cilindro (bloco 2.0); recebimento de fornecedor em etapas; modais do cilindro; rampa como estação de pátio; Recall ANVISA reescrito, com a campanha avançando até "Concluída".
  - Falta: Sprint 01.00 em diante (`docs/sprints/`), começando por Lotes/CQ (liberação pelo RT), depois Ativos e etiquetas.
- Próximos passos planejados: as sprints de `docs/sprints/`, na ordem do `README.md` de lá: 01 → **01B (painéis: monitor de TV e home de gestão)** → 02 a 15 → 16 (laboratório de CQ, que pode ser antecipada se o primeiro cliente for envasadora medicinal).

## Decisões do dono que não devem ser revertidas sem perguntar
- **Superusuário entra em qualquer empresa livremente** pelo seletor da topbar. O break-glass é um acesso *registrado* opcional (decidido em 27/10/2026).
- **IN 129:** na rampa, o checklist pré-envase nasce **pendente** (antes nascia "conforme"); concluir o envase exige a inspeção completa ou a declaração "Conferi todos".
- **Recall:** clientes só são notificados depois da homologação pelo RT; o status da campanha não muda por PATCH.
- **Cancelar uma venda já faturada** fica bloqueado até existir o estorno (Sprint 06).
- **Gateway fiscal e PSP de produção ainda não foram escolhidos**; a Sprint 12 depende disso.
- **Home com módulos:** empresa sem o módulo financeiro vê uma visão básica de gestão (vendas e patrimônio), sem números financeiros zerados; contas a receber, inadimplência e caixa só com o módulo (decidido em 10/11/2026).
- **Monitor de TV** abre por link com token, sem login, e nunca mostra valores em R$ nem dados de contato.

## Armadilhas já conhecidas (detalhes em `docs/sprints/00_REGRAS_GERAIS.md`)
- Nunca fazer consulta com escopo de tenant no import de um módulo (ex.: `queryset=Model.objects.all()` no corpo de um serializer). Isso derruba o projeto inteiro com `TenantNotSet`.
- Todo ViewSet registrado em router precisa de `TenantViewSetMixin` (há um teste que confere).
- Dados de cadastro nunca vão para `innerHTML`; números em `<input type="number">` precisam de `|unlocalize`.
- Testes não podem escrever em arquivos versionados nem no banco de desenvolvimento.
- No banco de desenvolvimento, o **módulo de envase está desligado** em todas as empresas: Rampa, Lotes e Recall só aparecem depois de ligá-lo em `/baros-admin/` → Empresas → Módulos.
