# Sprints para o agente de codificação (Antigravity)

Cada arquivo `Sxx_*.md` é uma mensagem pronta: **abra o arquivo, copie o conteúdo inteiro e cole no agente**. Todas as mensagens mandam o agente ler antes `docs/sprints/00_REGRAS_GERAIS.md`, que reúne as regras do projeto e os erros já cometidos que não podem se repetir.

## Ordem

| # | Arquivo | Escopo | Depende de |
|---|---|---|---|
| 01 | `S01_produtos_acabamento_e_etiquetas.md` | Produtos: aba Ativos, drawer, Lotes/CQ, etiquetas com QR real | `fase-2/produtos` |
| 01B | `S01B_paineis_monitor_e_gestao.md` | Histórico de status, **monitor operacional para TV** (link sem login), home com visão de gestão (com e sem módulo financeiro) | 01 |
| 02 | `S02_produtos_patrimonio.md` | Patrimônio: ativos, lotes de aquisição, classes, fabricantes, indenização | 01 |
| 03 | `S03_produtos_retestes_e_baixa.md` | Retestes em lote (envio e retorno com expansão) e baixa patrimonial | 02 |
| 04 | `S04_produtos_granel_tanques_estoque_custos.md` | Tanques, granel, estoque de gás e de produto, custo de envase, **nível do tanque em tempo real, autonomia e saída a granel** | 03 |
| 05 | `S05_produtos_legado_para_sku.md` | Aposentar `Produto` legado em favor de `SkuRecarga` | 04 |
| 06 | `S06_clientes_e_vendas.md` | Vendas redesenhada, estorno de faturamento, ajustes em Clientes | 05 |
| 07 | `S07_logistica_entregas_e_torre.md` | Dividir a tela de logística, montagem de entrega, torre de controle | 06 |
| 08 | `S08_logistica_frota_e_cadastros.md` | Frota, combustível, manutenção, seguros, rentabilidade, cadastros | 07 |
| 09 | `S09_financeiro_estrutura_e_operacao.md` | Dividir o Financeiro e redesenhar a operação diária | 08 |
| 10 | `S10_financeiro_cobranca_credito_caixa.md` | Visão do dono, fluxo de caixa, cobrança e régua, crédito | 09 |
| 11 | `S11_financeiro_contabil_gestao.md` | DRE, orçamento, fechamento do mês, lançamentos manuais, correções de modelagem | 10 |
| 12 | `S12_fiscal_e_unificacao_faturamento.md` | Fiscal completo e absorção do app Faturamento | 11 + **decisão do gateway** |
| 13 | `S13_core_accounts_analytics_menu.md` | Troca de senha obrigatória, códigos de recuperação do MFA, pessoal, home, integrações, filiais, LGPD, analytics, menu | 12 |
| 14 | `S14_app_campo_e_portal_b2b.md` | App de Campo (PWA offline) e Portal B2B | 13 |
| 15 | `S15_go_live.md` | Segurança, PostgreSQL/Celery, performance, manual e UAT | 14 |
| 16 | `S16_laboratorio_controle_qualidade.md` | Laboratório de CQ: especificações por gás, equipamentos e calibração, análises por parâmetro, liberação pelo RT, certificado de análise | 04 + **validação dos parâmetros pelo RT** |

A Sprint 01B fica logo depois da 01 porque a home é a primeira tela que todo usuário vê e o histórico de status que ela cria será usado pela Sprint 06 (vendas) e pela 07 (torre de controle).

A Sprint 16 (laboratório) está depois do go-live, como atualização. Se o primeiro cliente for uma envasadora de gás medicinal, ela deve ser antecipada para antes da 15.

A Sprint 13 tem itens de segurança (troca da senha provisória e recuperação do MFA). Se quiser, ela pode ser antecipada para logo depois da 01: nenhuma das duas depende da outra.

## Como usar
1. Antes da Sprint 01, garanta que a branch `fase-2/produtos` está no GitHub ou que o agente roda nesta mesma pasta.
2. Cole uma sprint por vez. Ao terminar, o agente grava `docs/sprints/relatorios/SPRINT_XX.md`: leia o relatório (principalmente "bugs encontrados" e "o que ficou de fora") antes de colar a próxima.
3. O agente **não** faz push nem merge. Revise a branch, faça o merge e só então siga.
4. Se o agente travar numa decisão de negócio, ele registra no relatório. Responda e peça para continuar.
