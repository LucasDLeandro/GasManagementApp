# Sprint 07: Logística, dividir a tela gigante, entregas e torre de controle

> Cole esta mensagem inteira no agente.

**Antes de começar, leia:** `docs/sprints/00_REGRAS_GERAIS.md` (obrigatório), `docs/DESIGN_SYSTEM.md`, a seção 7 de `docs/GUIA_MODULOS_BAROS.md`, a "FASE 4" de `docs/PLANO_CORRECAO_E_EVOLUCAO.md`, a seção "Sprint 12A" de `docs/DECISOES_PENDENTES.md` e `docs/adr/ADR-043-roteirizacao-e-rastreamento-logistico.md`.
**Branch:** `sprint-07/logistica-entregas` a partir de `sprint-06/clientes-vendas`.

## Objetivo
`logistica/templates/logistica/index.html` tem cerca de 3.600 linhas, 110 modais e 648 estilos inline, e `logistica/static/logistica/js/index.js` é igualmente grande. Esta sprint divide o módulo em páginas e refaz o coração dele: **montagem e despacho de entregas** e a **torre de controle**.

## O que já existe
- Abas atuais: Quadro de Entregas, Frota/Veículos, Rotas/Fretes, Combustível, Manutenção, Seguros & Sinistros, Rentabilidade, Histórico & Comprovantes.
- APIs em `logistica/urls.py` (27 rotas no router e cerca de 30 paths), entre elas: `entregas`, `paradas`, `validacoes`, `regras-incompatibilidade`, `motoristas`, `capacidades-veiculo-cilindro`, `alocacoes-equipe`, além de `api/tracking/sync/` e da otimização de paradas (`OtimizarOrdemParadasAPIView`).
- Serviços: `logistica/services/carga.py` (`validar_carga`, `liberar_carga_bloqueada`, `despachar_entrega_para_rota`), `routing.py` (`otimizar_ordem_paradas`, que devolve `paradas_ordenadas`, `distancia_total_km` e `tempo_total_min`), `paradas_service.py`, `rastreamento_service.py`, `rastreio_publico_service.py` e `validacao_carga.py`.
- O rastreio público (`/rastreio/<token>/`) foi corrigido na Fase 0. Não mude o contrato do JSON dele.

## Tarefas

### 07.1 Dividir em páginas (sem mudar comportamento)
- Criar o submenu Logística, com uma página por área: `/logistica/entregas/`, `/logistica/frota/`, `/logistica/combustivel/`, `/logistica/manutencao/`, `/logistica/seguros/`, `/logistica/rentabilidade/`. `/logistica/` redireciona para `/logistica/entregas/`.
- Cada página com o template base próprio (`logistica/templates/logistica/<area>/index.html` + parciais) e o seu JS (`logistica/static/logistica/js/<area>.js`). O código que serve várias páginas vai para `logistica/static/logistica/js/comum.js`.
- **Primeiro só mova** o código, sem redesenhar. Confira página por página que tudo continua funcionando e faça commit. Só depois comece 07.2.
- Remover o código morto encontrado (funções JS sem chamada, modais sem botão que os abra), listando-os no relatório.

### 07.2 Montagem de entrega (redesign)
- **Wizard "Nova entrega"**: Vendas (seleciona pedidos em separação, agrupados por região) → Cilindros (aloca e bipa; `alocar_cilindro_rota`) → Veículo e motorista (capacidade por tipo de cilindro, CNH/MOPP vencidos bloqueiam) → **Validação de carga** (`validar_carga`: incompatibilidade ANTT/NBR 14619, peso e capacidade; se bloquear, mostra o motivo e oferece "Liberar com justificativa" para ADMIN e GERENTE) → Ordem das paradas (`otimizar_ordem_paradas`, com a lista ordenada e o mapa, que permite arrastar e travar paradas) → Revisão e **Despachar** (`despachar_entrega_para_rota`).
- **Quadro de entregas**: colunas por status (Agendada, Em produção, Em rota, Concluída), com cartões e filtros por data e motorista.

### 07.3 Torre de controle
- Página `/logistica/torre/`: mapa com os veículos em rota (última posição de `CoordenadaRastreamento`), paradas com status e ETA, e lista lateral de entregas em rota com atraso destacado. Atualiza a cada 30 segundos (polling simples).
- **Mapa:** use Leaflet **hospedado no projeto** (copie para `static/vendor/leaflet/`; não use unpkg). Corrija também `logistica/templates/logistica/rastreio_publico.html`, que hoje carrega Leaflet e Google Fonts de CDN (regra D5).

## Critérios de aceite
- Nenhuma página nova de logística passa de cerca de 800 linhas de template; zero estilos inline nas áreas de Entregas e Torre.
- Criar, validar, roteirizar e despachar uma entrega pela tela; acompanhar na torre.
- O rastreio público continua respondendo igual (os testes em `logistica/tests/test_sprint8_tracking_roteirizacao.py` devem passar sem alteração).
- Suíte verde.

## Testes obrigatórios
- Cada página nova renderiza (200) para GERENTE e redireciona ou responde 403 para quem não tem o módulo logística.
- Validação bloqueada sem liberação não deixa despachar.
- Endpoint da torre (crie `GET /logistica/api/torre/` agregando posição e paradas, se necessário): isolamento entre empresas.

## Fora do escopo
Redesign de frota, combustível, manutenção e seguros (Sprint 08).

## Entrega
Seção 7 das regras gerais. Relatório: `docs/sprints/relatorios/SPRINT_07.md`.
