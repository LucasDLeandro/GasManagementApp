# Registro das Operações de Tratamento de Dados Pessoais (RoPA - LGPD)

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Enquadramento Legal:** Art. 37 da Lei Federal nº 13.709/2018 (LGPD)  

---

## 1. Inventário Geral de Dados Pessoais e Categorias de Titulares

O Baros processa dados pessoais exclusivamente necessários para a operação comercial, logística, patrimonial, fiscal e contábil das distribuidoras de gases.

| Categoria de Titular | Dados Pessoais Tratados | Finalidade Principal | Base Legal (LGPD) | Prazo de Retenção |
| :--- | :--- | :--- | :--- | :--- |
| **Motoristas e Entregadores** | Nome, CPF, CNH (número, categoria, validade), certificado MOPP, coordenadas GPS em rota, odômetro. | Habilitação legal para transporte de carga perigosa (ANTT), segurança viária, roteirização e comprovação de entrega. | Cumprimento de obrigação legal (Art. 7º, II) e Execução de contrato (Art. 7º, V). | **Dados Cadastrais:** Duração do contrato de trabalho + 5 anos (trabalhista). <br>**Coordenadas GPS:** 90 dias (expurgo automatizado). |
| **Clientes Pessoa Física (PF)** | Nome, CPF, endereço de entrega, telefone, WhatsApp, e-mail, histórico de consumo e títulos financeiros. | Venda de gases industriais/medicinais, emissão de NF-e, entrega física, cobrança e rastreabilidade de cilindros em comodato. | Execução de contrato (Art. 7º, V) e Cumprimento de obrigação legal/fiscal (Art. 7º, II). | **5 anos após o encerramento do exercício fiscal** (Art. 173 do Código Tributário Nacional - CTN c/c Art. 16, I da LGPD). |
| **Contatos Comerciais e Financeiros (PJ)** | Nome, e-mail corporativo, telefone, cargo/departamento, logs de acesso ao Portal B2B. | Comunicação operacional, envio de DANFE/XML, emissão de boletos/PIX e liberação de reposição de gás. | Execução de contrato (Art. 7º, V) e Legítimo interesse (Art. 7º, IX). | Duração da relação comercial com a pessoa jurídica ou revogação formal. |
| **Operadores do Sistema (Usuários)** | Nome de usuário, e-mail, hash de senha com salt, registro de MFA TOTP, IP de conexão e logs de auditoria. | Autenticação, controle de acesso RBAC, rastreabilidade e auditoria append-only de operações. | Segurança e prevenção à fraude (Art. 7º, IX c/c Art. 11, II, g) e Marco Civil da Internet (Art. 15 Lei 12.965/14). | **Logs de Conexão:** 6 meses (Marco Civil). <br>**Logs de Auditoria Transacional:** 5 anos (norma contábil e fiscal). |

---

## 2. Fluxo de Atendimento a Direitos dos Titulares (Art. 18 LGPD)

O sistema conta com o serviço formal de governança LGPD em `core/services/lgpd_service.py` e com o model `SolicitacaoTitularLGPD` para registro e auditoria de solicitações.

### 2.1. Direito de Acesso e Portabilidade (Art. 18, II e V)
- **Operação:** `exportar_dados_titular(tenant, titular_cpf, titular_email)`
- **Resultado:** Geração de arquivo estruturado JSON ou PDF contendo todos os dados cadastrais, movimentações de comodato, notas fiscais e títulos financeiros associados ao CPF do solicitante, emitido no prazo de até 15 dias.

### 2.2. Direito de Eliminação, Bloqueio ou Anonimização (Art. 18, IV e VI)
- **Operação:** `anonimizar_ou_eliminar_titular(tenant, titular_cpf, justificativa, usuario_solicitante)`
- **Conflito Aparente:** Solicitação de exclusão de dados pessoais por cliente que possui notas fiscais emitidas ou títulos financeiros faturados.
- **Harmonização Normativa Aplicada:**
  - O Art. 16, inciso I da LGPD expressamente autoriza e determina a conservação dos dados pessoais para o **"cumprimento de obrigação legal ou regulatória pelo controlador"**.
  - O Art. 173 do Código Tributário Nacional (CTN) e a legislação do ICMS e da Receita Federal exigem a guarda dos livros fiscais, faturas e NF-e pelo prazo prescricional de **5 anos**.
  - **Procedimento no Baros:**
    1. Se houver pendências ativas ou documentos fiscais dentro do prazo decadencial de 5 anos, o sistema aplica a **Pseudonimização Cadastral**:
       - Dados de contato direto (telefone, celular, WhatsApp, e-mail) e dados não-fiscais são imediatamente substituídos por valores anonimizados (`ANONIMIZADO_LGPD_...`).
       - O nome e CPF nas notas fiscais históricas são arquivados de forma criptografada para fins exclusivos de fiscalização tributária e auditoria externa.
       - Bloqueia-se qualquer disparo futuro da régua de cobrança, mala direta ou contatos comerciais.
    2. Quando decorrido o prazo prescricional de 5 anos sem qualquer obrigação fiscal remanescente, procede-se ao expurgo definitivo.

### 2.3. Expurgo Automatizado de Telemetria Geográfica (GPS)
- **Operação:** `expurgar_telemetria_gps_antiga(tenant=None, dias_retencao=90)`
- **Frequência:** Job diário agendado no Celery Beat às 03:00 BRT.
- **Regra:** Todas as instâncias de `CoordenadaRastreamento` com `timestamp < agora - 90 dias` são removidas fisicamente do banco de dados, mantendo apenas sumários desidentificados de distância e tempo para fins estatísticos de frota.

---

## 3. Segurança da Informação e Conformidade Técnica

1. **Criptografia em Repouso:**
   - Chaves de API, credenciais de gateway bancário e certificados A1 são cifrados via algoritmo simétrico Fernet (AES-128 em modo CBC com HMAC SHA-256) através de `core.services.seguranca_service`.
2. **Criptografia em Trânsito:**
   - Todo tráfego HTTP é estritamente forçado via TLS 1.3 (HTTPS) com HSTS habilitado.
3. **Isolamento Multi-Tenant:**
   - Validação fail-closed via `TenantAwareModel` e testes contínuos de invasão provando HTTP 404 em cruzamento de tenants.
4. **Governança de Logs:**
   - `LogAuditoriaDados` possui bloqueio estrito contra edição e exclusão (append-only), garantindo a rastreabilidade imutável de todas as modificações patrimoniais e fiscais.
