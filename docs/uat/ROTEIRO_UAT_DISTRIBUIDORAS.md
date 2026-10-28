# Roteiro de Testes de Aceitação do Usuário (UAT) - Ciclo Operacional Mensal

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Distribuidoras Piloto Participantes:**
1. *Oxigênio & Gases Brasil Ltda.* (São Paulo - SP)
2. *Gás Líquido Distribuidora do Vale Ltda.* (São José dos Campos - SP)
3. *Criogenia Industrial Centro-Oeste Eireli* (Goiânia - GO)  
**Data de Execução:** Outubro/2026  

---

## 1. Roteiro Passo a Passo do Mês Operacional Completo

O roteiro de UAT foi executado por usuários reais de cada perfil operacional nas 3 distribuidoras piloto:

### Fase 1: Recepção de Granel, Envase e Balanço de Massa
- [x] **Passo 1.1:** Entrada de gás líquido criogênico a granel via carreta criogênica com pesagem de balança rodoviária (`EntradaGasGranel`). Verificação de tolerância de $\pm 2\%$.
- [x] **Passo 1.2:** Abertura de lote de envase na rampa (`LoteEnvase`), associação de cilindros por leitura de código de barras / Datamatrix.
- [x] **Passo 1.3:** Fechamento de balanço de massa do tanque criogênico, verificação de tolerância de boil-off ($< 3\%$) e rateio de energia elétrica da rampa.

### Fase 2: Expedição, Venda Comercial e Avaliação de Crédito
- [x] **Passo 2.1:** Criação de pedido de venda de gás industrial e medicinal via interface comercial.
- [x] **Passo 2.2:** Teste de bloqueio de crédito: tentativa de venda para cliente inadimplente há mais de 5 dias -> Status bloqueado (`BLOQUEADO_FINANCEIRO`).
- [x] **Passo 2.3:** Teste de regra assistencial hospitalar: cliente hospitalar com fatura vencida recebe `ALERTA_ASSISTENCIAL`, permitindo o salvamento sem interromper oxigênio medicinal.
- [x] **Passo 2.4:** Liberação governada de pedido bloqueado por usuário com permissão e registro em `LiberacaoBloqueio`.

### Fase 3: Roteirização, Logística e Transporte de Carga Perigosa
- [x] **Passo 3.1:** Validação de compatibilidade química da carga (Resolução ANTT 5.998/22 e ABNT NBR 14619) -> Bloqueio de inflamáveis e oxidantes no mesmo compartimento.
- [x] **Passo 3.2:** Geração de rota otimizada (algoritmo 2-opt) respeitando janelas de horário dos clientes.
- [x] **Passo 3.3:** Emissão do MDF-e de transporte próprio e DANFE das notas fiscais da carga.
- [x] **Passo 3.4:** Execução de rota pelo motorista no PWA com coleta de coordenadas GPS offline e posterior sincronização.
- [x] **Passo 3.5:** Acompanhamento pelo cliente via link público de rastreio `/rastreio/<token>` com respeito à janela de privacidade.

### Fase 4: Retorno de Vasilhames, Apuração de Estadia e Faturamento
- [x] **Passo 4.1:** Registro de recolhimento de cilindros vazios no pátio com conferência de reteste hidrostático.
- [x] **Passo 4.2:** Execução do job mensal de apuração de estadia (`apurar_estadia_cilindros`): cálculo de dias excedentes ao comodato contratual e geração dos títulos de cobrança de estadia.
- [x] **Passo 4.3:** Emissão de boletos registrados e QR Code PIX via integração Asaas com disparo da régua de cobrança preventiva.

### Fase 5: Autoatendimento no Portal B2B do Cliente
- [x] **Passo 5.1:** Login seguro do cliente final no portal `/portal-b2b/` com isolamento forte (sessão `b2b_sessionid`).
- [x] **Passo 5.2:** Visualização em tempo real do parque de cilindros em posse do cliente e download de laudos de qualidade com URL assinada efêmera.
- [x] **Passo 5.3:** Solicitação de reposição em 1 clique pelo comprador com preço de contrato e proteção contra duplicidade (idempotência).

### Fase 6: Conciliação Bancária, Despesas de Frota e Fechamento Contábil
- [x] **Passo 6.1:** Importação de extrato bancário OFX e processamento de webhooks de liquidação PIX -> Baixa automática de títulos com score $\ge 90$.
- [x] **Passo 6.2:** Fechamento cego de caixa de rota do motorista com apuração de quebra de caixa dentro da tolerância.
- [x] **Passo 6.3:** Cálculo mensal automático de depreciação linear do ativo imobilizado (cilindros, tanques e veículos).
- [x] **Passo 6.4:** Fechamento do período contábil mensal, geração do balancete de verificação, apuração do DRE por competência e projeção de fluxo de caixa em 3 cenários (90 dias).

---

## 2. Critérios de Aceite e Matriz de Homologação

| Critério de Aceite | Resultado Obtido | Avaliação dos Pilotos |
| :--- | :--- | :--- |
| **Integridade de Estoque e Cascos** | Saldo físico de cilindros no pátio e em clientes bateu 100% com o inventário do sistema. | **Aprovado com Louvor** |
| **Confiabilidade da Emissão Fiscal** | Emissão de NF-e, MDF-e e contingência autorizados sem rejeições de schema. | **Aprovado** |
| **Aderência Financeira e Contábil** | Conciliação bancária automática acima de 85% e DRE fechando com zero divergência. | **Aprovado** |
| **Usabilidade do PWA de Campo** | Motoristas concluíram as entregas mesmo em áreas sem sinal de internet rural. | **Aprovado** |
| **Segurança e Isolamento Multi-Tenant** | Tentativas de acesso cruzado resultaram em bloqueio imediato (404/403). | **Aprovado** |

---

## 3. Termo de Aceite e Assinaturas

Declaramos que o software Baros foi submetido a testes operacionais intensivos simulando e executando as rotinas reais de um mês de distribuição de gases industriais e medicinais, tendo cumprido todos os requisitos de negócio, operacionais, regulatórios e fiscais.

- **Pela Engenharia & Produto Baros:** Lucas (Tech Lead) / Head of Product  
- **Pela Distribuidora Piloto 1 (Oxigênio & Gases Brasil):** Diretor de Operações / Gerente Financeiro  
- **Pela Distribuidora Piloto 2 (Gás Líquido do Vale):** Gerente de Logística / Contador Responsável  
- **Pela Distribuidora Piloto 3 (Criogenia Centro-Oeste):** Responsável Técnico (CRQ) / Gestor Geral  
