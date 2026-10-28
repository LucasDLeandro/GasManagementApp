# Registro de Decisões e Premissas de Engenharia — GO-LIVE

> [!IMPORTANT]
> **STATUS DO GO-LIVE (SPRINT 13): ZERADO (0 PENDÊNCIAS EM ABERTO)**  
> Todas as decisões técnicas, fiscais, contábeis, logísticas, de segurança e de produto levantadas ao longo das Sprints 7A até a Sprint 13 foram formalmente consensuadas, implementadas com testes automatizados (pytest e hypothesis) e homologadas pelos respectivos responsáveis (Engenharia, Contabilidade, DPO e Produto). Nenhuma pendência permanece sem dono e prazo.

---

## Painel Consolidado de Governança e Homologação

| Sprint | Total de Decisões | Status | Dono Principal | Data Homologação |
| :---: | :---: | :---: | :---: | :---: |
| **Sprint 7A** | 3 itens | RESOLVIDO | Engenharia / Tech Lead | 2026-10-27 |
| **Sprint 7B** | 3 itens | RESOLVIDO | Segurança / Operações SaaS | 2026-10-27 |
| **Sprint 8A** | 4 itens | RESOLVIDO | Engenharia / Comercial | 2026-10-27 |
| **Sprint 8B** | 4 itens | RESOLVIDO | Qualidade Técnica / Normas | 2026-10-27 |
| **Sprint 8C** | 4 itens | RESOLVIDO | Operações / Produção Criogênica | 2026-10-27 |
| **Sprint 9A** | 4 itens | RESOLVIDO | Contabilidade / Controladoria | 2026-10-27 |
| **Sprint 9B** | 4 itens | RESOLVIDO | Controladoria / Financeiro | 2026-10-27 |
| **Sprint 9C** | 3 itens | RESOLVIDO | Frota / Tesouraria | 2026-10-27 |
| **Sprint 10A** | 3 itens | RESOLVIDO | Financeiro / Bancos & PSP | 2026-10-27 |
| **Sprint 10B** | 3 itens | RESOLVIDO | Contabilidade / Tributário | 2026-10-27 |
| **Sprint 10C** | 4 itens | RESOLVIDO | Controladoria / Gestão | 2026-10-27 |
| **Sprint 11A** | 4 itens | RESOLVIDO | Fiscal / SEFAZ | 2026-10-27 |
| **Sprint 11B** | 6 itens | RESOLVIDO | Fiscal / RT Farmacêutico | 2026-10-27 |
| **Sprint 11C** | 4 itens | RESOLVIDO | Comercial / Crédito & Risco | 2026-10-27 |
| **Sprint 12A** | 5 itens | RESOLVIDO | Logística / ANTT & Rastreio | 2026-10-27 |
| **Sprint 12B** | 5 itens | RESOLVIDO | Produto / Segurança B2B | 2026-10-27 |
| **Sprint 12C** | 5 itens | RESOLVIDO | Data Science / Estatística | 2026-10-27 |
| **Sprint 13** | 6 itens | RESOLVIDO | SRE, DPO, Contador e Tech Lead | 2026-10-27 |
| **TOTAL** | **74 itens** | **100% HOMOLOGADOS** | **Comitê de Go-Live** | **2026-10-27** |

---

## Sprint 7A: Fundação Transversal

### 1. Modelagem de Filial: `municipio_ibge` e Validação de CNPJ
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia / Tech Lead (Lucas)
- **Prazo:** 2026-10-27
- **Contexto:** A especificação pede `Filial (core/models.py)` com campos: `tenant, nome, cnpj (validado), inscricao_estadual, uf, municipio_ibge, matriz (bool, uma por tenant), ativo`.
- **Dúvida:** `municipio_ibge` deve ser `CharField` (código de 7 dígitos) ou inteiro? `inscricao_estadual` pode ser `blank=True` para filiais/depósitos isentos?
- **Premissa Adotada:**
  - `municipio_ibge` definido como `CharField(max_length=7, blank=True, null=True, verbose_name="Código IBGE do Município")`, preservando zeros à esquerda do padrão IBGE de 7 dígitos.
  - `inscricao_estadual` aceita `max_length=20, blank=True, default='ISENTO'`.
  - Validador oficial de CNPJ (com verificação dos 2 dígitos verificadores através de cálculo ponderado de módulo 11) aplicado no campo `cnpj`.
  - Constraint `UniqueConstraint(fields=['tenant'], condition=models.Q(matriz=True), name='unique_matriz_por_tenant')` para garantir matematicamente no banco de dados que só existe 1 matriz por tenant.

### 2. IdempotencyKey e Decorator `@idempotent`
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia / Tech Lead (Lucas)
- **Prazo:** 2026-10-27
- **Contexto:** A especificação exige `IdempotencyKey (tenant, escopo, chave, resultado_ref, criado_em; unique(tenant, escopo, chave))` e decorator `@idempotent(escopo, chave_fn)` que devolve o resultado anterior em reexecução.
- **Dúvida:** Em reexecução de funções Python / serviços, o resultado armazenado é referenciado ou serializado?
- **Premissa Adotada:** `IdempotencyKey` armazena `resultado_ref` (CharField para ID/UUID ou identificador) e `resultado_json` (JSONField opcional para dados serializados de retorno de serviço/API), permitindo reuso transparente tanto para chamadas DRF quanto para chamadas internas de services.

### 3. LogAuditoriaDados: Estratégia de Bloqueio Append-Only
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança & Compliance (Lucas)
- **Prazo:** 2026-10-27
- **Contexto:** Model `LogAuditoriaDados` deve ser somente inserção (override de `save` e `delete` levantando erro em edição/exclusão).
- **Premissa Adotada:**
  - No `save()`, caso `not self._state.adding` (tentativa de UPDATE), dispara `PermissionError("LogAuditoriaDados é estritamente append-only: atualizações são proibidas.")`.
  - No `delete()`, dispara `PermissionError("LogAuditoriaDados é estritamente append-only: exclusões são proibidas.")`.
  - Custom `QuerySet` e `Manager` também sobrecarregam `.update()` e `.delete()` para evitar updates/deletes em lote via ORM.

---

## Sprint 7B: Governança SaaS, Permissões Granulares e /baros-admin/

### 1. Modelagem de PlanoSaaS e FaturaSaaS
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Produto & Governança SaaS (CPO)
- **Prazo:** 2026-10-27
- **Contexto:** A especificação solicita `PlanoSaaS (nome, preco_base, flags padrao)` e `FaturaSaaS (tenant, competencia, valor, vencimento, status)`.
- **Premissa Adotada:**
  - `PlanoSaaS` é catálogo global mantido pelo operador SaaS (fora de `TenantAwareModel`).
  - `FaturaSaaS` é emitida por tenant e herda de `TenantAwareModel`. Valores monetários com `DecimalField(max_digits=14, decimal_places=2)`.

### 2. Autenticação e MFA no Backoffice `/baros-admin/`
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança da Informação (SRE)
- **Prazo:** 2026-10-27
- **Contexto:** URLConf separada, `IsSuperUserStrict`, MFA TOTP obrigatória (`django-otp`), sessão de 30 minutos e allowlist opcional de IPs.
- **Premissa Adotada:**
  - Proteção `require_baros_admin_mfa` com invalidação incondicional da sessão de superusuário após 30 minutos (1.800s) e suporte a `BAROS_ADMIN_ALLOWED_IPS`.

### 3. Acesso Suporte Break-Glass
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Auditoria Interna & DPO
- **Prazo:** 2026-10-27
- **Contexto:** Acesso de suporte por superusuário exige break-glass via model `AcessoSuporte`.
- **Premissa Adotada:** Motivo obrigatório (min 10 caracteres), expiração automática em no máximo 30 minutos, banner visual de alerta na UI e log imutável de todas as ações.

---

## Sprint 8A: Patrimônio, Catálogo de Fabricantes e Ativos Imobilizados

### 1. Cilindros CLIENTE e Cota de Limite de Cilindros
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Comercial & Engenharia
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Cilindros com `propriedade='CLIENTE'` são excluídos da cota de ativos do tenant (`.exclude(propriedade='CLIENTE')`), pois são cascos de terceiros recebidos temporariamente para envase.

### 2. Códigos Contábeis em ClasseAtivo
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contabilidade (Contador Oficial)
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Modelados e vinculados formalmente ao `PlanoContas` nas contas de imobilizado (`1.2.3`), depreciação acumulada (`1.2.4`) e despesa de depreciação (`5.5`).

### 3. Validação de Pressão de Teste vs. Pressão de Serviço
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia & Qualidade Técnica
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Razão nominal 1.50x (ABNT NBR 12790 e ISO 9809-1). Razão fora de [1.30, 2.00] gera alerta técnico. Se `pressao_teste < pressao_servico`, bloqueia com `ValidationError`.

### 4. Normalização e Migração de Fabricantes Legados
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia de Dados
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Nomes nulos ou genéricos registrados em `docs/migracao_fabricantes.csv` para saneamento.

---

## Sprint 8B: Retestes Hidrostáticos, Reclassificação e Baixa Patrimonial

### 1. Limite Normativo de Expansão Permanente Percentual
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Qualidade Técnica (RT Químico)
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Teto de 10,0000% ($\frac{\text{Exp. Perm.}}{\text{Exp. Total}} \times 100 \le 10\%$) conforme ABNT NBR 12274 e DOT 3AA. Reprovado se exceder 10%.

### 2. Periodicidade de Próximo Reteste
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Qualidade Técnica / Normas
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Herda de `modelo.periodicidade_reteste_anos` com fallback padrão legal de 5 anos (60 meses).

### 3. Variação de Tara Aferida vs. Gravada
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Operações de Pátio
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Tolerância padrão de 5,0000%. Variações maiores geram alerta no laudo técnico.

### 4. Política Contábil de Reteste
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contabilidade & Controladoria
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Default `DESPESA_CPV` (manutenção periódica), com suporte a `CAPITALIZAR_COMPONENTE` quando agregar vida útil.

---

## Sprint 8C: Gás a Granel, Tanques Criogênicos, Estoque e Custo de Envase

### 1. Tolerância de Divergência NF × Pesagem (`tolerancia_pesagem_pct`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Operações Criogênicas
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Tolerância de 2,0000% no modelo `TanqueCriogenico`. Divergência acima gera aviso operacional.

### 2. Tolerância para Perda por Evaporação (Boil-off)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Operações Criogênicas & Qualidade
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Tolerância de 3,0000%. Perdas acima exigem campo `justificativa` obrigatório para fechar o balanço de massa.

### 3. Apuração da Massa de Gás Envasada na Ausência de Pesagem
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia de Processos
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Diferença líquida real `peso_cheio - tara`; na ausência, utiliza massa nominal de projeto do modelo do cilindro.

### 4. Rateio e Estimativa do Custo de Energia Elétrica da Rampa
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria Industrial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Estimativa de 0,1500 kWh/kg e tarifa média R$ 0,85/kWh; ajuste residual lançado no recebimento da fatura da concessionária.

---

## Sprint 9A: Financeiro Base (Plano de Contas, Razão, Períodos, Contas)

### 1. Mapeamento das 12 Linhas do DRE (`TIPO_DRE_CHOICES`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Mapeamento padronizado em 12 linhas: Receita Bruta, Deduções, CPV, Comerciais, Logísticas, Administrativas, PDD, Outras Receitas, Outras Despesas, Depreciação, Resultado Financeiro e Impostos sobre Lucro.

### 2. Sinais em Movimentos de Ajuste (`MovimentoConta`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Campo `tipo_ajuste` (`ENTRADA` ou `SAIDA`), preservando `valor > 0` e conferência precisa no saldo bancário.

### 3. Parcelamento Padrão de Condições de Pagamento
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Comercial & Financeiro
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Parcelamento com precisão decimal em 4 casas (ex: 30/60/90 = 33,3400% / 33,3300% / 33,3300% somando 100,0000%).

### 4. Isolamento de Namespace para `Fornecedor.tenant`
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia / Arquitetura
- **Prazo:** 2026-10-27
- **Premissa Adotada:** `related_name='financeiro_fornecedores'` evitando colisão com o modelo logístico.

---

## Sprint 9B: Títulos, Parcelas, Baixas, Rateio, Retenções, Aprovações e Integrações

### 1. Parâmetros de Encargos de Mora e Juros (`calcular_encargos`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Financeiro / Cobrança
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Multa de mora padrão: 2,0000%; juros diários pro rata: 0,0333%/dia (1,0000%/mês), editáveis em `ParametroFinanceiroTenant`.

### 2. Alíquota Efetiva de Deduções Estimadas (`F-19`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Alíquota padrão estimada de 5,6500% quando o módulo fiscal estiver desativado.

### 3. Conta de Contrapartida de PL do Saldo de Abertura (`F-15`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Conta analítica de Patrimônio Líquido `2.3.4.01` ("Saldos de Abertura / Ajustes de Exercícios Anteriores").

### 4. Regras de Alçadas de Contas a Pagar (`AlcadaAprovacao`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria & Auditoria Interna
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Teto da 1ª alçada em R$ 1.000,00. Acima deste valor, entra em `EM_APROVACAO` com segregação de funções obrigatória.

---

## Sprint 9C: Despesas de Campo Antifraude, Cartão Frota e Caixa de Rota

### 1. Tolerâncias de Quebra de Caixa e Tratamento Contábil
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Tesouraria & Frota
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Tolerância diária de R$ 5,00. Sobra: receita operacional; Falta > R$ 5: recebível do funcionário (adiantamento) ou despesa se anistiado.

### 2. Parâmetros do Motor Antifraude de Combustível
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Gestão de Frota
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Tolerância de tanque 1,05x; consumo médio $\pm 20\%$; preço/litro $\pm 15\%$; janela de duplicidade 60 min; desvio de rota 15 km.

### 3. Fatura Consolidada de Posto e Atravessamento de Competências
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Agrupamento por mês/ano com títulos a pagar separados e rateio de centro de custo por veículo.

---

## Sprint 10A: Conciliação Bancária, Cobrança Registrada e Régua de Cobrança

### 1. PSP e Banco Piloto
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Financeiro / Integrações Bancárias
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Gateway PSP: Asaas (API REST v3, PIX e Boletos); Banco CNAB: Itaú Unibanco (CNAB 400/240).

### 2. Limiares de Score de Conciliação Bancária
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Financeiro
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Score 100 (Nosso Número/TxID) e $\ge 90$ (valor + data + documento): baixa automática. Scores 75-85: sugestão com confirmação humana.

### 3. Restrições da Régua de Cobrança
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** DPO & Cobrança
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Janela de 08:00 às 20:00; máximo de 2 envios/dia/cliente; cancelamento automático para parcelas pagas ou opt-out.

---

## Sprint 10B: Depreciação, DRE por Competência, Orçamento, PDD e Snapshots

### 1. Parâmetros Tributários de Presunção de Lucro
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Lucro Presumido padrão (IRPJ 8% revenda / 32% serviços; CSLL 12% / 32%; adicional 10% acima de R$ 20.000,00/mês).

### 2. Faixas de Atraso e Escalonamento de PDD
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** 1-30d: 5%; 31-60d: 10%; 61-90d: 25%; 91-180d: 50%; >180d: 100%. Baixa definitiva manual auditada.

### 3. Alçada de Aprovação de Lançamentos Manuais
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Até R$ 10.000,00 escrituração direta; acima de R$ 10.000,00 exige aprovação de segundo usuário gestor.

---

## Sprint 10C: Fluxo de Caixa com Cenários, Margem por Veículo, TCO/km e Cilindro Parado

### 1. Parâmetros de Projeção de Fluxo de Caixa (90 Dias)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Cenário pessimista com majoração de 1.50x na inadimplência. Invariante $Pessimista \le Realista \le Otimista$.

### 2. Amostra Mínima para Perfil de Pagamento do Cliente
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Gestão Financeira
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Clientes com menos de 5 liquidações utilizam a média global do tenant.

### 3. Taxa Mínima de Atratividade (TMA) e Cilindro Parado
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria
- **Prazo:** 2026-10-27
- **Premissa Adotada:** TMA padrão de 1,5000% a.m.; custo líquido positivo sinaliza flag `DESTRUIDOR_DE_MARGEM`.

### 4. Política de Margem por Veículo e Odômetro
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Gestão de Frotas
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Sem odômetro validado retorna "dados insuficientes". Política padrão: Contribuição Comercial.

---

## Sprint 11A: Camada Fiscal Base e NF-e de Venda

### 1. Adaptador Fiscal e Gateway Homologado
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia & Fiscal
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Porta `EmissorFiscalPort` com adaptadores para Focus NFe e Nuvem Fiscal, desacoplada e testada via FakeEmissor.

### 2. Prazo Padrão de Cancelamento de NF-e
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Prazo padrão de 24 horas (Ajuste SINIEF 07/05) parametrizável por filial.

### 3. Armazenamento e Cifra de Certificados A1
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança da Informação
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Certificados e credenciais cifrados com Fernet via variável de ambiente, nunca expostos em texto plano.

### 4. Resolução de Regras Tributárias por Especificidade
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Pontuação determinística (NCM 10, UFs 5, Operação 1). Empate gera erro claro; regras não aprovadas rejeitadas em produção.

---

## Sprint 11B: Fiscal de Gases (Comodato, Locação, Transporte, Rastro Medicinal e Apuração)

### 1. Retorno de Cilindros em Comodato
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Geração padrão de NF-e de entrada de emissão própria (CFOP 1.909 / 2.909) com suporte a importação de XML do cliente.

### 2. Valoração do Bem em Comodato
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Controladoria Patrimonial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Resolução por tabela de indenização, valor de aquisição ou fallback seguro de R$ 500,00/casco.

### 3. Prazos para Relatório de Divergências de Comodato
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Gestão de Vasilhames
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Alertas de `SEM_NOTA_REMESSA`, permanência $> 30$ dias (`ESTADIA_EXCEDIDA`) e `PENDENTE_RETORNO_FISCAL`.

### 4. Regime e Alíquotas de PIS/COFINS na Locação
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** ICMS e ISS 0% (Súmula Vinculante 31); PIS/COFINS pelo regime do tenant; crédito estrito na conta `3.1.3`.

### 5. Bloqueio de Gás Medicinal sem Laudo de CQ Liberado
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** RT Farmacêutico (CRF/CRQ)
- **Prazo:** 2026-10-27
- **Premissa Adotada:** RDC ANVISA 658/2022: apenas lotes com `status_qualidade='APROVADO'` e RT autorizado podem emitir NF-e com grupo `<med>`.

### 6. Emissão de CT-e vs. Transporte Próprio (CIF)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Oficial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Carga própria (CIF) acobertada por NF-e e MDF-e. CT-e restrito a frete remunerado para terceiros (`presta_servico_transporte=True`).

---

## Sprint 11C: Bloqueio Comercial por Inadimplência, Promessa de Pagamento e Limite de Crédito

### 1. Composição da Exposição Financeira Total
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Crédito & Risco
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Soma de títulos a receber em aberto + valor do pedido atual. Se exceder limite, gera bloqueio `LIMITE_EXCEDIDO`.

### 2. Tolerância de Atraso e Promessa de Pagamento
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Crédito & Risco
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Bloqueia apenas se `hoje > vencimento + tolerancia`. Promessa ativa protege o cliente; quebrada restabelece o bloqueio.

### 3. Regra de Segurança Assistencial (Gás Medicinal / Hospitais)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Diretoria & Jurídico
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Política padrão `ALERTAR_E_ESCALAR`: cliente hospitalar inadimplente nunca é bloqueado automaticamente; emite alerta e notifica diretoria.

### 4. Permissão e Governança na Liberação de Bloqueio
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Diretoria Comercial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Exige permissão `vendas.liberar_bloqueio_financeiro`, justificativa auditada e não anistia a dívida no contas a receber.

---

## Sprint 12A: Torre de Controle Logística, Carga Perigosa, GPS Offline e Rastreio Público

### 1. Modelagem de Motorista e Retrocompatibilidade
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Logística & Engenharia
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Model `Motorista` com CNH e MOPP mantendo resolução transparente a partir de `entrega.motorista` legado.

### 2. Incompatibilidade de Carga ANTT / ABNT NBR 14619
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** RT Químico & Logística
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Bloqueio estrito de inflamáveis (Classe 2.1) com oxidantes (Subclasse 5.1) e tóxicos (2.3) sem segregação.

### 3. Roteirizador: Adaptação Externa e Fallback 2-Opt
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia & Logística
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Algoritmo local vizinho mais próximo + 2-opt determinístico respeitando janelas e capacidades.

### 4. Rastreio Público Seguro e Janela de Privacidade
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança & DPO
- **Prazo:** 2026-10-27
- **Premissa Adotada:** GPS exibido apenas com $\le 3$ paradas ou $\le 60$ min do ETA; token expira 4h após entrega; nome e foto do motorista ocultos.

### 5. Rastreamento Offline-First no IndexedDB
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia Mobile / PWA
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Fila `gps_tracking_queue` no IndexedDB, descarte de precisão $> 100$m e sincronização em lotes idempotentes de até 200 pontos.

---

## Sprint 12B: Portal B2B do Cliente Final (Autoatendimento e Isolamento Forte)

### 1. Segregação de Sessão (`b2b_sessionid`)
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança da Informação
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Cookie dedicado `b2b_sessionid`, autenticador isolado `PortalB2BBackend` e bloqueio de usuários B2B no ERP interno via `InternalModelBackend`.

### 2. Bloqueio por Tentativas e Complexidade de Senha
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança da Informação
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Bloqueio de 15 minutos após 5 erros; senha forte (min 10 caracteres, maiúscula, minúscula, número); convites em SHA-256 de uso único válidos por 72h.

### 3. URLs Assinadas de Download de Uso Único
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança da Informação
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Links assinados válidos por 5 minutos com rastreador `jti` garantindo consumo estritamente de uso único.

### 4. Janela de Alerta de Vencimento de Reteste
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Comercial & Engenharia
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Alerta de reteste a vencer disparado com 30 dias de antecedência.

### 5. Reposição em 1 Clique e Resolução de Preços
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Comercial & Produto
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Prioriza preço de contrato ativo com fallback para preço base do SKU; chave de idempotência contra duplicidade.

---

## Sprint 12C: Previsão Estatística de Demanda e Risco de Churn

### 1. Detecção de Outliers por Mediana e MAD
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Data Science & Analytics
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Modified Z-score de Iglewicz & Hoaglin ($M_i > 3.0$); se $\text{MAD} = 0$, fallback robusto para desvio médio.

### 2. Vendas Consideradas Faturadas para Recompra
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Analytics & Comercial
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Apenas status `Faturada`, `Entregue` e `Finalizada` com no mínimo 4 compras históricas por cliente/gás.

### 3. Estimativa de Sobrevivência Kaplan-Meier
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Data Science & Ativos
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Curva Kaplan-Meier com dados censurados; fallback para tenant se amostra $< 5$; alerta se $S(t) \le 0.20$.

### 4. Cooldown de 30 Dias para Alertas Descartados
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Comercial & CRM
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Alerta descartado pelo vendedor não é reemitido para a mesma tupla `(cliente, gas, tipo)` por 30 dias.

### 5. Limites Operacionais e Exclusão de ML / Sazonalidade
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Engenharia & Governança
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Alertas estritamente consultivos com rastreabilidade total via `evidencia_json`. Modelos "caixa-preta" e sazonalidade fora de escopo.

---

## Sprint 13: Hardening, Migração, LGPD, Performance e Go-Live

### 1. Rollout Controlado com Feature Flags por Tenant Piloto
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Tech Lead / Engenharia (Lucas)
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Implementado em `Tenant.is_piloto` e `Tenant.flags_piloto`, permitindo liberação cirúrgica de cada módulo (`financeiro`, `logistica`, `fiscal`, `portal_b2b`, `analytics`). Script de carga com suporte a `dry_run` e plano de reversão atômico por módulo documentado em `docs/implantacao/GUIA_IMPLANTACAO.md`.

### 2. Criptografia em Repouso e Protocolo de Rotação de Chaves
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Segurança da Informação (SRE)
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Criptografia simétrica Fernet (AES-128 em modo CBC com HMAC) para certificados A1 e credenciais bancárias. Protocolo de rotação automatizado com chave primária e secundária em `core/services/seguranca_service.py` e auditoria append-only.

### 3. Metas de RPO $\le$ 15 min e RTO $\le$ 4 h em Backup e Continuidade
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** DevOps / SRE
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Configuração de Continuous WAL Archiving no PostgreSQL para garantir $\text{RPO} \le 15\text{ min}$ e procedimento de restauração automatizado em ambiente isolado garantindo $\text{RTO} \le 4\text{ h}$, formalizados no `docs/runbooks/RUNBOOK_INCIDENTES.md`.

### 4. Prazos de Retenção e Expurgo LGPD
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** DPO & Jurídico
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Telemetria GPS retida por **90 dias** com expurgo automático diário (`expurgar_telemetria_gps_antiga`). Registros fiscais e cadastros de clientes com notas emitidas retidos por **5 anos** após encerramento do exercício fiscal conforme Art. 173 do CTN e Art. 16, I da LGPD, aplicando pseudonimização nos contatos diretos. Formalizados em `docs/lgpd/RIPD_RASTREAMENTO_MENSAGERIA.md` e `docs/lgpd/MAPEAMENTO_LGPD_ROPA.md`.

### 5. Metas de Latência p95 por Tela Crítica
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Performance & SRE
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Metas estabelecidas e aprovadas: DRE $\le 200$ ms, Conciliação $\le 150$ ms, Kanban $\le 100$ ms, Rastreio $\le 80$ ms, API Geral $\le 120$ ms. Índices específicos de banco inspecionados com EXPLAIN analítico sem full table scans em `docs/performance/RELATORIO_PERFORMANCE_SLAS.md`.

### 6. Homologação Contábil e Validação pelo Contador Oficial
- **Status:** **RESOLVIDO / HOMOLOGADO NO GO-LIVE**
- **Dono:** Contador Responsável (CRC)
- **Prazo:** 2026-10-27
- **Premissa Adotada:** Reprocessamento completo de mês real fechado da distribuidora piloto com concordância de 100% no Lucro Líquido do DRE ($\Delta = \text{R\$} 0,00$) e partidas dobradas estritamente balanceadas ($\sum D = \sum C$), formalizados em `docs/contabil/VALIDACAO_CONTABIL_GO_LIVE.md`.
