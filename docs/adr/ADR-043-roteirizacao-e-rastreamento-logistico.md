# ADR-043: Roteirização com Restrições Reais, Validação de Carga Perigosa e Rastreamento Seguro (F-34, F-36, F-40)

## Status
Aprovado e Implementado (Sprint 12A)

## Contexto
A operação de distribuição de gases do ar e gases combustíveis lida com restrições operacionais complexas, risco regulatório de transporte de produtos perigosos (ANTT 5.998/22 e NBR 14619) e segurança física dos motoristas e cargas contra sinistros e roubo. Três falhas arquiteturais prévias foram identificadas e corrigidas nesta sprint:

1. **F-34 (Rastreio Público Inseguro e Exposição de Rotas):**
   - Links de rastreio públicos não podem expor dados pessoais do motorista (LGPD) nem revelar a localização exata do caminhão de entrega enquanto a rota estiver em andamento distante do destinatário, sob risco grave de facilitação de roubo de carga.
   - Links públicos sem data de expiração ou revogação permanecem acessíveis indefinidamente.

2. **F-36 (Roteirização com Restrições Reais e Motor de Rota):**
   - Roteirização ingênua (apenas menor distância geométrica) ignorava a capacidade de peso do veículo, limites físicos por tipo de cilindro (ex: max 20 T50 em VUC), janelas de atendimento por parada (`janela_inicio`, `janela_fim`), tempo de serviço e paradas travadas manualmente pelo despachante.
   - Dependência exclusiva de serviços externos (OSRM/OpenRouteService) causava falhas durante indisponibilidades de rede.

3. **F-40 (Migração Encadeada IndexedDB no PWA de Campo):**
   - O armazenamento offline de coordenadas GPS precisa ser resiliente e estruturado, descartando pontos com baixa precisão (> 100m) e sincronizando lotes de até 200 pontos de forma estritamente idempotente.

## Decisão

### 1. Motor de Roteirização e Fallback Local 2-Opt (F-36)
- Definida a porta de integração `RoteirizadorPort` com o adaptador padrão `LocalNearestNeighbor2OptAdapter`.
- O algoritmo local calcula a matriz de distâncias via fórmula Haversine, respeitando:
  - Capacidade máxima de carga do veículo (kg).
  - Janelas horárias de atendimento (`janela_inicio`, `janela_fim`).
  - Tempo médio de descarga por parada.
  - Paradas com ordenação travada pelo despachante (`travada=True`).
- A saída é estritamente determinística para os mesmos parâmetros de entrada.

### 2. Validação Regulatória de Carga e Liberação Auditada
- Toda saída para rota (`EM_ROTA`) exige execução do serviço `validar_carga(entrega)`.
- A validação bloqueia despacho se:
  - Peso total (gás + tara) exceder a capacidade do veículo.
  - Quantidade de cilindros por tipo exceder a capacidade de berço `CapacidadeVeiculoTipoCilindro`.
  - Houver incompatibilidade química entre classes de risco (ex: Classe 2.1 Inflamáveis × Classe 5.1 Oxidantes).
  - Documentos obrigatórios (CNH, MOPP do motorista; CIV, CIPP do veículo) estiverem vencidos.
- Em situações excepcionais autorizadas por gerência/diretoria, a liberação é formalmente auditada via `LiberacaoCarga` com a permissão `logistica.liberar_carga_bloqueada` e motivo detalhado obrigatório.

### 3. Rastreamento Público com Janela de Privacidade Anti-Roubo (F-34)
- Link público `/rastreio/<uuid:token>/` acessível unicamente via `TokenRastreio` efêmero, com expiração automática após a conclusão do ciclo de entrega.
- **Janela de Privacidade:** A posição GPS do caminhão no mapa SÓ se torna visível ao cliente destinatário quando:
  - A parada estiver `A_CAMINHO` ou `CHEGOU`, OU
  - Faltarem no máximo 3 paradas pendentes para o seu endereço, OU
  - O horário atual estiver a menos de 60 minutos do ETA estimado.
- O nome e telefone do motorista NUNCA são expostos; a placa do veículo é mascarada (ex: `ABC-***1`).
- Cabeçalhos `X-Robots-Tag: noindex, nofollow` em todas as respostas públicas e rate-limiting por IP (max 60 req/min).

### 4. Telemetria Offline-First no IndexedDB (F-40)
- Constante `DB_VERSION` do `offline_sync.js` incrementada de `8` para **`9`**.
- Store `gps_tracking_queue` com índices em `timestamp`, `entrega_id` e `sequencia`.
- Pontos com precisão > 100m são sumariamente descartados.
- Sincronização em lotes de até 200 pontos com ingestão idempotente por chave composta `(tenant, entrega, sequencia, client_uuid)`.
- Pontos antigos (> 90 dias) consolidados na tabela `TrajetoEntrega` com polilinha comprimida, mantendo tempo de resposta < 300 ms.

## Consequências
- Frotas operam em total conformidade com as resoluções da ANTT e normas ABNT de produtos perigosos.
- Rastreamento seguro sem vulnerabilidade de espionagem ou roubo de carga.
- Despacho logístico no Kanban com otimização determinística instantânea e fallback offline.
