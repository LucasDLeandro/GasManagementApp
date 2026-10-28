# Plano de Correção e Evolução do Baros

**Data:** 27/10/2026 · **Base:** `docs/ANALISE_SISTEMA_2026-10-27.md` e `docs/GUIA_MODULOS_BAROS.md`

Este plano cobre: **(1)** a correção de todos os problemas encontrados na análise e **(2)** a evolução de cada app (redesign + telas faltantes + melhorias). Ele foi feito para ser executado **um módulo por vez**, com um commit (ou PR) por etapa.

**Tamanho das tarefas:** P = poucas horas · M = 1–2 dias · G = 3–5 dias · GG = mais de uma semana.

---

## Regras para toda tarefa (Definição de Pronto)

1. Segue `docs/DESIGN_SYSTEM.md` (criado na Fase 0): stepper para cadastros, cartões de seção, cartões de métrica, abas, CSS/JS próprios do módulo, **zero `alert()`/`confirm()` nativos** e **zero estilos inline novos**.
2. Funciona nos temas claro, escuro e alto contraste, e no celular (largura 375px).
3. Respeita o tenant (404 para dados de outra empresa) e o papel (`Membership.papel`) **também no backend**, não só escondendo o botão.
4. Testes do que mudou + suíte completa verde (`pytest`).
5. Um commit por tarefa ou grupo pequeno, com mensagem descritiva (`feat(produtos): ...`, `fix(vendas): ...`).

---

## Visão geral das fases

| Fase | Nome | Tamanho | Depende de |
|---|---|:---:|---|
| 0 | Estabilização (git, testes, bugs críticos, design system) | G | — |
| 1 | Backoffice Baros | G | 0 |
| 2 | Produtos (cilindros, envase, sanitário, patrimônio, granel) | GG | 0 |
| 3 | Clientes (ajustes) + Vendas | G | 2 |
| 4 | Logística | GG | 2, 3 |
| 5 | Financeiro | GG | 3 |
| 6 | Fiscal + unificação do Faturamento | GG | 5 + decisão do gateway |
| 7 | Core (home, integrações, perfil), Accounts, Analytics | G | 0 |
| 8 | App de Campo (PWA) e Portal B2B | G | 4 |
| 9 | Go-live: segurança, performance, documentação | M | todas |

As fases 1, 2 e 7 podem andar em paralelo depois da Fase 0, desde que não mexam nos mesmos arquivos.

---

## FASE 0 — Estabilização

**Objetivo:** proteger o código, partir de uma suíte 100% verde e fechar os bugs que afetam dados ou segurança.

### 0.1 Versionamento
| ID | Tarefa | Arquivos | Pronto quando | Tam. |
|---|---|---|---|:---:|
| 0.1.1 | Conferir o `.gitignore`: ignorar `db.sqlite3`, `.coverage`, `media/`, `__pycache__`, `.env` | `.gitignore` | `git status` não lista nenhum desses | P |
| 0.1.2 | Commitar o código atual **separado por app** (core, accounts, clientes, produtos, vendas, logistica, faturamento, financeiro, fiscal, portal_b2b, analytics, docs) | todos | `git status` limpo; ~12 commits descritivos | P |
| 0.1.3 | Criar e configurar o repositório remoto (GitHub privado) e fazer o push | — | Código no remoto | P |
| 0.1.4 | Adotar branches por fase (`fase-1/backoffice`, ...) | — | — | P |

### 0.2 Testes que falham hoje (10)
| ID | Teste | Correção provável | Tam. |
|---|---|---|:---:|
| 0.2.1 | `accounts` › `test_autoatendimento_alterar_senha` | `login(request, user, backend='django.contrib.auth.backends.ModelBackend')` em `accounts/views.py:260` (ou `update_session_auth_hash`) | P |
| 0.2.2 | `cross_tenant` › listagem de `/produtos/api/cilindros/` responde 500 | Investigar a exceção (provável efeito das mudanças no drawer/serializer de cilindros) | M |
| 0.2.3 | `cross_tenant` › `/produtos/api/envases/1/` responde 403 em vez de 404 | Aplicar o filtro de tenant **antes** da checagem de permissão de objeto no `EnvaseViewSet` | P |
| 0.2.4 | `fase5` › ping de webhook com HMAC e latência | Revisar `core/webhooks.py` × teste (assinatura/cabeçalho) | P |
| 0.2.5 | `webhook_shielding` › outbox grava PENDENTE e executa | Revisar o `on_commit` no teste (`captureOnCommitCallbacks`) | P |
| 0.2.6 | `sprint6` › webhooks com HMAC e conclusão de romaneio | Mesma causa provável de 0.2.4 | P |
| 0.2.7 | `sprint8` › `otimizar_ordem_paradas` | Revisar `logistica/services/routing.py` após a Sprint 12A | M |
| 0.2.8 | `sprint8` › sync GPS em lote | Revisar `rastreamento_service.sincronizar_lote_gps` × endpoint | M |
| 0.2.9 | `sprint8` › rastreio público HTML/JSON | Revisar `TokenRastreio` × `Entrega.token_rastreio` (modelo mudou na 12A) | M |
| 0.2.10 | `sprint9c` › versionamento IndexedDB (ADR-040) | Alinhar a versão do banco em `static/js/offline_sync.js` com a ADR | P |
| 0.2.11 | Avisos: datas sem fuso nos testes; paginação sem `ordering` em `logistica.Veiculo` | `timezone.make_aware` nos testes; `ordering` no `Meta` | P |

### 0.3 Bugs críticos encontrados na análise
| ID | Problema | Correção | Tam. |
|---|---|---|:---:|
| 0.3.1 | **MFA do `/baros-admin/` aceita qualquer código** se o superusuário não tiver TOTP (`core/views_baros_admin.py:119-127`) | Sem dispositivo → redirecionar para o fluxo de cadastro do TOTP (Fase 1.1). Nunca autenticar sem `verify_token` válido. Teste cobrindo DEBUG=False | M |
| 0.3.2 | **Venda sem máquina de estados:** `alterar_status` aceita qualquer status, inclusive `BLOQUEADO_FINANCEIRO → Faturada` (**fura o bloqueio de crédito**) e não checa o papel | Criar `TRANSICOES_VENDA` + `vendas/services/status.py::transicionar_venda()`; liberar o bloqueio só via `liberar_bloqueio_venda`; checar o papel | M |
| 0.3.3 | **Baixa de estoque em dobro:** `Faturada` e depois `Finalizada` chamam `baixar_estoque_venda_faturada` duas vezes; o erro é engolido por `except Exception: pass` | Baixar só na transição para `Faturada`; idempotência por `origem_id`; remover o `except` silencioso (logar e falhar) | P |
| 0.3.4 | App `frotas` morto, sem tenant e fora do `INSTALLED_APPS` | Excluir a pasta `frotas/` | P |
| 0.3.5 | `produtos/services.py` + pasta `produtos/services/` unidos por gambiarra (`__path__`) | Transformar em pacote: `produtos/services/__init__.py` reexportando as funções de `services.py` (movido para `services/ciclo_cilindro.py`) | M |
| 0.3.6 | Rotas duplicadas: `analytics` e `fiscal` incluídos duas vezes (`config/urls.py`) | Manter um prefixo por app (`/analytics/`, `/fiscal/`) com `api/` dentro; atualizar o JS | P |

### 0.4 Fundação do redesign
| ID | Tarefa | Pronto quando | Tam. |
|---|---|---|:---:|
| 0.4.1 | Escrever `docs/DESIGN_SYSTEM.md` a partir da tela de `clientes`: tokens de cor, tipografia, espaçamentos, componentes (stepper, cartão de seção, métrica, abas, tabela, drawer, badge, vazio/carregando/erro), regras de formulário (rótulos, máscaras, validação inline, mensagens) | Documento aprovado por você | M |
| 0.4.2 | Extrair os componentes de `clientes/static/clientes/css/index.css` que são genéricos para `core/static/core/css/components.css` | `clientes` continua idêntico | M |
| 0.4.3 | Helper único de diálogos em `core/static/core/js/core.js` (`Baros.confirmar()`, `Baros.avisar()`, `Baros.erro()`) sobre o `sweetalert2` já instalado | Funções documentadas | P |
| 0.4.4 | Helper de formulário em etapas (`Baros.Stepper`) e de chamadas à API (`Baros.api()` com CSRF, tenant e tratamento de erro padrão) | Usado pela tela de clientes | M |
| 0.4.5 | Template parcial padrão: `templates/components/` (`_page_header.html`, `_metric_card.html`, `_empty_state.html`, `_stepper.html`) | — | M |

---

## FASE 1 — Backoffice Baros (`/baros-admin/`)

**Objetivo:** vocês conseguirem operar o SaaS inteiro pela tela, com segurança.

| ID | Tarefa | Detalhe | Tam. |
|---|---|---|:---:|
| 1.1 | **Cadastro e verificação de MFA** | Primeiro acesso: gerar `TOTPDevice` não confirmado → mostrar QR code → confirmar com o código → só então logar. Códigos de recuperação. Tela para trocar o dispositivo | M |
| 1.2 | Layout do backoffice no padrão novo | Base própria (`baros_admin/base.html`) com menu lateral: Dashboard, Empresas, Planos, Faturas SaaS, Suporte, Auditoria | M |
| 1.3 | **Empresas → detalhe da empresa** | Página por tenant: dados, plano, status, módulos, cotas e uso, usuários, faturas, histórico (`LogAuditoriaSaaS`). O botão "Gerenciar" passa a abrir esta página | G |
| 1.4 | **Onboarding em etapas** | Stepper: Empresa → Filial matriz → Plano → Módulos (com dependências de `core/modulos.py`) → Usuário admin → Revisão. Usa `onboarding_tenant` | M |
| 1.5 | **Módulos** | Interruptores com validação de dependência ("Logística requer Vendas") e confirmação | P |
| 1.6 | **Assinatura** | Botões conforme a máquina de estados (TRIAL/ATIVO/SUSPENSO/CANCELADO), motivo obrigatório, reativação de cancelado só com motivo | P |
| 1.7 | **Planos SaaS** | Listar, criar e editar (preço, cotas, módulos incluídos) | M |
| 1.8 | **Faturas SaaS** | Gerar fatura (manual e em lote do mês), marcar como paga/vencida/cancelada, filtro de inadimplentes | M |
| 1.9 | **Suporte (break-glass)** | Iniciar com motivo (mínimo 10 caracteres) → abrir o app como aquele tenant → contador de expiração → encerrar. Lista de acessos ativos e histórico | M |
| 1.10 | **Auditoria SaaS** | Tela de `LogAuditoriaSaaS` com filtros | P |
| 1.11 | Link "Backoffice Baros" no menu do usuário, visível só para superusuário | `base_dashboard.html` | P |
| 1.12 | Testes: acesso negado para não superusuário, MFA obrigatório, IP bloqueado, expiração de 30 minutos | — | M |

**Evolução futura (opcional):** saúde de cada tenant (último acesso, volume de uso, jobs com falha, certificados a vencer, a partir do `observabilidade_service`) e flags de piloto (`rollout_service`) pela tela.

---

## FASE 2 — Produtos

**Objetivo:** o núcleo operacional (cilindro → envase → sanitário → patrimônio → granel) inteiro com telas no padrão novo.

### 2.1 Reestruturação
| ID | Tarefa | Tam. |
|---|---|:---:|
| 2.1.1 | Quebrar `produtos/index.html` (1.061 linhas) em parciais por aba: `_cilindros.html`, `_entradas.html`, `_catalogo.html`, `_rampa.html`, cada uma com seu JS | M |
| 2.1.2 | Mover os 221 estilos inline para `produtos/static/produtos/css/` | M |
| 2.1.3 | Commitar e revisar o drawer de cilindros (`cilindros_drawer.js`), que está modificado e não commitado | P |

### 2.2 Redesign dos formulários existentes
| ID | Formulário | Formato novo | Tam. |
|---|---|---|:---:|
| 2.2.1 | Cadastro de cilindro | Stepper: Identificação (série, QR) → Modelo/Gás → Fabricante/Patrimônio → Propriedade (própria/cliente) → Revisão | M |
| 2.2.2 | Cadastro de SKU de gás | Stepper curto + prévia do preço | P |
| 2.2.3 | Entrada por nota fiscal (fornecedor) | Etapas: NF → bipagem dos cilindros → conferência → confirmação | M |
| 2.2.4 | Bloqueio sanitário | Modal com motivo + RT + confirmação dupla | P |
| 2.2.5 | Retorno de reteste | Formulário com cálculo de expansão permanente e variação de tara ao vivo | M |
| 2.2.6 | Reclassificação de gás | Stepper com homologação da RT | P |
| 2.2.7 | Estorno no ledger | Modal com motivo obrigatório e prévia do efeito | P |
| 2.2.8 | Rampa de envase (batelada) | Tela "estação": bipar → inspeção pré-envase → lote → concluir, com teclas grandes (uso no pátio) | G |
| 2.2.9 | **Recall ANVISA** (`recall_anvisa.html`, 1.211 linhas, 17 `alert`) | Quebrar em: lista de campanhas → detalhe (linha do tempo ABERTO → HOMOLOGADO_RT → EM_NOTIFICACAO → CONCLUIDO) → clientes afetados → dossiê Notivisa | G |

### 2.3 Telas novas (backend já pronto)
| ID | Tela | API | Tam. |
|---|---|---|:---:|
| 2.3.1 | **Patrimônio**: fabricantes, classes de ativo (com contas contábeis), lotes de aquisição, ativos imobilizados | `api/patrimonio/*` | G |
| 2.3.2 | **Retestes**: envios para reteste (lote enviado → retorno), calendário de vencimentos, cilindros vencidos | `api/patrimonio/envios-reteste`, `retestes` | M |
| 2.3.3 | **Baixa patrimonial** e estorno | `api/patrimonio/baixas` | M |
| 2.3.4 | **Tabela de indenização** por modelo/gás | `api/patrimonio/indenizacoes` | P |
| 2.3.5 | **Tanques criogênicos**: cadastro, nível atual, medições, gráfico de boil-off, fechamento de período | `api/tanques`, `api/medicoes-tanque` | G |
| 2.3.6 | **Entradas a granel** (NF × pesagem com alerta de tolerância) | `api/entradas-granel` | M |
| 2.3.7 | **Estoque**: gás (por tanque) e produto acabado (por SKU), com movimentos | `api/estoque-gas/movimentos`, `api/estoque-produto/movimentos` | M |
| 2.3.8 | **Custo por lote de envase** (fechar/estornar, energia da rampa) | `api/custos-lote` | M |
| 2.3.9 | **Lotes de envase**: lista, CQ/laudo, liberação pela RT, etiquetas | `api/lotes` | M |

### 2.4 Melhorias
- Substituir o uso do modelo legado `Produto` por `SkuRecarga` em todo o sistema (vendas, sinistros) e marcar `Produto` como somente leitura. **M**
- Painel "Cilindro 360°" com linha do tempo completa do ledger (já parcialmente no drawer). **M**

---

## FASE 3 — Clientes (ajustes) + Vendas

### 3.1 Clientes
| ID | Tarefa | Tam. |
|---|---|:---:|
| 3.1.1 | Reduzir os 136 estilos inline restantes | P |
| 3.1.2 | **Usuários B2B do cliente**: convidar, mudar o papel, revogar (aba no detalhe do cliente) | M |
| 3.1.3 | **Fechamento de estadia**: tela de fechamento mensal (prévia → fechar → espelho PDF/CSV), ajustes de competência, extravio (lista de candidatos → declarar) | G |
| 3.1.4 | Limite de crédito e promessas do cliente visíveis no detalhe (lê o Financeiro) | M |

### 3.2 Vendas
| ID | Tarefa | Tam. |
|---|---|:---:|
| 3.2.1 | (Depende de 0.3.2) Botões de status só com as transições permitidas | P |
| 3.2.2 | **Nova venda em etapas**: Cliente (com o crédito disponível exibido) → Itens por SKU (preço, estoque) → Entrega (retirada/entrega, data) → Pagamento → Revisão | G |
| 3.2.3 | Pedido bloqueado: banner com o motivo e o botão "Liberar" (papel autorizado + motivo) | P |
| 3.2.4 | Detalhe da venda em drawer: itens, linha do tempo de status, entrega, NF-e, cobrança | M |
| 3.2.5 | Reduzir os 92 estilos inline | P |
| 3.2.6 | Alertas comerciais (`AlertaComercial`) visíveis para o vendedor | P |

---

## FASE 4 — Logística

**Objetivo:** quebrar a maior tela do sistema e completar a torre de controle.

### 4.1 Reestruturação (pré-requisito)
| ID | Tarefa | Tam. |
|---|---|:---:|
| 4.1.1 | Quebrar `logistica/index.html` (3.594 linhas, 110 modais, 648 estilos inline) em **páginas separadas** com submenu: `/logistica/entregas/`, `/frota/`, `/combustivel/`, `/manutencao/`, `/seguros/`, `/rentabilidade/` | G |
| 4.1.2 | Um JS por página; remover o código morto | M |

### 4.2 Redesign
| ID | Tela/formulário | Tam. |
|---|---|:---:|
| 4.2.1 | **Montagem de entrega** em etapas: Vendas → Cilindros → Veículo/Motorista → Validação de carga (ANTT, peso, capacidade) → Ordem das paradas (mapa) → Despachar | G |
| 4.2.2 | **Torre de controle**: mapa com veículos em rota, paradas e ETAs, ao vivo | G |
| 4.2.3 | Cadastro de veículo (já tem stepper: alinhar ao padrão final) | P |
| 4.2.4 | Abastecimento, OS (kanban), plano preventivo, checklist, apólice, sinistro (linha do tempo) no padrão novo | G |

### 4.3 Telas novas
| ID | Tela | Tam. |
|---|---|:---:|
| 4.3.1 | **Motoristas** (CNH, MOPP, vencimentos) e **alocação motorista × veículo** | M |
| 4.3.2 | **Regras de incompatibilidade de carga** (ANTT/NBR 14619) + liberações registradas | M |
| 4.3.3 | **Capacidade veículo × tipo de cilindro** | P |
| 4.3.4 | **Tabelas de frete interno** (por km/parada) | P |
| 4.3.5 | Validações de carga pendentes de aprovação (fila do gerente) | M |

---

## FASE 5 — Financeiro

### 5.1 Reestruturação
| ID | Tarefa | Tam. |
|---|---|:---:|
| 5.1.1 | Quebrar `financeiro/dashboard.html` (1.574 linhas, 25 `alert`) em páginas com submenu: **Visão geral · Receber · Pagar · Bancos · Cobrança · Operação de campo · Contabilidade · Gestão · Configurações** | G |
| 5.1.2 | Migrar `conciliacao.html` e `fechamento_caixa_detalhe.html` para o padrão | M |

### 5.2 Redesign dos formulários existentes
Título a receber/pagar em etapas (Dados → Parcelas → Rateio/Retenções → Revisão), baixa de parcela, transferência, plano de contas (árvore), saldo de abertura (simular → confirmar), despesas de campo e fatura de posto (conferência em lote), caixa de rota (contagem cega). **G**

### 5.3 Telas novas (backend pronto)
| ID | Tela | Tam. |
|---|---|:---:|
| 5.3.1 | **Visão geral do dono**: saldo hoje, a receber/pagar 30 dias, inadimplência, alertas de caixa | M |
| 5.3.2 | **Fluxo de caixa**: realizado + projeção 90 dias em cenários (pessimista/base/otimista) com gráfico | G |
| 5.3.3 | **Cobrança**: configuração do PSP, emissão de boleto/PIX, **régua de cobrança** (editor de etapas e templates), log de envios, consentimentos | G |
| 5.3.4 | **Crédito**: parâmetros, limites por cliente, exposição, promessas de pagamento | M |
| 5.3.5 | **DRE** por competência (com comparação ao orçamento) e exportação | M |
| 5.3.6 | **Orçamento anual** (edição em grade mês × conta, importação CSV, aprovação) | G |
| 5.3.7 | **PDD** (parâmetros, cálculo, baixa de perda) | M |
| 5.3.8 | **Depreciação** (rodar o mês, revisão de vida útil) | M |
| 5.3.9 | **Lançamentos manuais** com aprovação + importação de provisões | M |
| 5.3.10 | **Recorrências** (aluguel, folha, contas fixas) | P |
| 5.3.11 | **Parâmetros** (financeiros, tributários, gestão, crédito) numa página de configurações | M |

### 5.4 Correções de modelagem
- Dois modelos de **Fornecedor** (`financeiro.Fornecedor` e `logistica.Fornecedor` para oficinas) e dois de **preço de combustível** (`financeiro.PrecoReferenciaCombustivel` e `logistica.PrecoCombustivelReferencia`). Unificar com migração de dados. **G**
- `MovimentoConta.baixa` aponta para `faturamento.FaturaCobranca`: rever na Fase 6.

---

## FASE 6 — Fiscal + unificação do Faturamento

**Decisão necessária antes de começar** (ver `docs/DECISOES_PENDENTES.md`, Sprint 11A): gateway fiscal homologado e PSP piloto.

| ID | Tarefa | Tam. |
|---|---|:---:|
| 6.1 | **Unificar:** `fiscal.DocumentoFiscal` passa a ser a única fonte de NF-e; `faturamento.NotaFiscal` vira somente leitura (migrar o histórico); `FaturaCobranca` é substituída pela cobrança do Financeiro (`emitir_cobranca_parcela`); os webhooks passam a apontar para o Fiscal/Financeiro; depois disso, remover o app `faturamento` | GG |
| 6.2 | **Configuração fiscal por filial** (certificado A1 com upload seguro, série, ambiente, alerta de vencimento) | M |
| 6.3 | **Regras tributárias** (lista, editor, aprovação, simulador "qual regra se aplica") | G |
| 6.4 | **Documentos emitidos**: lista com filtros, detalhe (itens, tributos, eventos), DANFE/XML, cancelar, carta de correção | G |
| 6.5 | **Emissão de NF-e de venda** a partir da venda (botão na Venda + fila de rejeitadas) | M |
| 6.6 | **Comodato fiscal**: remessas/retornos e relatório de divergências | M |
| 6.7 | **MDF-e/CT-e**: emitir, encerrar, alerta de MDF-e aberto | M |
| 6.8 | **Notas de entrada**: importar XML → conferir → gerar título a pagar | M |
| 6.9 | **Apuração** mensal e guia | M |
| 6.10 | **Recarga de terceiros** (kanban RECEBIDO → ... → FATURADO) | M |
| 6.11 | **Numeração/inutilização** e **lote de XMLs para o contador** | P |

---

## FASE 7 — Core, Accounts e Analytics

| ID | Tarefa | Tam. |
|---|---|:---:|
| 7.1 | **Home** (`core/home.html`): redesign dos 3 painéis (envase, distribuição, integrado) com cartões de métrica e atalhos por papel | M |
| 7.2 | **Integrações**: webhooks (criar, testar, log de entregas, reenviar), exportação ERP | M |
| 7.3 | **Perfil regulatório e RTs** no padrão novo | P |
| 7.4 | **Filiais**: tela de cadastro (hoje sem tela) | M |
| 7.5 | **Accounts**: lista de pessoal, convite/cadastro em etapas (Dados → Papel/Filial → Dados trabalhistas), meu perfil, troca de senha | M |
| 7.6 | **LGPD**: solicitações de titulares (fila e atendimento) | M |
| 7.7 | **Analytics**: colocar o funil de alertas no menu; redesign; painel de previsão de recompra e risco de não retorno; indicadores executivos | G |
| 7.8 | **Menu lateral**: reorganizar por áreas (Operação, Comercial, Logística, Financeiro, Fiscal, Configurações) e respeitar módulos e papéis | M |

---

## FASE 8 — App de Campo (PWA) e Portal B2B

| ID | Tarefa | Tam. |
|---|---|:---:|
| 8.1 | **App de Campo**: adaptar o design system para mobile (botões grandes, alto contraste ao sol), remover os 246 estilos inline, indicador claro de offline/sincronizando, fila de pendências visível | G |
| 8.2 | Fluxos do motorista: checklist do veículo → carregar → paradas → entrega/recolha → assinatura → despesa de campo → contagem do caixa de rota | G |
| 8.3 | **Portal B2B**: redesign (identidade da distribuidora), meus cilindros, estadia, faturas e 2ª via, laudos, reposição em 1 clique, notificações | G |

---

## FASE 9 — Go-live

| ID | Tarefa | Tam. |
|---|---|:---:|
| 9.1 | Revisão de segurança (`docs/seguranca/REVISAO_SEGURANCA_OWASP_RBAC.md`) refeita sobre as telas novas | M |
| 9.2 | PostgreSQL em produção, Celery + Redis, backups (runbooks em `docs/runbooks/`) | M |
| 9.3 | Performance das telas principais (`docs/performance/`) | M |
| 9.4 | Atualizar o manual por perfil (`docs/treinamento/MANUAL_POR_PERFIL.md`) e o roteiro de UAT | M |

---

## Roadmap futuro (depois das telas)

Itens dos planos que ainda não foram implementados no backend:
- **Telemetria IoT de tanques criogênicos** nos hospitais (MQTT/HTTP) + alerta preditivo de abastecimento (Sprint 7 do plano original).
- **Portal do cliente hospitalar** com laudos e certificados de reteste (parcialmente coberto pelo Portal B2B).
- **API pública para ERPs** com webhooks bidirecionais (hoje só existe a exportação).

---

## Como vamos executar cada módulo

1. Abro uma branch da fase.
2. Faço o inventário detalhado das telas e formulários do módulo e confirmo com você.
3. Implemento na ordem do plano, com testes.
4. Mostro rodando no navegador (claro, escuro e celular).
5. Commit, e passamos para o próximo item.
