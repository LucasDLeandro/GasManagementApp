# Relatório de Impacto à Proteção de Dados Pessoais (RIPD / DPIA)
## Rastreamento Geográfico (GPS) e Mensageria Automatizada de Cobrança

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data de Emissão:** 2026-10-27  
**Enquadramento Legal:** Lei Federal nº 13.709/2018 (Lei Geral de Proteção de Dados Pessoais - LGPD), Art. 38 e correlatos.  

---

## 1. Caracterização dos Agentes de Tratamento e Papéis

No contexto do modelo de fornecimento de software SaaS (Software as a Service) multilocatário:

1. **Controlador dos Dados (Tenant / Distribuidora de Gás):**
   - É a empresa distribuidora contratante do Baros SaaS.
   - Detém o poder de decisão sobre o tratamento dos dados de seus colaboradores (motoristas, ajudantes), clientes (pessoas físicas e contatos de pessoas jurídicas) e rotas de entrega.
   - Define os clientes a serem cobrados, as rotas a serem executadas e os canais de contato autorizados.

2. **Operador dos Dados (Baros SaaS / Provedor de Tecnologia):**
   - Atua exclusivamente em nome e segundo as instruções lícitas do Controlador (Art. 39 da LGPD).
   - Implementa a infraestrutura lógica, banco de dados isolado com *Fail-Closed Multi-Tenancy*, criptografia em repouso e em trânsito, controle estrito de acessos RBAC e auditoria append-only.

3. **Encarregado pelo Tratamento de Dados (DPO):**
   - Canal institucional: `dpo@baros.com.br` / `privacidade@baros.com.br`.

---

## 2. Descrição das Operações de Tratamento Avaliadas

### Operação A: Rastreamento Geográfico (GPS) de Motoristas e Veículos em Rota
- **Finalidade:** Segurança de transporte de carga perigosa (ABNT NBR 14619 / Resolução ANTT nº 5.998/22), comprovação de entrega ao cliente, cálculo de ETA e monitoramento logístico operacional.
- **Titulares dos Dados:** Motoristas próprios e terceirizados.
- **Dados Coletados:** Latitude, longitude, precisão em metros, velocidade instantânea, timestamp e identificador do veículo/entrega.
- **Base Legal (LGPD):**
  - **Execução de Contrato de Trabalho / Prestação de Serviços (Art. 7º, V):** Necessário para a execução dos serviços de entrega e jornada de trabalho em rota externa.
  - **Cumprimento de Obrigação Legal e Regulatória (Art. 7º, II):** Rastreabilidade de produtos perigosos inflamáveis e medicinais.
  - **Legítimo Interesse do Controlador (Art. 7º, IX):** Prevenção a roubo de carga e sinistros viários.
- **Medidas de Minimização e Salvaguardas:**
  - Descarte no client-side de coordenadas com precisão inferior a 100m.
  - Exposição no link público de rastreio (`/rastreio/<uuid:token>/`) apenas quando faltarem no máximo 3 paradas ou $\le$ 60 minutos do ETA, ocultando nome e foto do motorista.
  - **Prazo de Retenção e Expurgo:** **90 dias**. Coordenadas anteriores a 90 dias são permanentemente expurgadas pelo serviço automatizado `expurgar_telemetria_gps_antiga`.

### Operação B: Mensageria Automatizada de Cobrança e Notificações (Régua de Cobrança)
- **Finalidade:** Notificação preventiva e de cobrança referente a parcelas a vencer ou vencidas, envio de boletos registrados e QR Code PIX.
- **Titulares dos Dados:** Clientes pessoas físicas e prepostos financeiros de clientes jurídicos.
- **Dados Coletados:** Nome, CPF/CNPJ, telefone WhatsApp, endereço de e-mail e dados do título em aberto.
- **Base Legal (LGPD):**
  - **Execução de Contrato (Art. 7º, V):** Gestão e adimplemento da obrigação financeira pactuada na venda de gases/locação.
  - **Legítimo Interesse e Proteção do Crédito (Art. 7º, X):** Cobrança amigável antes de negativação.
  - **Consentimento Expresso para Canais Digitais (Art. 7º, I):** Armazenado no modelo `ConsentimentoCanal` com registro de IP e timestamp.
- **Medidas de Minimização e Salvaguardas:**
  - Bloqueio imediato de envio se o consentimento do canal for revogado (`revogado_em is not None`).
  - Janela estrita de horário comercial (08:00 às 20:00).
  - Teto de no máximo 2 comunicações diárias por cliente.

---

## 3. Avaliação de Riscos e Medidas de Mitigação

| Risco Identificado | Severidade Inicial | Probabilidade | Medida de Mitigação Implementada | Severidade Residual |
| :--- | :--- | :--- | :--- | :--- |
| **Vazamento de trajeto pessoal do motorista fora de horário de serviço** | Alta | Baixa | A coleta de GPS é ativada estritamente durante o status `'Em Rota'` de entrega e encerrada imediatamente no retorno à base. | **Baixa** |
| **Exposição indevida da posição do caminhão a terceiros mal-intencionados** | Alta | Média | O link público `/rastreio/<token>` usa UUID criptográfico, expira 4h após entrega, possui rate limiting (60 req/min) e oculta a rota preliminar. | **Baixa** |
| **Comunicação invasiva ou cobrança vexatória via canais de mensagens** | Média | Baixa | A régua de cobrança respeita teto diário, janela de 08h-20h, cancelamento automático se a parcela estiver paga e respeito a opt-out. | **Muito Baixa** |
| **Acesso indevido a dados de outro tenant (quebra de multitenancy)** | Crítica | Muito Baixa | Modelos herdam de `TenantAwareModel`, filtro obrigatório no QuerySet (`Fail-Closed`), testes de regressão automatizados provando HTTP 404. | **Residual Mínimo** |

---

## 4. Parecer e Conclusão

As operações de rastreamento geográfico e mensageria digital no Baros SaaS atendem rigorosamente aos princípios da **finalidade, adequação, necessidade, livre acesso, qualidade dos dados, transparência, segurança, prevenção e não-discriminação** (Art. 6º da LGPD).

Os riscos residuais foram considerados baixos e plenamente controlados pelos mecanismos técnicos e contratuais estabelecidos. O tratamento é homologado e considerado seguro para operação regular em produção.
