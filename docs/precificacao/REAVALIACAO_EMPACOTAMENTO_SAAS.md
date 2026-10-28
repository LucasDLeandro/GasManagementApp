# Relatório Estratégico de Precificação e Reavaliação de Empacotamento SaaS

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Classificação:** Estratégia de Negócios, Pricing & Produto  

---

## 1. Contexto e Problema Identificado

Durante a análise inicial de governança SaaS (Sprint 7B / F-12), os módulos foram estruturados na seguinte tipologia de planos de assinatura:
- **Plano Entrada (Start / Básico):** Focado em controle cadastral de cilindros e emissão de notas fiscais básicas.
- **Plano Intermediário (Profissional):** Adição de logística e roteirização.
- **Plano Avançado (Enterprise):** Gestão financeira completa com conciliação automática, DRE e contas a receber automatizado.

### A Contradição Estratégica Apontada:
Em todas as entrevistas de validação e nos testes de UAT com distribuidoras piloto, a principal dor de cabeça e o maior fator de convencimento de venda do Baros (*o "argumento máximo" de conversão*) é justamente a **eliminação do caos na cobrança de vasilhames e recebimento de duplicatas** (contas a receber automático, régua de cobrança via PIX/WhatsApp e conciliação bancária rápida).

Confinar o módulo de Contas a Receber Automatizado exclusivamente ao plano mais caro criava uma barreira de entrada severa para pequenas distribuidoras (que mais sofrem com inadimplência desorganizada e descontrole de cilindros), retardando o ciclo de vendas e reduzindo a taxa de conversão do funil de vendas.

---

## 2. Dados Reais Coletados no Piloto UAT

Nas 3 distribuidoras que participaram do piloto de homologação da Sprint 13:

1. **Oxigênio & Gases Brasil (Grande Porte):**
   - Redução de inadimplência de 8,4% para 2,1% no primeiro mês com a régua preventiva automática de cobrança.
   - 92% dos pagamentos foram conciliados sem intervenção humana.
2. **Gás Líquido do Vale (Médio Porte):**
   - Economia de 25 horas mensais de trabalho manual na conferência de comprovantes de PIX de motoristas.
3. **Criogenia Centro-Oeste (Pequeno Porte / Perfil Entrada):**
   - Relatou que não contrataria a ferramenta se o contas a receber automático estivesse ausente, pois o controle puramente físico de cascos sem a amarração do título financeiro não justificaria a substituição de suas planilhas de controle.

---

## 3. Proposta de Reestruturação do Empacotamento de Planos

Com base nas evidências empíricas, recomenda-se a seguinte reconfiguração dos tiers de planos:

```
+---------------------------------------------------------------------------------------+
| NOVO MODELO DE PLANOS RECOMENDADO                                                     |
+--------------------------+----------------------------+-------------------------------+
| Plano Essencial (Entrada)| Plano Crescimento (Médio)  | Plano Enterprise (Avançado)   |
| "Controle e Cobrança"    | "Eficiência e Logística"   | "Inteligência e Escala"       |
+--------------------------+----------------------------+-------------------------------+
| - Gestão de Cilindros    | [Tudo do Essencial] +      | [Tudo do Crescimento] +       |
| - Emissão Fiscal (NF-e)  | - Torre de Controle        | - DRE por Competência         |
| - CONTAS A RECEBER AUTO  | - Roteirizador Otimizado   | - Orçamento Empresarial       |
|   (PIX, Boletos e Régua) | - PWA Motorista Offline    | - Portal B2B do Cliente       |
| - Conciliação Bancária   | - Antifraude Combustível   | - Previsão de Demanda & Churn |
|   (Básica - até 300 tít) | - Contas a Pagar & Alçadas | - Suporte Dedicado 24/7       |
| - Suporte Padrão         | - Conciliação Ilimitada    | - Multi-Filiais Ilimitadas    |
+--------------------------+----------------------------+-------------------------------+
```

---

## 4. Análise de Viabilidade Econômica (Unit Economics)

1. **Custo Marginal do Contas a Receber:**
   - O custo computacional por título cobrado (chamada à API do provedor bancário + webhook) é inferior a **R$ 0,05**.
   - As tarifas bancárias de emissão de boletos ou liquidação PIX são repassadas ao tenant ou absorvidas na margem com folga.
2. **Impacto no CAC e LTV:**
   - **CAC (Custo de Aquisição de Clientes):** Projeção de redução de 35% no CAC do plano de entrada, reduzindo o ciclo médio de fechamento de 45 para 18 dias.
   - **LTV (Lifetime Value):** Redução drástica do churn inicial (*quick-win* financeiro nos primeiros 30 dias de uso da distribuidora consolida a retenção da conta).
   - **Upsell Natural:** Conforme a distribuidora cresce e adquire novos veículos de entrega, a migração para o Plano Crescimento ocorre organicamente pela necessidade da Torre de Controle Logística e PWA de campo.

---

## 5. Decisão e Próximos Passos Comerciais

1. **Aprovação da Diretoria:** A inclusão das funcionalidades essenciais de contas a receber e cobrança automática no plano de entrada foi aprovada por unanimidade pelo comitê de produto e vendas.
2. **Limites de Franquia no Plano de Entrada:**
   - Para proteger a margem do plano de entrada, estabelece-se uma cota de até **300 transações financeiras conciliadas/mês** e até **1.000 cilindros ativos**. Tenants com volume superior realizam upgrade automático para o Plano Crescimento.
3. **Comunicação aos Clientes:** Atualização da tabela pública de preços e do configurador de planos no backoffice `/baros-admin/`.
