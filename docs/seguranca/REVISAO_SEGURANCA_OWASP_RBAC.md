# Relatório de Revisão de Segurança da Informação, OWASP Top 10 e RBAC

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Classificação:** Confidencial / Auditoria de Segurança  

---

## 1. Avaliação contra o OWASP Top 10 (2021 / 2025)

A arquitetura do Baros foi submetida à verificação minuciosa contra os 10 vetores de vulnerabilidade mais críticos em aplicações web:

| Código OWASP | Categoria de Risco | Status no Baros | Mecanismos de Mitigação Implementados |
| :--- | :--- | :--- | :--- |
| **A01:2021** | **Broken Access Control** | **PROTEGIDO** | Dupla camada de autorização: permissão DRF/View + `assert_tenant_writable` e checagem de módulo ativo no serviço de negócio. Testes automatizados IDOR provando HTTP 404/403 para recursos de outros tenants ou clientes. |
| **A02:2021** | **Cryptographic Failures** | **PROTEGIDO** | Certificados digitais A1 (.pfx) e credenciais de gateways bancários cifrados em repouso com algoritmo Fernet (AES-128-CBC + HMAC). Chaves mestras lidas exclusivamente de variáveis de ambiente. Tráfego forçado em TLS 1.3 com HSTS. |
| **A03:2021** | **Injection** | **PROTEGIDO** | Uso exclusivo do Django ORM parametrizado; proibição de consultas SQL cruas concatenadas. Consultas complexas em `selectors/` validadas com linters de segurança. |
| **A04:2021** | **Insecure Design** | **PROTEGIDO** | Arquitetura segura por padrão: Fail-Closed Multi-Tenancy; modelo append-only para auditoria; idempotência garantida com `IdempotencyKey`; segregação de funções em aprovações financeiras (quem lança não aprova). |
| **A05:2021** | **Security Misconfiguration** | **PROTEGIDO** | `DEBUG=False` em produção, headers de segurança configurados (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`), cookies `Secure` e `HttpOnly`. |
| **A06:2021** | **Vulnerable and Outdated Components** | **PROTEGIDO** | Varredura contínua de dependências no CI via `pip-audit` e `safety`. Django 6.0 e pacotes de terceiros sem vulnerabilidades conhecidas (CVEs). |
| **A07:2021** | **Identification and Authentication Failures** | **PROTEGIDO** | Backoffice `/baros-admin/` com MFA TOTP obrigatório e expiração de sessão em 30 min. Portal B2B com cookies segregados (`b2b_sessionid`), bloqueio após 5 tentativas incorretas por 15 min e tokens SHA-256 de uso único. |
| **A08:2021** | **Software and Data Integrity Failures** | **PROTEGIDO** | Validação de assinatura HMAC nos webhooks bancários e fiscais. Links de download com `TimestampSigner` efêmero e rastreador de uso único (`jti`). |
| **A09:2021** | **Security Logging and Monitoring Failures** | **PROTEGIDO** | `LogAuditoriaDados` imutável, `LogAuditoriaSaaS` para eventos administrativos globais, painel unificado de observabilidade e alertas ativos de divergência contábil e jobs falhos. |
| **A10:2021** | **Server-Side Request Forgery (SSRF)** | **PROTEGIDO** | Requisições HTTP de saída (webhooks/APIs) direcionadas a endpoints estritamente validados contra allowlist interna, impedindo resolução para endereços privados (`127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`). |

---

## 2. Protocolo de Rotação de Chaves Criptográficas

Implementado e validado em `core/services/seguranca_service.py` através da função `rotacionar_chaves_criptografia`:

1. **Geração da Nova Chave:** Gera-se uma nova chave segura Fernet de 32 bytes em Base64.
2. **Janela de Transição Criptográfica:**
   - Durante a transição, a aplicação reconhece uma lista encadeada de chaves (`FERNET_KEYS = [chave_nova, chave_anterior]`).
   - Dados gravados são cifrados com a chave nova (`primary`).
   - Dados lidos podem ser decifrados tanto com a chave nova quanto com a chave anterior.
3. **Rotina de Re-criptografia em Lote:**
   - O serviço itera sobre todos os registros sensíveis (credenciais de gateway bancário e certificados em `fiscal.ConfiguracaoFiscalFilial`).
   - Decifra com a chave antiga e recifra atomicamente com a chave nova.
   - Registra a rotação no log de auditoria append-only (`LogAuditoriaDados`).
4. **Descomissionamento da Chave Antiga:**
   - Após validação de 100% dos registros recifrados, a chave anterior é revogada do ambiente.

---

## 3. Revisão de Permissões RBAC e Segurança de `/baros-admin/`

1. **Backoffice Superadministrador (`/baros-admin/`):**
   - URLConf isolada (`core.urls_baros_admin`).
   - Acesso restrito a usuários com `is_superuser=True` e `IsSuperUserStrict`.
   - Segundo fator de autenticação (MFA TOTP) obrigatório para qualquer tela administrativa.
   - Timeout incondicional de sessão de 30 minutos (1.800 segundos).
   - Suporte a restrição de acesso por IP via allowlist (`BAROS_ADMIN_ALLOWED_IPS`).
   - Acesso a dados operacionais de clientes por suporte é restrito a sessões temporárias auditadas de break-glass (`AcessoSuporte`).

2. **Permissões Granulares por Módulo (Distribuidores):**
   - Papéis bem definidos: `GESTOR_FINANCEIRO`, `OPERADOR_FINANCEIRO`, `EXPEDICAO_LOGISTICA`, `MOTORISTA_CAMPO`, `COMERCIAL_VENDAS`, `RESPONSAVEL_TECNICO_RT`.
   - Segregação de funções estrita: operador que lança despesa/título a pagar não possui permissão para aprovar ou liquidar o título (`pode_aprovar`).
   - Liberação de bloqueio comercial exige permissão específica `vendas.liberar_bloqueio_financeiro` e justificativa auditada.

---

## 4. Testes de Invasão (Pen-Test) no Portal B2B e Link de Rastreio

### 4.1. Portal B2B (`/portal-b2b/`)
- **Vetor Testado:** Tentativa de acesso direto a pedidos, cilindros ou notas fiscais de outro cliente através de alteração de IDs na URL (IDOR).
- **Resultado:** **Acesso negado com HTTP 404**. O queryset filtra compulsoriamente por `tenant` e `cliente` vinculado à sessão do usuário B2B.
- **Vetor Testado:** Tentativa de login por operador interno ou superusuário através da tela do portal B2B.
- **Resultado:** **Rejeitado**. `PortalB2BBackend` autentica unicamente credenciais cadastradas em `UsuarioClienteB2B`.
- **Vetor Testado:** Força bruta de senhas.
- **Resultado:** **Bloqueio automático** da conta por 15 minutos após a 5ª tentativa consecutiva incorreta.

### 4.2. Link Público de Rastreio (`/rastreio/<uuid:token>/`)
- **Vetor Testado:** Enumerabilidade e adivinhação de links.
- **Resultado:** Tokens utilizam UUIDv4 de 128 bits criptograficamente seguros (espaço de busca $2^{128}$).
- **Vetor Testado:** Rastreamento perpétuo ou prematuro.
- **Resultado:** Posição GPS oculta até que o veículo esteja próximo ao destino ($\le 3$ paradas ou $\le 60$ min); token expira compulsoriamente 4 horas após a entrega.
- **Vetor Testado:** Ataques de negação de serviço (DoS/Scraping).
- **Resultado:** Rate limiting ativo de 60 requisições por minuto por endereço IP.
