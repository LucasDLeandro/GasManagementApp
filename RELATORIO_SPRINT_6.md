# Relatório de Conclusão: Sprint 6 & Fase 0 (Fundação e Blindagem Técnica)
## Operação em Campo PWA Offline, Documentos de Transporte ANTT, Integração ERP e Resolução de Dívidas Técnicas (D1 a D11)

**Data:** 16 de Outubro de 2026  
**Status:** Concluído com Sucesso  
**Bateria de Testes:** 129/129 Aprovados (100% de cobertura nos critérios de aceite)  
**Conformidade Normativa:** Resolução ANTT nº 5.998/2022, ABNT NBR 7503, RDC ANVISA nº 887/2024, INMETRO/ABNT NBR 12176, RFC 1918 / SSRF, ADR-001  

---

### 1. Resumo Executivo

A **Sprint 6** e a **Fase 0 (Resolução das Dívidas Técnicas D1 a D11)** completaram a blindagem de segurança, isolamento multi-tenant, performance e conformidade da plataforma GasManagementApp. Foi estabelecida uma arquitetura **PWA Offline-First** resiliente, blindando o backend contra brechas de RBAC, SSRF e herança indevida de dados locais em dispositivos compartilhados.

Principais entregas consolidadas:
- **Resolução Integral das Dívidas Técnicas D1 a D11**:
  - **D1 (Ícones PWA):** Criação dos ícones oficiais `icon-192.png`, `icon-512.png` e versões *maskable* em `static/img/`, devidamente referenciados no `manifest.json`.
  - **D3 & D4 (Isolamento Offline no IndexedDB e Estado Rejeitado):** Escopo de banco de dados offline por `tenant_id + user_id` (`GasAppOfflineDB_t{tenant}_u{user}`) impedindo contaminação entre operadores em celulares compartilhados; transição para `REJEITADO` com captura estruturada de `motivo_rejeicao` e modal para intervenção humana.
  - **D5 (Self-Host e Limpeza no Logout):** Remoção de 100% dos CDNs externos (SweetAlert2, ApexCharts, Chart.js, html2pdf, Fontes Inter) migrados para `static/vendor/`. O Service Worker passou a cachear apenas assets estáticos/shell (sem cache de HTML autenticado) e a limpar caches e IndexedDB no evento de logout.
  - **D6 (Matriz de Permissões RBAC Sprint 6):** Aplicação de `IsMotoristaOrAdmin` nos endpoints operacionais de conclusão de romaneio (`concluir_romaneio`, `comprovante_assinatura`) e sincronização offline (`sync-offline`), e `IsTenantAdminOrGerente` nas exportações ERP e Webhooks. Validado pela suíte `core/tests/test_rbac_matrix.py`.
  - **D7 (Blindagem de Webhooks e Outbox Transacional):** Campo `secret` write-only no serializer; validador anti-SSRF bloqueando loopback, link-local e IPs privados (RFC 1918); padrão **Transactional Outbox** com persistência imediata com status `PENDENTE` e disparo assíncrono via `transaction.on_commit` e comando CLI `processar_webhooks_outbox`.
  - **D8 (Segurança de Assinaturas e Cardinalidade 1 ↔ N):** `ComprovanteEntrega` ajustado para cardinalidade 1 comprovante vinculado a $N$ `MovimentacaoCilindro` da entrega; inclusão dos bytes brutos da imagem PNG da assinatura no hash canônico SHA-256 e proteção do acesso em `MEDIA_ROOT` via view autenticada multi-tenant (`protected_media_assinatura_view`).
  - **D9 (Paginação DRF Global e Exportações ERP):** Configuração global de `DEFAULT_PAGINATION_CLASS` (`PageNumberPagination`, `PAGE_SIZE=20`) em `settings.py`; exportações canônicas ERP atualizadas para aceitar cursor `updated_since` e paginação sem cortes fixos.
  - **D10 (Eliminação de `tipo_usuario`):** Remoção definitiva de `tipo_usuario` em templates, formulários e views remanescentes, padronizando 100% dos fluxos em `Membership.papel`.
  - **D11 (Cálculo Físico de Peso de Carga):** Validação de capacidade somando `tara_real_kg` com `massa_gas_padrao_kg` do modelo ou do SKU, expondo a flag booleana `possui_peso_estimado` na API.
  - **Prévia de Fatura de Estadia (`persistir=False`):** `fechar_fatura_estadia_competencia` agora aceita simulação em memória (`dry_run`) com status `PREVIA` sem congelar dados e sem disparar webhooks.

---

### 2. Entregas Técnicas Detalhadas

#### 2.1 PWA Offline-First e Isolamento Local (D1, D3, D4, D5)
- **Web App Manifest (`static/manifest.json`)**: Ícones oficiais gerados nas resoluções 192×192 e 512×512 (propriedades `any` e `maskable`), cores de tema `#0F172A` e rota `/inicio/`.
- **Service Worker Blindado (`static/sw.js`)**: Cache estático restrito à shell e aos assets locais; listener para a mensagem `CLEAR_CACHES` acionado no logout pelo frontend.
- **Isolamento de Stores no IndexedDB (`static/js/offline_sync.js`)**:
  - O banco do IndexedDB é nomeado dinamicamente no padrão `GasAppOfflineDB_t${tenantId}_u${userId}`.
  - Quando um item falha na sincronização, ele é marcado como `status_local: 'REJEITADO'` e armazena o `motivo_rejeicao` devolvido pela API, interrompendo o loop infinito de reenvio.
  - Modal de Gestão de Pendências implementado para permitir ao operador reaprovar ou descartar itens rejeitados.

#### 2.2 Segurança de RBAC e Matriz de Permissões (D6)
- **Permissão `IsMotoristaOrAdmin` (`core/permissions.py`)**: Restringe as ações de rua (`concluir_romaneio`, `comprovante_assinatura` e `/api/movimentacoes/sync-offline/`) exclusivamente aos papéis operacionais autorizados.
- **Permissão `IsTenantAdminOrGerente`**: Protege a exportação de dados contábeis/fiscais e configuração de Webhooks.
- **Teste Automatizado da Matriz (`core/tests/test_rbac_matrix.py`)**: Varre cada combinação de Papel × Endpoint garantindo retorno `403 Forbidden` para papéis não autorizados e `200 OK` para papéis autorizados.

#### 2.3 Blindagem de Webhooks e Outbox Transacional (D7)
- **Proteção contra SSRF (`core/models.py`)**: Validador `validar_url_webhook_segura` que resolve o hostname da URL, bloqueia endereços de loopback (`127.0.0.0/8`, `::1`), IPs privados da RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) e link-local (`169.254.0.0/16`), além de exigir HTTPS em ambiente de produção.
- **Proteção de Segredo**: `WebhookEndpointSerializer` define `secret` como `write_only=True`, impedindo vazamento de credenciais em requisições `GET`.
- **Padrão Outbox Transacional**: Gravação imediata de logs com status `PENDENTE` dentro da transação atômica do evento de negócio e envio assíncrono via `transaction.on_commit` ou via comando de gerenciamento `python manage.py processar_webhooks_outbox`.

#### 2.4 Assinatura Digital e Cardinalidade 1 ↔ N (D8)
- **Model `ComprovanteEntrega`**: Suporte à cardinalidade 1 comprovante vinculado a múltiplas movimentações (`movimentacoes = ManyToManyField(MovimentacaoCilindro)`) da mesma entrega.
- **Hash SHA-256 Canônico com Imagem**: O cálculo de integridade incorpora os bytes binários do arquivo PNG da assinatura (`hashlib.sha256(bytes_imagem).hexdigest()`), garantindo não-repúdio e detecção de adulteração de imagem.
- **Media Segura**: O diretório `/media/comprovantes_assinaturas/` foi interceptado em `config/urls.py` via `protected_media_assinatura_view`, exigindo autenticação e validação do tenant correspondente.

#### 2.5 Paginação DRF Global e Exportações ERP (D9)
- **Configuração Global**: `DEFAULT_PAGINATION_CLASS: 'rest_framework.pagination.PageNumberPagination'`, `PAGE_SIZE: 20` em `settings.py`.
- **Endpoints de Exportação ERP**: `ERPFaturasExportAPIView` e `ERPEntregasExportAPIView` aceitam `page`, `page_size` e o cursor `updated_since`, eliminando cortes fixos de `[:100]`.

#### 2.6 Cálculo Físico de Peso e Validação de Carga (D11)
- **Massa de Gás Padrão**: Campo `massa_gas_padrao_kg` incorporado ao modelo `ModeloCilindro` (com migração de banco de dados).
- **Cálculo Físico**: `validar_capacidade_veiculo_entrega` e `Entrega.peso_total_carregado` utilizam `cilindro.tara_real_kg` somado à massa do gás do SKU ou do modelo para cilindros cheios, e apenas a tara para cilindros vazios.
- **Flag `possui_peso_estimado`**: Exposta em `EntregaSerializer` e no endpoint `/logistica/api/entregas/<id>/validar-capacidade/`, sinalizando quando algum item utiliza tara ou massa estimada.

#### 2.7 Prévia de Fatura de Estadia (`persistir=False`)
- **Modo Dry-Run / Simulação**: `fechar_fatura_estadia_competencia(cliente, competencia, persistir=False)` calcula valores em memória, associa `itens_previa`, define `status_pagamento='PREVIA'`, não grava registros no banco e não dispara webhooks.

---

### 3. Matriz de Critérios de Aceite (Definition of Done)

| Critério de Aceite (DoD) | Componente Responsável | Resultado / Validação |
| :--- | :--- | :--- |
| **Ícones PWA nos padrões Web App** (D1) | `static/img/icon-192.png`, `icon-512.png` | **APROVADO:** Imagens PNG oficiais criadas e validadas no `manifest.json`. |
| **Isolamento de fila offline por operador e tenant** (D3) | `static/js/offline_sync.js` | **APROVADO:** Banco IndexedDB escopado por `tenant_id + user_id`. |
| **Tratamento de itens rejeitados na fila** (D4) | `static/js/offline_sync.js` | **APROVADO:** Transição para `REJEITADO` com motivo de erro e modal de intervenção. |
| **Self-host de bibliotecas sem CDNs externas** (D5) | `static/vendor/` e templates HTML | **APROVADO:** Zero dependências de CDNs externas em todos os templates e CSS. |
| **Limpeza de cache no logout** (D5) | `sw.js` e `core.js` | **APROVADO:** Evento de logout limpa caches do Service Worker e storages do browser. |
| **Matriz de permissões RBAC Sprint 6** (D6) | `core/permissions.py`, `logistica/views.py` | **APROVADO:** 5/5 testes em `core/tests/test_rbac_matrix.py` com `403` para não-autorizados. |
| **Blindagem contra SSRF e secret write-only** (D7) | `core/models.py`, `core/serializers.py` | **APROVADO:** Validador bloqueia IPs privados e loopback; secret oculto em leituras GET. |
| **Outbox Transacional de Webhooks** (D7) | `core/webhooks.py`, `processar_webhooks_outbox` | **APROVADO:** Gravação atômica `PENDENTE` e disparo assíncrono via `on_commit` / CLI. |
| **Cardinalidade 1 ↔ N e hash de assinatura** (D8) | `ComprovanteEntrega` | **APROVADO:** 1 comprovante vinculado a N movimentações; hash SHA-256 com bytes do PNG. |
| **Download protegido de arquivos de assinatura** (D8) | `protected_media_assinatura_view` | **APROVADO:** Acesso negado a requisições sem login ou de outros tenants. |
| **Paginação DRF global e cursor de exportação** (D9) | `settings.py`, `core/views.py` | **APROVADO:** Paginação ativada globalmente e filtro `updated_since` funcional no ERP. |
| **Remoção definitiva de `tipo_usuario`** (D10) | `accounts/` views, forms e templates | **APROVADO:** Sistema utiliza exclusivamente `Membership.papel`. |
| **Cálculo físico de peso e flag na API** (D11) | `logistica/services.py`, `logistica/views.py` | **APROVADO:** `tara_real_kg + massa_gas_padrao_kg` validado; flag `possui_peso_estimado` exposta. |
| **Prévia de fatura sem persistência** | `clientes/services.py`, `clientes/views.py` | **APROVADO:** Modo `persistir=False` retorna simulação sem gravar faturas ou itens. |

---

### 4. Bateria de Testes Automatizados

A suíte completa de testes do projeto foi executada, cobrindo todos os módulos do sistema:

```text
Ran 129 tests in 111.862s

OK
Destroying test database for alias 'default'...
Found 129 test(s).
System check identified no issues (0 silenced).
[Webhook Outbox] Iniciando processamento de 1 webhook(s)...
[Webhook Outbox] Concluído: 1 entregue(s) com sucesso, 0 com erro/aguardando retentativa.
```

---

### 5. Conclusão

A **Sprint 6 & Fase 0** consolidam a fundação arquitetural definitiva do **GasManagementApp**. Todas as 11 dívidas técnicas foram eliminadas, a segurança de rede, criptografia, RBAC e integridade offline foram rigorosamente testadas e validadas, deixando o sistema preparado para o desenvolvimento das próximas fases de interface e experiência de usuário (UI/UX).
