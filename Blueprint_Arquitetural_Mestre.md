# 🏗️ Blueprint Arquitetural Mestre - Baros SaaS (Sprints 7 a 10)

**Diretrizes Globais para o Agente de IA (SYSTEM INSTRUCTIONS):**
1. **Multitenancy Estrito:** Todo novo model DEVE herdar de `TenantAwareModel` (ou similar) em `core/models.py`. Toda query DEVE ser filtrada por `.filter(tenant=request.tenant)` (se em services) ou derivada de `self.get_queryset()` em ViewSets.
2. **Sem Bloqueio de Thread (Non-Blocking):** Toda integração externa (SEFAZ, APIs de Mapa, Gateways de Pagamento) DEVE ser processada de forma assíncrona usando **Celery** + **Redis**.
3. **Fail-Closed:** Novas permissões no DRF devem negar o acesso por padrão. Rotas públicas (como rastreio) devem usar UUID `uuid4` como chave de busca, NUNCA `id` sequencial inteiro.

---

## 📦 SPRINT 7: Hub Fiscal & Motor de Cobrança (ERP)

### 7.1. Modelagem de Dados (`faturamento/models.py` ou `vendas/models.py`)
- **`ConfiguracaoFiscalTenant`**: `tenant` (OneToOne), `cnpj_emissor` (CharField 18), `inscricao_estadual` (CharField), `certificado_pfx` (FileField protegido), `senha_certificado` (CharField criptografado), `ambiente` (Choices: `HOMOLOGACAO`, `PRODUCAO`).
- **`NotaFiscal`**: `tenant` (FK), `venda` (FK OneToOne, `null=True`), `fatura_estadia` (FK OneToOne, `null=True`), `chave_acesso` (CharField 44, `unique`), `status` (Choices: `PENDENTE`, `PROCESSANDO`, `AUTORIZADA`, `REJEITADA`, `CANCELADA`), `xml_url` (URLField), `danfe_url` (URLField), `motivo_rejeicao` (TextField), `data_emissao` (DateTimeField).
- **`FaturaCobranca`**: `tenant` (FK), `venda`/`estadia` (FKs), `gateway_id` (CharField), `status` (Choices: `ABERTA`, `PAGA`, `VENCIDA`, `CANCELADA`), `qr_code_pix` (TextField), `linha_digitavel` (CharField), `link_pagamento` (URLField), `data_vencimento` (DateField).

### 7.2. Processamento Assíncrono (`faturamento/tasks.py`)
- Criar a task Celery: `@shared_task(bind=True, max_retries=3) def emitir_nfe_task(self, tenant_id, entidade_id, tipo_entidade):`.
  - A task deve buscar a `ConfiguracaoFiscalTenant`.
  - Montar o payload JSON padrão da API fiscal (ex: Focus NFe).
  - Atualizar o `status` da `NotaFiscal` para `PROCESSANDO` e, após resposta da API, para `AUTORIZADA` ou `REJEITADA`.
  - Em caso de timeout da API (HTTP 504), usar `self.retry(countdown=60)`.

### 7.3. Segurança de Webhooks (`faturamento/views.py`)
- Criar `WebhookGatewayPagamentoView(APIView)` e `WebhookNFeView(APIView)`.
- **Proteção Obrigatória:** Decorar com `@csrf_exempt`. No método `post`, capturar o cabeçalho de assinatura (ex: `X-Hub-Signature` ou `X-Signature`), gerar o HMAC-SHA256 usando o payload bruto (`request.body`) e a chave secreta da API do Gateway (armazenada em `.env`). Só processar o pagamento se `hmac.compare_digest` for `True`.

---

## 📦 SPRINT 8: Torre de Controle Logística & Tracking Dinâmico

### 8.1. PWA e Tracking Offline (`static/js/offline_sync.js` e `app_campo.js`)
- **Modificação no IndexedDB:** Adicionar nova ObjectStore `gps_tracking_queue` (keyPath: `id` auto-increment).
- **Captura no PWA:** No `app_campo.js`, instanciar `navigator.geolocation.watchPosition()`. A cada 30 segundos, salvar `{lat, lng, timestamp, entrega_id}` no `gps_tracking_queue`.
- **Sync:** A rotina de sync do PWA deve enviar os arrays de coordenadas em lote (`POST /logistica/api/tracking/sync/`) e depois limpar o banco local.

### 8.2. Roteirização e Modelagem (`logistica/models.py`)
- Em `Entrega`, adicionar `token_rastreio = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)`.
- Criar `CoordenadaRastreamento`: `tenant` (FK), `entrega` (FK), `latitude` (DecimalField 10,7), `longitude` (DecimalField 10,7), `timestamp` (DateTimeField).
- **API de Roteirização (`logistica/services/routing.py`):** Criar função `otimizar_ordem_paradas(entrega_id)` que monta um array de `waypoints` com os endereços das vendas daquela entrega e simula uma chamada à API de rotas para calcular a `ordem_otimizada` dos itens.

### 8.3. View Pública de Rastreio (Sem DRF Auth)
- Criar rota `path('rastreio/<uuid:token>/', TrackingPublicoView.as_view(), name='rastreio_publico')`.
- Esta View DEVE retornar apenas os dados mínimos (`nome_motorista`, `placa_mascarada`, `status_entrega`, `ultima_lat`, `ultima_lng`). Não serializar dados de faturamento ou clientes na mesma entrega. Renderizar um HTML leve usando a biblioteca Leaflet.js (`<div id="map">`).

---

## 📦 SPRINT 9: Portal B2B do Cliente (Autoatendimento)

### 9.1. Modelagem de Acesso B2B (`accounts/models.py` e `clientes/models.py`)
- Criar `UsuarioClienteB2B`: Herda de `TenantAwareModel` (para garantir que o usuário pertence àquele tenant). Campos: `user` (OneToOneField para o User do Django, `related_name='usuarioclienteb2b'`), `cliente` (ForeignKey para `Cliente`).
- **Segurança Restritiva (`core/permissions.py`):** Criar `class IsClientB2B(permissions.BasePermission)`. Valida se `request.user.is_authenticated` e se possui o hasattr `usuarioclienteb2b`.

### 9.2. ViewSets Isolados (`portal_b2b/views.py`)
- É ESTRITAMENTE PROIBIDO reutilizar os ViewSets do sistema administrativo (como `VendaViewSet`).
- Criar ViewSets espelho (ex: `B2BVendaViewSet`, `B2BFaturaViewSet`, `B2BCilindroViewSet`).
- A regra de ouro no `get_queryset(self)` desses ViewSets:
  ```python
  def get_queryset(self):
      cliente_b2b = self.request.user.usuarioclienteb2b.cliente
      return super().get_queryset().filter(cliente=cliente_b2b)
  ```

### 9.3. Download de Laudos (Compliance ANVISA)
- No `B2BCilindroViewSet` (cilindros em comodato com este cliente), criar `@action(detail=True, methods=['get']) def laudo_quimico(self, request, pk=None)`.
- A query deve buscar a `MovimentacaoCilindro` mais recente deste casco associada a este cliente, cruzar com o `EnvaseCilindro` que originou a carga, recuperar o `LoteEnvase` correspondente e servir o PDF do laudo (assinado pelo RT).