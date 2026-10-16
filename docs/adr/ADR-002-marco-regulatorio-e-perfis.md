# ADR 002: Marco Regulatório ANVISA, Perfis de Operação (Envasadora vs. Distribuidora) e Responsabilidade Técnica Farmacêutica

**Status:** Aprovado  
**Data:** 15 de Outubro de 2026  
**Contexto de Negócio:** Conformidade Sanitária, Boas Práticas de Fabricação (BPF) e Farmacovigilância ANVISA  
**Decisores:** Arquiteto de Software, Farmacêutico Responsável Técnico, Especialista Regulatório  

---

## 1. Contexto e Problema

Gases medicinais (Oxigênio Medicinal, Óxido Nitroso, Ar Comprimido Medicinal, Misturas Carbógenas) são classificados pela legislação sanitária brasileira como **medicamentos** de uso hospitalar e domiciliar, sujeitos ao controle estrito da Agência Nacional de Vigilância Sanitária (ANVISA) e dos Conselhos Profissionais (CRF e CRQ).

Historicamente, o sistema continha referências desatualizadas a normas revogadas (RDC nº 69/2008 e RDC nº 67/2007) e tratava todas as distribuidoras de gás como se fossem plantas fabris envasadoras, sem distinguir:
- As empresas autorizadas a **envasar e fabricar** lotes medicinais (exigência de CBPF de fabricante);
- As empresas autorizadas exclusivamente a **distribuir, armazenar e transportar** cilindros já envasados por terceiros qualificados.

Além disso, a assunção de Responsabilidade Técnica (RT) era tratada apenas como um texto livre no lote, sem validação da vigência formal do profissional perante a certidão de regularidade do conselho de classe.

---

## 2. Decisão Arquitetural

Adotamos a **modernização regulatória integral** da plataforma, alinhando a arquitetura multi-tenant aos marcos legais vigentes no Brasil.

### 2.1. Marco Regulatório Vigente Adotado
1. **RDC nº 658/2022 (Diretrizes Gerais de BPF de Medicamentos):**
   Estabelece o Sistema de Gestão da Qualidade Farmacêutica, qualificação de fornecedores, controle de mudanças e auditorias.
2. **Instrução Normativa (IN) nº 129/2022 (BPF para Gases Medicinais):**
   Norma complementar obrigatória para empresas que executam envase e purificação. Rege a rastreabilidade por lote químico, pureza analítica mínima, laudos laboratoriais e retenção de contraprovas.
3. **RDC nº 870/2024 (Registro e Notificação de Gases Medicinais):**
   Normatiza os requisitos de registro e notificação de gases medicinais na ANVISA, substituindo os procedimentos arcaicos anteriores.
4. **RDC nº 887/2024 (Boas Práticas de Distribuição, Armazenagem e Transporte de Medicamentos):**
   Regulamenta os operadores que não envasam, mas transportam e estocam cilindros cheios (distribuidores e operadores logísticos).

### 2.2. Perfis de Operação Sanitária do Tenant
A entidade `PerfilRegulatorioTenant` passa a tipificar formalmente cada distribuidora cliente do SaaS em três modos:

| Modo de Operação | Escopo Autorizado | Normas Exigidas | Exigência de CBPF? |
| :--- | :--- | :--- | :---: |
| **`ENVASADORA`** | Envasa lotes químicos a granel em cilindros próprios ou de terceiros | RDC 658/2022 + IN 129/2022 + RDC 870/2024 | **Sim (Obrigatório)** |
| **`DISTRIBUIDORA`** | Armazena, fraciona e entrega cilindros lacrados procedentes de envasadoras qualificadas | RDC 887/2024 + Licença Sanitária local + AFE | **Não** (CBPF não aplicável a distribuidor puro) |
| **`MISTO`** | Opera tanto planta de envase quanto entreposto logístico de distribuição | Todas as normas acima cumulativamente | **Sim (Obrigatório)** |

### 2.3. Habilitação e Atribuições do Responsável Técnico (RT)
Conforme a **Resolução CFF nº 731/2022** do Conselho Federal de Farmácia e normas congêneres do Conselho Federal de Química (CFQ):
- É mandatório que o tenant possua profissional legalmente habilitado registrado na entidade `ResponsavelTecnico`.
- O sistema valida a **Certidão de Regularidade Técnica (CRT)** do RT (`vigencia_inicio` e `vigencia_fim`), seu conselho (`CRF` ou `CRQ`), número e UF.
- O método validador `validar_aptidao_medicinal(tenant, exigir_envase=False)` bloqueia de forma *fail-closed* qualquer tentativa de envase ou expedição caso o RT esteja ausente, inativo ou com vigência expirada.

### 2.4. Trava Sanitária nos Serviços de Negócio
- Tentativas de acionar `registrar_envase_cilindro` em gás medicinal com `exigir_envase=True` verificam se o tenant possui modo `ENVASADORA` ou `MISTO` e se o `CBPF` está vigente perante a ANVISA.
- Uma distribuidora pura que tentar registrar um envase recebe `ValidationError` impeditivo com base na IN 129/2022.

---

## 3. Consequências

### Positivas
- **Conformidade em Fiscalizações:** A distribuidora ou envasadora operando o software apresenta evidência documental imediata de adequação às normas sanitárias vigentes.
- **Segurança ao Paciente e Clínicas:** Impede que empresas não certificadas para envase comercializem gases medicinais sob suspeita de contaminação cruzada ou falta de pureza analítica.
- **Rastreabilidade para o Notivisa:** Toda ordem de recolhimento sanitário é amparada pela cadeia de custódia e assinatura técnica do RT cadastrado.

### Próximos Passos
- Na Sprint 5A.4, integração do fluxo de Dossiê Notivisa com disparo de comunicados sanitários automáticos com chave de autenticidade digital do RT.
