# ADR-042: Arquitetura da Camada Fiscal, EmissorFiscalPort e Estratégia de Gateway

## Status
Aprovado (Sprint 11A - Fundação Fiscal e NF-e de Venda)

## Contexto e Problema
A emissão de Documentos Fiscais Eletrônicos (NF-e modelo 55, NFC-e 65, CT-e 57 e MDF-e 58) no Brasil é altamente regulada e complexa, com frequentes alterações de Notas Técnicas (NT) e variações de regras estaduais nas 27 Secretarias de Fazenda (SEFAZ).

As auditorias das versões anteriores apontaram:
- **F-24 (Ausência de camada fiscal integrada e desacoplada):** Dependência de sistemas ERP externos sem governança sobre contingências fiscais e eventos;
- **F-25 (Fragilidade e ausência de motor tributário auditável):** Regras tributárias hardcoded ou aproximadas, gerando riscos de autuação fiscal por CFOP/CST indevido;
- **F-26 (Descompasso entre faturamento financeiro e autorização SEFAZ):** Reconhecimento de receita antes da autorização fiscal da NF-e.

## Decisão Arquitetural

### 1. Padrão Port & Adapters (Hexagonal)
Para desacoplar a lógica de negócio do provedor externo de transmissão fiscal, adotamos o padrão Port & Adapter:
- **Port Canônico:** Interface abstrata `EmissorFiscalPort` definindo o contrato com métodos unificados:
  - `emitir_nfe(payload: Dict[str, Any]) -> RespostaEmissao`
  - `consultar(chave_ou_recibo: str) -> RespostaConsulta`
  - `cancelar(chave: str, justificativa: str, protocolo: str) -> RespostaEvento`
  - `carta_correcao(chave: str, texto_correcao: str, seq: int) -> RespostaEvento`
  - `inutilizar(filial, serie: int, numero_inicial: int, numero_final: int, justificativa: str) -> RespostaEvento`
  - `emitir_mdfe(payload: Dict[str, Any]) -> RespostaEmissao`
  - `encerrar_mdfe(chave: str, protocolo: str, municipio_ibge: str) -> RespostaEvento`
  - `emitir_cte(payload: Dict[str, Any]) -> RespostaEmissao`
  - `baixar_xml_danfe(chave: str) -> RespostaDownload`

### 2. Escolha do Adaptador Inicial: Gateway Fiscal Homologado
Avaliou-se a implementação de transmissão SEFAZ própria (direta via bibliotecas PyTrustNFe/erpbrasil) versus o uso de um Gateway Fiscal homologado em nuvem (Focus NFe, Nuvem Fiscal ou PlugNotas).

**Critérios de Avaliação:**
1. **Custo:** Gateways em nuvem cobram centavos por documento emitido (R$ 0,05 a R$ 0,15), eliminando o custo de servidores de HSM e manutenção contínua de certificados em cluster.
2. **SLA e Alta Disponibilidade:** Os gateways gerenciam automaticamente contingências (SCAN, SVC-AN, SVC-RS), retransmissões por fila e redundância geográfica em 27 UFs com SLA superior a 99,8%.
3. **Cobertura Normativa e Atualizações:** Notas Técnicas da SEFAZ são absorvidas pelo gateway sem exigir paradas ou correções emergenciais de certificados no core do SaaS.

**Decisão:**
- O adaptador inicial implementa a integração com **Gateway Fiscal Homologado** (Focus NFe / Nuvem Fiscal).
- A interface `EmissorFiscalPort` isola 100% o sistema, mantendo a opção de implementação própria no futuro como outro adaptador sem qualquer impacto no core.
- **FakeEmissor:** Implementação de teste para homologação completa de ponta a ponta sem chamadas externas, simulando autorizações, rejeições com códigos SEFAZ reais, timeouts, duplicidades e contingências.

### 3. Segurança de Credenciais e Certificados A1
- Certificados digitais A1 (`.pfx`) e credenciais de API do gateway são gravados de forma cifrada simétrica via `cryptography.fernet`.
- A chave de cifra (`FISCAL_ENCRYPTION_KEY`) é obtida exclusivamente de variáveis de ambiente do sistema operacional ou KMS externo, sendo terminantemente proibida a persistência da chave no banco de dados.
- Logs operacionais passam por filtro de sanitização automática (`sanitize_log_data`), expurgando senhas, chaves privadas e dados sensíveis antes de qualquer saída.

### 4. Sequenciamento Estrito com o Módulo Financeiro
- Quando o tenant tiver o `modulo_fiscal_ativo = True`:
  1. A venda é registrada com status inicial `Pendente`/`Em Separação`;
  2. O `DocumentoFiscal` é montado e transmitido;
  3. Somente após a confirmação de status `AUTORIZADO` pela SEFAZ é que o evento de domínio `venda_faturada` é publicado para o financeiro;
  4. O financeiro recebe os tributos reais calculados da NF-e autorizada e substitui eventuais estimativas;
  5. Documentos rejeitados não publicam evento financeiro nem geram títulos de cobrança.

## Consequências
- **Positivas:** Conformidade fiscal rigorosa, facilidade de auditoria para os contadores dos tenants, desacoplamento tecnológico e garantia de que nenhum cliente é cobrado por notas rejeitadas.
- **Atenção:** Exige acompanhamento do contador responsável do tenant para validação das regras tributárias antes da ativação do ambiente de produção.
