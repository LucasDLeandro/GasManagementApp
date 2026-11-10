# Sprint 16: Laboratório de controle de qualidade (CQ)

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 5 de `docs/GUIA_MODULOS_BAROS.md`, a "FASE 10" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md` e as seções 11B e de envase de `docs/DECISOES_PENDENTES.md`.
**Branch:** `sprint-16/laboratorio-cq` a partir da última branch de sprint mergeada.

> ⚠️ **Decisão do dono antes de começar:** a lista de parâmetros por gás e grau (medicinal, industrial, alimentício), os limites de cada um e o **plano de amostragem** (quantos cilindros por lote, teste de identidade por cilindro ou não) precisam ser validados pelo Responsável Técnico ou pela assessoria regulatória da empresa. O sistema deve deixar tudo isso **configurável**; os valores de exemplo do `populate_db.py` são só para teste e precisam estar marcados como tal.

## Objetivo
Hoje o controle de qualidade do lote é um único número (`LoteEnvase.pureza_percentual`) e um PDF de laudo enviado à mão. Esta sprint cria o laboratório: especificações por gás, equipamentos com calibração, análises com resultado por parâmetro, aprovação automática contra a especificação com homologação do RT, e o certificado de análise gerado pelo sistema.

## O que já existe (não refazer)
- `LoteEnvase` com `status_qualidade` (`QUARENTENA`/`APROVADO`/`REPROVADO`), `pureza_percentual`, `laudo_pdf`, RT com snapshot (`responsavel_tecnico_fk`, `rt_*_snapshot`).
- Bloqueio de entrega e de rota para cilindro cujo lote não está `APROVADO` (`produtos/services/ciclo_cilindro.py`).
- `RecebimentoCilindroCheio.laudo_pdf` (laudo do fornecedor) e `EntradaGasGranel` (entrada no tanque).
- Recall ANVISA (`RecallCampanha`) e dossiê do lote (`produtos/services/dossie_builder.py`).
- Se a Sprint 04 implementou a 04.5, o lote já nasce em `QUARENTENA`.

## Tarefas

### 16.1 Especificações por gás
- `EspecificacaoGas` (`TenantAwareModel`): `gas`, `grau` (`MEDICINAL`, `INDUSTRIAL`, `ALIMENTICIO`, `ANALITICO`), `versao`, `vigente_desde`, `referencia_normativa` (texto livre, ex.: monografia da Farmacopeia), `aprovada_por` (RT), `ativa`. Versões antigas ficam guardadas: a análise aponta para a versão usada.
- `ParametroEspecificacao`: `especificacao`, `nome` (pureza, umidade, CO, CO₂, óleo, odor, identidade...), `unidade` (%, ppm, ppm v/v, qualitativo), `tipo_limite` (`MINIMO`, `MAXIMO`, `FAIXA`, `QUALITATIVO`), `limite_min`, `limite_max`, `obrigatorio`, `metodo` (texto).
- Plano de amostragem na especificação: `amostras_por_lote` (número fixo ou % do lote) e `identidade_por_cilindro` (bool).
- Tela de cadastro (ADMIN, GERENTE e RT; só o RT aprova uma versão).

### 16.2 Equipamentos de laboratório e calibração
- `EquipamentoLaboratorio`: `nome`, `tipo` (analisador de O₂, higrômetro, cromatógrafo, tubos colorimétricos, outro), `fabricante`, `numero_serie`, `parametros_que_mede` (M2M com nomes de parâmetro), `ativo`.
- `CalibracaoEquipamento`: `equipamento`, `data`, `validade`, `laboratorio_calibrador`, `certificado_pdf`, `resultado` (aprovado/reprovado).
- **Equipamento com calibração vencida ou reprovada não pode ser usado em análise** (validação no backend). Alerta de calibração vencendo em 30 dias na fila do RT e no monitor (Sprint 01B, seção Fábrica).

### 16.3 Análises
- `AnaliseLote`: `lote`, `especificacao` (versão usada), `analista` (User), `iniciada_em`, `concluida_em`, `resultado_geral` (`CONFORME`/`NAO_CONFORME`, calculado), `observacoes`.
- `AmostraAnalise`: `analise`, `cilindro` (o cilindro amostrado do lote; validar que pertence ao lote).
- `ResultadoParametro`: `amostra`, `parametro`, `equipamento`, `valor_medido` (decimal) ou `valor_qualitativo`, `conforme` (calculado contra o limite, nunca informado à mão).
- Fluxo em etapas na tela: escolher o lote em quarentena → amostras (sugere a quantidade do plano) → resultados por parâmetro (com conformidade ao vivo) → revisão → enviar para o RT.
- `pureza_percentual` do lote passa a ser preenchida a partir do resultado (menor pureza medida entre as amostras), não digitada.
- Resultado imutável depois de enviado ao RT: correção só por nova análise com referência à anterior (`retifica`), como já é feito no histórico de retestes.

### 16.4 Liberação pelo RT
- O RT vê a análise e homologa: **aprovar** (só se `resultado_geral=CONFORME`) ou **reprovar**. Lote reprovado → bloqueio sanitário de todos os cilindros do lote (`AuditoriaBloqueioSanitario`) e abertura de um registro de não conformidade.
- `NaoConformidade`: `lote`, `analise`, `descricao`, `causa_provavel`, `acao_corretiva`, `responsavel`, `prazo`, `status`. Atalho para abrir um recall se cilindros do lote já saíram.

### 16.5 Certificado de análise (CoA)
- PDF gerado pelo sistema por lote aprovado: empresa, gás, grau, lote, data de envase e validade, especificação (versão e referência), resultados por parâmetro com limites, equipamentos usados (com nº de série e validade da calibração), analista e RT (com conselho e registro).
- Disponível no detalhe do lote, no dossiê do lote e no Portal B2B (laudo do cilindro em posse do cliente; Sprint 14). O `laudo_pdf` manual continua aceito para lotes antigos.

### 16.6 Análise de entrada do gás a granel
- Ao registrar uma `EntradaGasGranel`, anexar o certificado do fornecedor e, se a especificação exigir, registrar uma análise de entrada (mesmo modelo de 16.3, ligada à entrada e não a um lote). Entrada não conforme → tanque marcado "em análise" e a rampa não deixa abrir lote desse tanque até a liberação.

### 16.7 Painel do laboratório
- Página `/produtos/laboratorio/` (módulo envase; RT, ADMIN, GERENTE e um novo papel `ANALISTA_CQ` se o dono aprovar, senão o RT faz tudo): lotes aguardando análise, análises aguardando o RT, não conformidades abertas, calibrações vencendo, tempo médio entre envase e liberação.

## Critérios de aceite
- Fluxo completo na tela: envase → lote em quarentena → análise com 2 amostras → conformidade calculada → RT aprova → CoA gerado → cilindro pode sair para rota.
- Lote com um parâmetro fora do limite não pode ser aprovado; ao reprovar, os cilindros ficam bloqueados.
- Equipamento descalibrado é recusado no backend.
- Suíte verde.

## Testes obrigatórios
- Conformidade calculada para cada `tipo_limite` (mínimo, máximo, faixa, qualitativo), incluindo valores exatamente no limite.
- Só o RT aprova/reprova; o analista não consegue.
- Reprovação bloqueia todos os cilindros do lote.
- Análise usa a versão da especificação vigente na data da análise.
- Isolamento entre empresas em todos os endpoints novos.

## Fora do escopo
Integração direta com analisadores (leitura automática por serial/USB/rede) e LIMS externo: roadmap.

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_16.md`.
