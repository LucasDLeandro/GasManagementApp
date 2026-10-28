# ADR-041: Arquitetura de Integração Bancária, Cobrança Registrada e Conciliação (Sprint 10A)

## Status
Aprovado e Implementado (Sprint 10A)

## Contexto
O ecossistema financeiro do ERP de Distribuição de GLP e Gases Industriais exige:
1. Emissão de cobrança bancária registrada com geração simultânea de Boleto Bancário e PIX Dinâmico com QR Code e Copia-e-Cola por parcela;
2. Baixa automatizada e instantânea via Webhooks autenticados de Provedores de Serviços de Pagamento (PSPs);
3. Conciliação bancária confiável de extratos (OFX e CNAB 240/400 de retorno) sem promessas instáveis de Open Finance neste estágio inicial;
4. Execução de régua de cobrança multicanal (E-mail e WhatsApp via BSP oficial) com gestão rigorosa de consentimento (LGPD) e controle de frequência.

Historicamente, tentativas de integração direta via Open Finance no mercado de distribuição B2B nacional enfrentam alta volatilidade de APIs de leitura bancária, lentidão de consentimento de pessoas jurídicas e latência incompatível com o fechamento diário do caixa. Por outro lado, a dependência exclusiva de arquivos manuais CNAB impõe defasagem de D+1 a D+2 para confirmação de recebimentos.

## Decisão

### 1. Padrão Arquitetural: Port & Adapters (`BancoGatewayPort`)
Adotou-se a arquitetura de portas e adaptadores (Hexagonal) para isolar o domínio financeiro das particularidades bancárias:
- **Porta Central (`BancoGatewayPort`):** Interface abstrata com as operações obrigatórias:
  - `emitir_boleto(cobranca_request) -> CobrancaResponse`
  - `emitir_pix(cobranca_request) -> CobrancaResponse`
  - `consultar_cobranca(gateway_charge_id) -> CobrancaStatusResponse`
  - `cancelar(gateway_charge_id) -> bool`
  - `processar_webhook(payload, headers) -> WebhookEvent`
- **Adaptadores Implementados:**
  1. **`GatewayPSPAdapter` (Prioritário):** Adaptador com o PSP piloto **Asaas** (API REST v3), viabilizando emissão síncrona com `gateway_charge_id`, retorno imediato de QR Code PIX, linha digitável e conciliação em segundos via Webhook com validação de assinatura HMAC.
  2. **`ArquivoCNABAdapter` (Segunda via / Piloto Tradicional):** Adaptador para remessa e retorno nos padrões CNAB 240 e CNAB 400 com layout piloto do **Itaú Unibanco**, atendendo clientes industriais de grande porte que operam com carteiras de cobrança escritural direta.
- **Recomendação Estratégica:** Priorizar o `GatewayPSPAdapter` para 100% das novas emissões e utilizar o `ArquivoCNABAdapter` como alternativa para clientes que exigem remessa bancária tradicional.

### 2. Conciliação Bancária Híbrida (OFX + CNAB Retorno)
- Parser tolerante a codificações heterogêneas (UTF-8, Latin-1/ISO-8859-1, Windows-1252) e variações de tags SGML do padrão OFX.
- Deduplicação rígida por hash SHA-256 do arquivo em `ImportacaoExtrato` e por `hash_dedup` (composto por FITID/Documento + Data + Valor) em `ExtratoBancarioItem`.
- **Motor de Conciliação em 5 Regras Ordenadas:**
  1. *Regra 1:* Casamento direto por `nosso_numero` ou `txid` do PIX $\rightarrow$ Baixa automática da parcela (Score 100).
  2. *Regra 2:* Valor exato + Janela de $\pm 3$ dias + Documento (CNPJ/CPF) do pagador $\rightarrow$ Conciliação automática acima do limiar configurável (Score 95).
  3. *Regra 3:* Valor exato + Janela de $\pm 3$ dias + Similaridade de razão social/nome $\rightarrow$ Marcação exclusiva como **SUGERIDO** (Score 75-85), exigindo conferência humana.
  4. *Regra 4:* Depósito único para múltiplas parcelas (combinação combinatória de até 5 parcelas do mesmo cliente) $\rightarrow$ Sugestão para o operador aprovar em lote.
  5. *Regra 5:* Tarifas e rendimentos bancários via tabela configurável `RegraConciliacao` $\rightarrow$ Escrituração contábil automática no Razão.
- Bloqueio estrito de estorno de conciliação para datas anteriores a `conciliacao_fechada_ate` de cada conta financeira.

### 3. Régua de Cobrança e Gestão de Consentimento (LGPD)
- Disparos automáticos baseados no vencimento ($D-3, D0, D+3, D+7, D+15$).
- Exigência prévia de `ConsentimentoContato` ativo (com suporte a opt-out imediato).
- Respeito à janela de horário comercial (08:00 às 20:00) e limite diário de envios por cliente.
- Supressão imediata de envios caso a parcela esteja quitada (`PAGA`) ou renegociada.

### 4. Fora de Escopo
- **Open Finance:** Adiado para fase futura, quando a maturidade de APIs de iniciação de pagamento (ITP) para pessoas jurídicas atingir SLA corporativo.
- **Protesto Automático em Cartório:** Mantido sob marcação manual de status `EM_PROTESTO`.
- **Múltiplos Bancos além dos Pilotos:** Suporte inicial focado em Asaas (PSP) e Itaú (CNAB).

## Consequências
- Fim da inadimplência oculta por falta de conciliação tempestiva.
- Total rastreabilidade e reconciliação entre saldo do extrato bancário e saldo do Razão Contábil.
- Emissão instantânea e resiliente de boletos registrados e PIX com liquidação em tempo real.
