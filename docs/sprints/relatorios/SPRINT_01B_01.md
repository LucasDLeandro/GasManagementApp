# Relatório da Entrega 01B.01 — Monitor de TV Operacional

**Data:** 12/11/2026  
**Branch:** `sprint-01b.01/monitor`  
**Base:** `sprint-01b.00/historico-status` (commit `007c1fc`)  
**Status:** Revisão 1 Concluída com Sucesso (Aguardando aprovação do dono para iniciar a Entrega 01B.02)

---

## 1. O que foi feito

### Backend de Gestão e Persistência
- **Modelo `core.PainelMonitor` (`TenantAwareModel`):**
  - Campos:
    - `nome`: CharField(100) descritivo (ex.: "TV Expedição / Pátio").
    - `filial`: FK opcional para `core.Filial` (`on_delete=models.SET_NULL`).
    - `token`: CharField(64) único, indexado (`db_index=True`), gerado por padrão via `secrets.token_urlsafe(32)`. Garante que nenhum identificador sequencial (ID) seja exposto externamente.
    - `ativo`: BooleanField(default=True) para controle de revogação imediata.
    - `mostrar_nomes_clientes`: BooleanField(default=True) para conformidade e privacidade visual.
    - `tempo_alerta_min`: PositiveIntegerField(default=30).
    - `tempo_critico_min`: PositiveIntegerField(default=60).
    - `secoes`: JSONField(default=dict, blank=True) para ativação seletiva de blocos visuais.
    - `ultimo_acesso_em`: DateTimeField(null=True, blank=True), atualizado com taxa máxima de 1 vez por minuto.
    - `criado_por`: FK para o usuário autenticado que cadastrou o painel.
    - `criado_em`: DateTimeField auto_now_add.
  - Migração: `core/migrations/0013_painelmonitor.py`.
  - Reversão do campo `Tenant.modulos_ativos`: migração 0014 excluída e banco revertido em `0013_painelmonitor`, preservando as flags canônicas do plano/tenant como fonte única da verdade.

### Serviços de Negócio (`core/services/painel_monitor.py`)
- `gerar_token_painel() -> str`: geração criptográfica de 32 bytes url-safe.
- `regenerar_token_painel(painel) -> str`: invalida o cache do token anterior (`cache.delete`), gera novo token e persiste o modelo.
- `revogar_painel(painel) -> bool`: desativa o painel (`ativo=False`) e invalida o cache de dados.
- `montar_dados_painel(painel) -> dict`:
  - **Zero `except Exception: pass`:** eliminados todos os tratamentos genéricos de exceção (Regra 3.9). Erros em campos inexistentes falham testes abertamente.
  - **Isolamento Fail-Closed:** consultas com `.unscoped.filter(tenant=painel.tenant, ...)` impedem vazamento de informações entre empresas.
  - **Desempenho Otimizado (<= 15 queries):**
    - Vendas ativas em aberto recuperadas em lote único com `select_related('cliente')`.
    - Histórico de transições recuperado em lote único (`HistoricoStatusVenda.unscoped.filter(venda_id__in=venda_ids)`), eliminando o problema de N+1 queries.
    - Contagens de pátio consolidadas em consulta condicional única (`aggregate(cheios=Count(...), vazios=Count(...), reteste_vencido=Count(...), bloqueios_sanitarios=Count(...))`).
    - Cache do catálogo de gases químicos (`catalogo_gases_quimicos`, 300s) evitando query redundante.
  - **Privacidade Estrita (LGPD):**
    - Zero campos financeiros no JSON: nenhum valor monetário (R$), preços, faturamentos, limites de crédito, nem motivos de bloqueio.
    - Zero dados de contato: nenhum telefone, e-mail, CNPJ, CPF, logradouro completo ou CEP.
  - **Mascaramento de Clientes:**
    - Quando `mostrar_nomes_clientes=False`, o campo `cliente` exibe exclusivamente `f"{bairro} - {cidade}"` e o número do pedido.
  - **Respeito aos Módulos SaaS Ativos:**
    - Seção `fabrica` (fila de rampa, inspeções, quarentena e tanques) só é incluída se `is_modulo_ativo(tenant, 'envase')` for verdadeiro.
    - Seção `esteira` só é incluída se `is_modulo_ativo(tenant, 'distribuicao')` for verdadeiro (mapeado para `logistica` ou `vendas`).
  - **Tempo na Etapa com Níveis Semânticos:**
    - Tempo calculado a partir de `desde_quando_no_status` (01B.00).
    - Classificação semântica: `normal` (< 30 min), `alerta` (>= 30 min) e `critico` (>= 60 min).
  - **Campos Operacionais e Limitações Arquiteturais Mapeadas:**
    - *Bloqueio Sanitário:* `Cilindro.unscoped.filter(tenant=tenant, bloqueio_sanitario=True).exclude(status='BAIXADO')`.
    - *Recalls Abertos:* `RecallCampanha.unscoped.filter(tenant=tenant, status__in=['ABERTO', 'HOMOLOGADO_RT', 'EM_NOTIFICACAO'])`.
    - *Inspeções Pendentes:* Cilindros `VAZIO_TRIAGEM` sem inspeção aprovada recente (últimos 7 dias), resolvido em uma única query com exclusão na relação reversa `inspecoes_pre_envase`.
    - *Lotes em Quarentena:* `LoteEnvase.unscoped.filter(tenant=tenant, status_qualidade='QUARENTENA')`.
    - *Tanques Criogênicos:* `nome = f"{t.codigo} - {t.descricao}" if t.descricao else t.codigo`, com cálculo percentual e alerta de nível baixo quando `< 20.0%`.
    - *Recolhas Previstas:* Removido `recolhas_previstas_hoje` da estrutura `retornos`. No GasManagementApp, recolhas ocorrem por bipagem em campo no ato da entrega (full-for-empty), sem agendamento prévio individual. Mantido `vazios_triagem`.
    - *Cilindros e Filial:* O modelo `Cilindro` não possui FK `filial`. Painéis vinculados a uma filial consolidam o pátio com o tenant inteiro, sem gerar erro 500.
    - *Pátio × Demanda por Gás:* Agrupamento individual por gás comparando cheios disponíveis no pátio com quantidades pedidas nos pedidos abertos (`Pendente`, `Em Separação`) com `prazo_entrega <= hoje` (ou sem prazo), suportando tanto itens com `sku` quanto `produto` legado. Cada entrada possui `gas`, `cheios_disponiveis`, `quantidade_pedida`, `saldo` e `em_falta`.

### Rotas e Views Públicas do Monitor
- `path('painel/<str:token>/', PainelMonitorView.as_view(), name='painel_monitor')`:
  - Rota HTML pública sem necessidade de login.
  - Busca `PainelMonitor` ativo pelo token. Token inexistente ou inativo resulta em HTTP 404.
  - Header de resposta: `X-Robots-Tag: noindex, nofollow`.
- `path('painel/<str:token>/dados/', PainelMonitorDadosAPIView.as_view(), name='painel_monitor_dados')`:
  - Rota JSON pública para atualização assíncrona.
  - **Revogação Imediata:** resolução do painel (`token=token, ativo=True`) ANTES de consultar o cache de dados. Se revogado ou inativo, responde 404 de imediato, mesmo com cache quente.
  - **Rate Limiting / Throttle:** limite de 12 requisições por minuto por token via cache (`rl_monitor_{token}`). Excedente recebe HTTP 429 com mensagem JSON.
  - **Atualização Throttled de `ultimo_acesso_em`:** gravada no banco no máximo 1 vez a cada 60 segundos.
  - Header de resposta: `X-Robots-Tag: noindex, nofollow`.

### Gestão Administrativa em Configurações
- ViewSet `PainelMonitorViewSet` registrado em `/inicio/api/paineis/`.
- Permissões: `[IsAuthenticated, IsTenantAdminOrGerente]`. Papéis VENDEDOR e MOTORISTA recebem HTTP 403 Forbidden.
- Actions: `revogar` e `regenerar_token`.
- Interface administrativa integrada na aba "Monitores de TV (Operacional)" em `templates/core/integracoes.html` e manipulada via `core/static/core/js/integracoes.js`.

### Frontend do Monitor para TV
- `core/templates/core/painel_monitor.html`: HTML semântico sem nenhum estilo inline (`style="..."`).
- `core/static/core/css/painel_monitor.css`: tema escuro de alto contraste otimizado para TVs (distância de 3 a 4 metros). Fontes grandes (24px corpo, 44px a 72px números), sem scroll vertical (`overflow: hidden`). Pílulas de demanda por gás (`.patio-gas-pill`) com destaque crítico quando em falta.
- `core/static/core/js/painel_monitor.js`:
  - Atualização periódica automática a cada 30 segundos via `fetch`.
  - Relógio digital em tempo real (HH:MM:SS) e indicador "Atualizado há X s".
  - Banner de desconexão: aviso "SEM CONEXÃO — dados de HH:MM" se a API falhar por mais de 2 minutos.
  - Fullscreen API e Screen Wake Lock API integradas.
  - **Segurança Estrita de DOM:** uso exclusivo de `document.createElement`, `classList` e `textContent` (zero `innerHTML` dinâmico).

---

## 2. Testes Automatizados (15 Testes — 100% Aprovados)

Foram executados todos os 15 testes de `core/tests/test_sprint01b_01_monitor_tv.py`:
1. `test_01_token_invalido_ou_painel_inativo_retorna_404`: PASSED
2. `test_02_isolamento_multitenant_token_empresa_a_nao_mostra_dados_empresa_b`: PASSED
3. `test_03_ausencia_total_de_dados_financeiros_e_contato_varredura_recursiva`: PASSED
4. `test_04_mostrar_nomes_clientes_false_mascara_para_bairro_cidade`: PASSED
5. `test_05_rate_limit_throttle_por_token_retorna_429`: PASSED
6. `test_06_secoes_respeitam_modulos_fabrica_e_esteira`: PASSED
7. `test_07_tempo_na_etapa_calculado_com_historico_01b00_e_cores_alerta`: PASSED
8. `test_08_sem_n_mais_um_e_cache_15s`: PASSED
9. `test_09_gestao_paineis_rbac_apenas_admin_e_gerente`: PASSED
10. `test_10_revogacao_e_regeneracao_de_token`: PASSED
11. `test_11_seguranca_frontend_static_scan_sem_innerhtml_e_sem_estilos_inline`: PASSED
12. `test_12_dados_reais_por_secao_diferentes_de_zero`: PASSED
13. `test_13_painel_com_filial_responde_200_sem_erro_no_patio`: PASSED
14. `test_14_patio_demanda_por_gas_com_sku_e_produto_legado`: PASSED
15. `test_15_revogacao_imediata_mesmo_com_cache_quente`: PASSED

**Suíte Completa:** 739 passed em 190.63s (zero regressões).

---

## 3. Estrutura de Campos do JSON do Monitor (`/painel/<token>/dados/`)

```json
{
  "nome": "TV Galpão Principal",
  "empresa": "Distribuidora de Gases Modelo",
  "gerado_em": "2026-11-12T13:10:00.000000+00:00",
  "tempo_alerta_min": 30,
  "tempo_critico_min": 60,
  "esteira": {
    "a_separar": [
      {
        "id": 101,
        "numero": "PED-00101",
        "cliente": "Hospital Municipal ou Bairro - Cidade",
        "bloqueado": false,
        "minutos_na_etapa": 15,
        "nivel_alerta": "normal",
        "itens": [
          {"gas": "O2-MED", "quantidade": 10.0}
        ]
      }
    ],
    "em_separacao": [],
    "faturada": [],
    "em_rota": [],
    "concluidos_hoje": 12
  },
  "patio_demanda": {
    "cheios_disponiveis": 45,
    "quantidade_pedida": 20,
    "saldo": 25,
    "em_falta": false,
    "gases": [
      {
        "gas": "O2-MED",
        "cheios_disponiveis": 15,
        "quantidade_pedida": 20,
        "saldo": -5,
        "em_falta": true
      },
      {
        "gas": "AR-IND",
        "cheios_disponiveis": 30,
        "quantidade_pedida": 0,
        "saldo": 30,
        "em_falta": false
      }
    ]
  },
  "retornos": {
    "vazios_triagem": 18
  },
  "alertas": {
    "reteste_vencido_patio": 1,
    "bloqueios_sanitarios": 1,
    "recalls_abertos": 1
  },
  "fabrica": {
    "inspecoes_pendentes": 2,
    "lotes_quarentena": 1,
    "tanques": [
      {
        "nome": "TQ-01 - Tanque O2 Principal",
        "gas": "O2-MED",
        "percentual_nivel": 18.0,
        "alerta_nivel_baixo": true
      }
    ]
  }
}
```

---

## 4. Checklist da Definição de Pronto

- [x] Branch `sprint-01b.01/monitor` criada a partir de `sprint-01b.00/historico-status`.
- [x] Modelo `PainelMonitor` com token de 32 bytes url-safe, sem expor ID sequencial.
- [x] Rotas `/painel/<token>/` e `/painel/<token>/dados/` públicas com cabeçalho `X-Robots-Tag: noindex, nofollow`.
- [x] Token inválido ou painel inativo responde HTTP 404 (nunca 403).
- [x] Isolamento multi-tenant estrito (testado empresa A vs B).
- [x] JSON sem nenhum valor em R$ nem dado de contato pessoal (varredura recursiva automatizada).
- [x] Mascaramento de cliente para bairro/cidade quando `mostrar_nomes_clientes=False`.
- [x] Rate limit / throttle por token (12 req/min) respondendo HTTP 429.
- [x] Seção Fábrica respeita módulo `envase`; Esteira respeita módulo `distribuicao`.
- [x] Tempo na etapa pelo histórico de status com classes `normal`, `alerta` e `critico`.
- [x] Otimização de performance: máximo de 15 queries por atualização e validação pré-cache imediata de token.
- [x] RBAC de gestão de painéis em Configurações restrito a ADMIN e GERENTE (Vendedor e Motorista recebem 403).
- [x] Frontend para TV com dark mode, fontes grandes, zero estilos inline e zero `innerHTML` dinâmico.
- [x] Remoção de todos os `except Exception: pass` de `core/services/painel_monitor.py`.
- [x] Correção dos modelos e campos: `Cilindro.bloqueio_sanitario`, `RecallCampanha.status`, `LoteEnvase.status_qualidade`, tanques com código/descrição e percentual.
- [x] Pátio × Demanda detalhado por gás, com suporte a `sku` e produtos legados.
- [x] Reversão do campo `Tenant.modulos_ativos` e migração 0014, mantendo as flags do plano como única verdade.
- [x] Revogação imediata pré-cache com teste dedicado de 404 instantâneo.
- [x] Suíte de testes completa verde (739 passed).
- [x] `git status` limpo e pronto para commit.
