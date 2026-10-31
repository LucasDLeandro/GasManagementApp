# Sprint 08: Logística, frota, combustível, manutenção, seguros e cadastros que faltam

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 7.2 de `docs/GUIA_MODULOS_BAROS.md` e a "FASE 4" (4.2.3, 4.2.4 e 4.3) de `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.
**Branch:** `sprint-08/logistica-frota` a partir de `sprint-07/logistica-entregas`.

## Objetivo
Redesenhar as páginas de Frota, Combustível, Manutenção, Seguros e Rentabilidade (já separadas na Sprint 07) e criar as telas de cadastros de logística que hoje só existem na API.

## O que já existe
- Páginas separadas na Sprint 07, ainda com o visual antigo.
- Serviços: `combustivel.py` (`processar_abastecimento` com alertas antifraude), `manutencao.py`, `seguros_sinistros.py` (máquina de estados do sinistro), `rentabilidade.py`, `margem_veiculo_service.py`, `fipe.py` e `anp.py`.
- APIs: `veiculos`, `abastecimentos`, `combustivel/precos-referencia`, `fornecedores`, `planos-manutencao`, `ordens-servico`, `os-itens`, `checklists-modelos`, `checklists`, `apolices`, `apolices-seguro`, `sinistros`, `custos-viagem`, `custos-viagem-itens`, `tabelas-frete-interno`, `motoristas`, `regras-incompatibilidade`, `capacidades-veiculo-cilindro`, `alocacoes-equipe`.
- A Fase 0 adicionou `ordering = ['placa']` em `Veiculo`.

## Tarefas

### 08.1 Frota
- Lista de veículos com status, documentos vencendo (CRLV, RNTRC, CIPP/CIV) e cartões de métrica.
- Cadastro de veículo em etapas (já existe um stepper: alinhar ao Design System): Dados → FIPE (consulta) → Capacidades por tipo de cilindro → Documentos e fotos → Revisão.
- Detalhe do veículo em drawer: documentos, fotos, OS, sinistros, abastecimentos e TCO.

### 08.2 Combustível
- Registro de abastecimento (modal), lista com alertas antifraude em destaque (consumo fora da curva, preço acima da referência ANP, odômetro inconsistente) e tela de preços de referência ANP (importação já existe no comando `importar_precos_anp`).

### 08.3 Manutenção
- **Kanban de OS** (`Aberta → Orçada → Aprovada → Em Execução → Concluída`), arrastando entre colunas só pelas transições válidas (valide no backend; se a máquina de estados não existir, crie-a em `logistica/services/manutencao.py`).
- OS em etapas: Veículo e tipo → Itens (peças e serviços) → Fornecedor e orçamento → Revisão. Aprovação só ADMIN e GERENTE.
- Planos preventivos, modelos de checklist e checklists realizados (que geram OS).

### 08.4 Seguros e sinistros
- Apólices (coberturas e veículos segurados).
- Sinistro com **linha do tempo** (`Rascunho → Registrado → Comunicado à Seguradora → Em Análise → Em Vistoria → Aprovado/Negado → Indenizado → Encerrado`), anexos, itens de carga e OS vinculada; botões só com as transições válidas (`transicionar_status_sinistro`).

### 08.5 Rentabilidade
- Painel com TCO por veículo, margem de contribuição, custo por km e alertas de baixa ocupação, com gráficos de `static/vendor/chartjs` e exportação CSV (já existe `gerar_csv_rentabilidade`).

### 08.6 Cadastros novos (backend pronto, sem tela)
- **Motoristas** (CNH com categoria e validade, MOPP com validade, vínculo com usuário) e **alocação motorista × veículo**. Alertas de vencimento.
- **Regras de incompatibilidade de carga** (ANTT/NBR 14619: par de classes → BLOQUEAR ou AVISAR) e lista de **liberações** já concedidas (somente leitura).
- **Capacidade veículo × tipo de cilindro** e **tabelas de frete interno** (por km ou por parada).
- Fila de **validações de carga pendentes de aprovação** para o gerente.

## Critérios de aceite
- Zero estilos inline e zero `alert`/`confirm`/`prompt` em todo o módulo logística (exceto o App de Campo, que é a Sprint 14).
- Transições de OS e de sinistro validadas no backend.
- Suíte verde.

## Testes obrigatórios
- Transição inválida de OS e de sinistro responde 400; aprovação de OS por papel sem permissão responde 403.
- Alertas de CNH e MOPP vencidos.
- Renderização das páginas.

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_08.md`.
