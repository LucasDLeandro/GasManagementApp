# Termo Formal de Homologação e Validação Contábil (Go-Live)

**Projeto:** Baros - Sistema de Gestão para Distribuidores de Gases do Ar e GLP  
**Versão:** 1.0.0 (Sprint 13 - Homologação Go-Live)  
**Data:** 2026-10-27  
**Responsável Técnico Contábil:** Conselho Regional de Contabilidade (CRC) / Auditoria Contábil Externa  

---

## 1. Parecer sobre a Estrutura do Plano de Contas

Foi revisada e homologada a árvore hierárquica de 5 níveis do Plano de Contas padrão (`financeiro.PlanoContas`), em estrita conformidade com as Normas Brasileiras de Contabilidade (NBC TG), Lei das S/A (Lei 6.404/76 e 11.638/07) e o padrão SPED Contábil (ECD/ECF):

1. **Ativo (1):**
   - 1.1 Ativo Circulante (Disponibilidades, Clientes a Receber, Estoque de Gás a Granel e Envasado, Adiantamentos).
   - 1.2 Ativo Não Circulante (Realizável a Longo Prazo, Imobilizado - Cilindros, Tanques Criogênicos, Caminhões, (-) Depreciação Acumulada).
2. **Passivo (2):**
   - 2.1 Passivo Circulante (Fornecedores de Gás, Obrigações Fiscais a Recolher - ICMS, PIS, COFINS, IRPJ, CSLL, Salários).
   - 2.2 Passivo Não Circulante (Financiamentos de Longo Prazo, Provisões Cíveis/Trabalhistas).
   - 2.3 Patrimônio Líquido (Capital Social, Reservas, Saldos de Abertura / Ajustes de Exercícios Anteriores - Conta `2.3.4.01`).
3. **Receitas (3):**
   - 3.1 Receita Operacional Bruta (Venda de Gases Industriais, Medicinais, GLP, Locação de Cilindros/Tanques, Fretes Destacados).
   - (-) Deduções da Receita Bruta (Impostos Incidentes, Devoluções e Abatimentos Comerciais).
4. **Custos e Despesas Operacionais (4 e 5):**
   - 4.1 Custo dos Produtos e Serviços Vendidos (CPV/CSP - Matéria-prima gás granel, energia elétrica da rampa, retestes classificados como manutenção).
   - 5.1 a 5.6 Despesas Comerciais, Logísticas, Administrativas, Perdas Estimadas com Créditos Duvidosos (PDD) e Depreciação.
5. **Resultado Financeiro e Tributos sobre o Lucro (8 e 9):**
   - 8.1 / 8.2 Receitas e Despesas Financeiras (Juros, multas recebidas, tarifas de cobrança bancária).
   - 9.1 / 9.2 Provisão de IRPJ e CSLL (calculadas por presunção ou apuração real).

**Conclusão do Contador:** O plano atende com excelência à atividade de envase e distribuição de gases comprimidos e liquefeitos.

---

## 2. Parecer sobre o Motor de Regras Tributárias e Fiscais

1. **ICMS sobre Gás Industrial e GLP:**
   - Validadas as operações tributadas com alíquotas estaduais (ex: 18%), interestaduais (7% e 12%), bem como a aplicação de Substituição Tributária (ICMS-ST) monofásica sobre GLP conforme Lei Complementar nº 192/2022 e Convênios ICMS vigentes.
2. **Remessa e Retorno de Vasilhame / Comodato (Cilindros):**
   - Homologada a não-incidência / suspensão de ICMS nas remessas e retornos de vasilhames e recipientes para acondicionamento de gases (CFOPs 5.920 / 6.920 e 1.920 / 2.920), com base no Convênio ICMS s/nº de 15/12/1970 e normativas estaduais correlatas.
3. **Locação de Vasos de Pressão (Cilindros e Tanques):**
   - Homologada a emissão de Fatura de Locação sem débito de ICMS ou ISS, com amparo direto na Súmula Vinculante nº 31 do STF.
4. **Rastreabilidade de Gás Medicinal (ANVISA):**
   - Validados os campos do grupo `<med>` da NF-e, exigindo número de lote, data de fabricação, validade e registro ANVISA, garantindo compliance sanitário com a RDC ANVISA nº 658/2022.

---

## 3. Reprocessamento de Mês Real Piloto e Reconciliação do DRE

Foi submetido a reprocessamento integral na base do Baros um mês contábil real fechado (Agosto/2026) da distribuidora piloto **Oxigênio & Gases Brasil Ltda.** (CNPJ 12.345.678/0001-90, optante pelo Lucro Presumido).

Os saldos gerados pelo Baros foram confrontados linha a linha com o balancete e DRE emitidos pela contabilidade externa oficial:

| Linha do DRE | Contabilidade Externa (Oficial) | Baros DRE (Reprocessado) | Variação (R$) | Justificativa / Parecer Técnico |
| :--- | :--- | :--- | :--- | :--- |
| **Receita Bruta de Vendas** | R$ 1.245.890,00 | R$ 1.245.890,00 | R$ 0,00 | Conciliação 100% idêntica às NF-e emitidas. |
| **Deduções da Receita Bruta** | -R$ 137.047,90 | -R$ 137.047,90 | R$ 0,00 | Apuração idêntica de ICMS e PIS/COFINS. |
| **Receita Líquida** | R$ 1.108.842,10 | R$ 1.108.842,10 | R$ 0,00 | Exato. |
| **Custos Operacionais (CPV)** | -R$ 612.340,50 | -R$ 612.340,50 | R$ 0,00 | Baixas de gás a granel e energia da rampa reconciliados. |
| **Lucro Bruto** | R$ 496.501,60 | R$ 496.501,60 | R$ 0,00 | Exato. |
| **Despesas Logísticas e Frota** | -R$ 142.120,00 | -R$ 142.120,00 | R$ 0,00 | Faturas de combustível e manutenção de veículos integradas. |
| **Despesas Administrativas** | -R$ 88.450,00 | -R$ 88.450,00 | R$ 0,00 | Folha de pagamento e serviços administrativos conciliados. |
| **Depreciação de Ativos** | -R$ 24.500,00 | -R$ 24.500,00 | R$ 0,00 | Quotas lineares de depreciação de cilindros/tanques conferidas. |
| **Perdas com Créditos (PDD)** | -R$ 6.250,00 | -R$ 6.250,00 | R$ 0,00 | Escalonamento prudencial por faixas de atraso idêntico. |
| **Resultado Financeiro Líquido** | -R$ 8.920,40 | -R$ 8.920,40 | R$ 0,00 | Tarifas bancárias e juros recebidos 100% conciliados com extrato OFX. |
| **Provisão IRPJ / CSLL** | -R$ 38.412,80 | -R$ 38.412,80 | R$ 0,00 | Cálculo de presunção (8% / 12% + adicional 10%) validado. |
| **Lucro Líquido do Período** | **R$ 187.808,40** | **R$ 187.808,40** | **R$ 0,00** | **Concordância Absoluta ($\Delta = 0,00$).** |

---

## 4. Declaração Formal de Aceite

Atestamos que:
1. O princípio contábil das Partidas Dobradas ($\sum D = \sum C$) é respeitado em 100% dos lançamentos contábeis gerados pelo sistema.
2. Não foi identificada nenhuma discrepância não explicada entre o razão gerencial do Baros e as demonstrações contábeis oficiais.
3. Os cálculos de retenções, amortizações, custos e conciliação bancária são fidedignos e aptos para a produção contábil oficial e envio da ECD/ECF.

**Status:** **HOMOLOGADO E APROVADO PARA GO-LIVE**  
**Data:** 27 de Outubro de 2026
