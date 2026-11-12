# Sprint U02 — Financeiro: primeiros passos e plano de contas padrão

Leia antes: `CLAUDE.md`, `docs/PROGRESSO.md`, `docs/sprints/00_REGRAS_GERAIS.md` (inteiro), a "FASE 5" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md` e `financeiro/seeds.py`. Depende da U01.
**Branch:** `sprint-u02/financeiro-primeiros-passos` a partir de `fase-2/produtos` (com a U01 mergeada).

## Objetivo
Uma empresa que liga o módulo Financeiro já encontra o plano de contas, os centros de custo e as condições de pagamento padrão, e a tela inicial do Financeiro guia os primeiros passos em vez de mostrar zeros.

## O que está errado (verificado em 12/11/2026)
1. **Plano de contas vazio.** Na Gases Goiás, o Financeiro mostra "Plano de contas 0" e "Contas financeiras ativas 0": nada pode ser lançado. Existe `seed_financeiro_tenant_completo(tenant)` em `financeiro/seeds.py` (linha ~1034: plano de contas, centros de custo e condições de pagamento) e a action `POST /financeiro/api/plano-contas/seed-padrao/` (`financeiro/views.py`, ~linha 197), mas nada os chama ao ligar o módulo, e não há botão na tela.
2. **Indicador enganoso:** sem nenhum lançamento, o cartão mostra "Balancete de verificação: ZERADO (OK)".
3. **Texto técnico para o usuário:** "Razão imutável com encadeamento SHA-256…" no subtítulo da página.
4. **Confirme** se o menu e a tela do Financeiro aparecem para usuário comum de empresa sem o módulo (o superusuário vê tudo por decisão do dono; o usuário comum não deveria).

## Escopo
- **Seed ao ligar o módulo:** quando o módulo `financeiro` é ligado para uma empresa (backoffice `/baros-admin/` → Empresas → Módulos, e no onboarding), rode `seed_financeiro_tenant_completo` (idempotente: rodar duas vezes não duplica).
- **Empresas que já têm o módulo e estão sem plano:** migração de dados (ou comando de gerenciamento documentado nas Notas de deploy) que aplica o seed só onde o plano de contas está vazio.
- **Estado vazio "Primeiros passos"** no topo do Financeiro enquanto faltar algo: (1) plano de contas, (2) uma conta bancária ou caixa, (3) condições de pagamento — cada item com o estado e a ação. Botão "Aplicar plano de contas padrão" só para ADMIN, com `Baros.confirmar`, chamando o seed.
- **Balancete sem lançamentos:** o cartão mostra "Sem lançamentos no período", não "ZERADO (OK)".
- **Textos em linguagem simples** no cabeçalho do Financeiro (sem SHA-256, sem "Sprint").
- Não é o redesign do Financeiro (Sprints 09 a 11): mexa só no cabeçalho, nos cartões e no estado vazio.

## Decisões pendentes
- O plano de contas padrão de `financeiro/seeds.py` é premissa: registre no relatório que precisa ser validado pelo contador.

## Testes
- [ ] **Falha antes:** ligar o módulo financeiro de uma empresa (pelo serviço usado no backoffice) cria o plano de contas, os centros de custo e as condições de pagamento; ligar de novo não duplica.
- [ ] **Falha antes:** com zero lançamentos, o resumo do balancete devolve o estado "sem lançamentos".
- [ ] A action `seed-padrao` só aceita ADMIN (e superusuário); outros papéis → 403; empresa sem o módulo → 403.
- [ ] A migração/comando aplica o seed só em empresa com módulo ativo e plano vazio.
- [ ] Usuário comum de empresa sem o módulo não vê o item Financeiro no menu e recebe 403 na tela.

## Critérios de aceite
- [ ] No navegador (cópia do banco), console sem erros: ligar o módulo numa empresa sem plano → a tela do Financeiro mostra o plano aplicado e os próximos passos.
- [ ] Definição de pronto (seção 9).

## Fora do escopo
Redesign das abas do Financeiro (Sprint 09) e regras contábeis novas.
