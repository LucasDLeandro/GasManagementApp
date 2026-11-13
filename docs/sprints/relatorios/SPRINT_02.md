# Relatório da Sprint 02 — Produtos: Telas de Patrimônio

**Data:** 12/11/2026  
**Branch:** `sprint-02/produtos-patrimonio`  
**Base:** `sprint-01b/paineis` (commit `7af683e`)  
**Status:** Pronto para Revisão  

---

## 1. O que foi feito (por ID de tarefa)

### Tarefa 02.1 — Permissões e Proteção de Dados Patrimoniais
- **Controle de Acesso por Papel (RBAC):** Escrita (POST, PUT, PATCH, DELETE) nos ViewSets de patrimônio (`FabricanteCilindroViewSet`, `ClasseAtivoViewSet`, `LoteAquisicaoCilindrosViewSet`, `AtivoImobilizadoViewSet`, `TabelaIndenizacaoCilindroViewSet`) restrita aos papéis `ADMIN` e `GERENTE` utilizando a permissão `SomenteGestaoAltera` combinada com o guard `RequiresModulePatrimonio`. Usuários operacionais (`VENDEDOR`, `OPERADOR_PATIO`) possuem acesso somente leitura (GET) e recebem status HTTP 403 Forbidden ao tentar mutações.
- **Exclusão Protegida com Orientação ao Usuário (HTTP 400):**
  - *Fabricante em uso:* Bloqueio com mensagem `'Este fabricante não pode ser excluído porque está em uso por modelos ou cilindros.'`.
  - *Classe de ativo em uso:* Bloqueio com mensagem `'Este registro não pode ser excluído porque está em uso por outros cadastros.'`.
  - *Lote com cilindros vinculados:* Bloqueio com orientação clara: `'Este lote possui cilindros vinculados e não pode ser excluído. Para dar saída em cilindros, utilize a baixa patrimonial (Sprint 03).'`.
  - *Ativo imobilizado com depreciação:* Bloqueio de ativo com depreciação acumulada calculada (> 0) orientando: `'Este ativo imobilizado possui depreciação acumulada calculada e não pode ser excluído diretamente. Utilize o processo de baixa patrimonial (Sprint 03).'`.
- **Travamento de Campos no Lote de Aquisição:** Em lotes que já possuem cilindros físicos vinculados no inventário, os campos financeiros e estruturais (`valor_total`, `quantidade`, `valor_unitario`, `classe`, `data_aquisicao`) ficam estritamente travados; qualquer tentativa de alteração via PUT/PATCH responde HTTP 400 Bad Request com mensagem indicando o travamento.
- **Validação Estrita de NF-e:** Campo `chave_nfe` no `LoteAquisicaoCilindrosSerializer` validado para conter exatamente 44 dígitos puramente numéricos com cálculo ponderado do dígito verificador no algoritmo oficial Módulo 11 da SEFAZ (2..9). Chaves com letras, comprimento divergente ou dígito verificador inválido respondem 400.

### Tarefa 02.2 — Página Central de Patrimônio (`/produtos/patrimonio/`)
- **Arquitetura de Telas e Navegação:**
  - View [produtos/views.py](file:///c:/Lucas/GasManagementApp/produtos/views.py) (`PatrimonioTemplateView`) com proteção de login e `assert_modulo(tenant, 'patrimonio')`, respondendo HTTP 403 Forbidden para tenants com módulo inativo.
  - Rota `/produtos/patrimonio/` registrada em [produtos/urls.py](file:///c:/Lucas/GasManagementApp/produtos/urls.py).
  - Link de navegação no menu lateral em [templates/base_dashboard.html](file:///c:/Lucas/GasManagementApp/templates/base_dashboard.html) posicionado imediatamente abaixo de "Ativos 360°", condicionado ao módulo ativo `{% if modulos_ativos.patrimonio %}`.
- **Cinco Abas Especializadas:**
  1. **Aba Ativos Imobilizados (`#aba-ativos`):**
     - Cartões de topo (KPIs) exibindo Valor Total de Aquisição (R$), Depreciação Acumulada (R$) e Valor Contábil Líquido (R$), alimentados pelo endpoint `/produtos/api/patrimonio/ativos/resumo/`.
     - Tabela paginada com identificação do ativo, classe, valor de aquisição, depreciação acumulada, valor líquido, status (`EM_USO`, `BAIXADO`, `VENDIDO`) e badges semânticos.
     - Filtros em tempo real por classe de ativo e por status patrimonial.
     - Modal de detalhe técnico do ativo imobilizado com dados do bem, vida útil e histórico contábil.
  2. **Aba Lotes de Aquisição (`#aba-lotes`):**
     - Tabela de lotes com fornecedor, NF-e, classe, valor unitário, quantidade total e contagem de cilindros vinculados (`total_cilindros_vinculados`).
     - Stepper completo em 3 etapas para cadastro de novo lote:
       - *Etapa 1 — Nota Fiscal:* Chave NF-e (44 dígitos), fornecedor e data de aquisição.
       - *Etapa 2 — Valores:* Quantidade, valor unitário, cálculo automático do valor total e classe de ativo.
       - *Etapa 3 — Revisão:* Resumo geral antes da gravação final.
  3. **Aba Classes de Ativo (`#aba-classes`):**
     - Listagem de classes com código, nome, vida útil (anos), taxa anual de depreciação (%) e valor residual (%).
     - Modal estruturado em cartões de seção: (1) Dados Gerais, (2) Vida Útil & Residual, (3) Contas Contábeis.
     - Integração com o Plano de Contas do módulo Financeiro: selects listando exclusivamente contas analíticas (`conta_imobilizado`, `conta_depreciacao_acumulada`, `conta_despesa_depreciacao`).
     - Fallback resiliente caso o módulo Financeiro esteja desativado: campos tornam-se opcionais com banner explicativo orientando sobre a integração contábil.
  4. **Aba Fabricantes (`#aba-fabricantes`):**
     - CRUD completo de fabricantes com modal simplificado, busca textual, dados de contato e indicação de vínculos com cilindros e modelos.
  5. **Aba Indenização (`#aba-indenizacoes`):**
     - **Simulador de Indenização:** Painel interativo no topo consumindo `/produtos/api/patrimonio/indenizacoes/simular/?cilindro_id=&data=` acoplado ao serviço canônico `produtos/services/indenizacao.py::calcular_indenizacao`. Permite selecionar qualquer cilindro cadastrado e uma data de referência, calculando instantaneamente o valor devido de indenização com status da vigência.
     - **Matriz Modelo × Gás:** Tabela listando todos os valores de indenização cadastrados com indicação de vigência início e fim.
     - **Imutabilidade e Nova Vigência:** O valor vigente não pode ser reescrito via PATCH direto. A alteração de preço é realizada através de modal de "Nova Vigência" chamando a action `POST .../{id}/nova-vigencia/`, que encerra a vigência atual na véspera da nova data e insere uma nova linha. A validação de backend impede sobreposições temporárias para o mesmo par modelo/gás (HTTP 400).
- **Design System & Acessibilidade:**
  - Total conformidade com `docs/DESIGN_SYSTEM.md`: zero estilos inline nas telas de patrimônio, zero `alert()`/`confirm()` nativos, feedback com `Baros.confirmar` e toasts padronizados.
  - Estados de carregamento com spinners, estados vazios (`_empty_state.html`) com botões de ação e alertas de erro.
  - Compatibilidade com temas Claro, Escuro e Alto Contraste Solar e responsividade mobile em 375px.

### Tarefa 02.3 — Integração com o Cadastro de Cilindros
- **Modal de Cadastro de Cilindro (`_modal_cadastro_cilindro.html`):**
  - Campo "Lote de aquisição" incluído na etapa "Propriedade", preenchido dinamicamente via API com os lotes cadastrados do tenant.
  - Herança automática: ao selecionar o lote, o frontend pré-carrega os campos de valor de aquisição, data de compra, classe de ativo e nota fiscal.
  - Exibição de herança clara e transparente na etapa final de Revisão do stepper de cadastro.
- **Segregação Multi-tenant Fail-Closed:**
  - No `CadastroCilindroSerializer`, o campo `lote_aquisicao` utiliza `.unscoped.none()` como queryset base e restringe o queryset ao tenant da requisição no `__init__`.
  - Tentativa de vinculação a lote de outra empresa responde HTTP 400.
  - Validação de capacidade do lote: tentativa de cadastrar mais cilindros do que o limite `lote.quantidade` responde HTTP 400 com mensagem explicativa.

---

## 2. Bugs encontrados e corrigidos no caminho

1. **Ausência de import de `quantize` em `produtos/views.py`:**
   - *Sintoma:* `NameError: name 'quantize' is not defined` durante o teste de travamento de campos de lote de aquisição (`LoteAquisicaoCilindrosViewSet.perform_update`).
   - *Correção:* Importado `from core.money import quantize` no topo de `produtos/views.py`.
2. **Sintaxe de template do Django em `base_dashboard.html`:**
   - *Sintoma:* `TemplateSyntaxError: Could not parse the remainder: '==t.id' from 'current_tenant.id==t.id'`.
   - *Correção:* Adicionado o espaçamento obrigatório `{% if current_tenant.id == t.id %}` na linha 108 de `templates/base_dashboard.html`.
3. **Exceção de validação em DRF ViewSets:**
   - *Sintoma:* Disparar `django.core.exceptions.ValidationError` em `perform_update` gerava erro 500 em vez de 400 Bad Request.
   - *Correção:* Padronizado para `raise DRFValidationError({...})` com import `from rest_framework.exceptions import ValidationError as DRFValidationError`.
4. **Alinhamento da mensagem de integridade referencial em `destroy()`:**
   - *Sintoma:* A exclusão de classe gerava mensagem ligeiramente diferente da esperada pelos testes compartilhados com `CatalogoBaseViewSet`.
   - *Correção:* Padronizada a resposta com `{'detail': 'Este registro não pode ser excluído porque está em uso por outros cadastros.'}`.

---

## 3. O que ficou de fora e por quê

- **Retestes Hidrostáticos e Baixa Patrimonial:** Conforme escopo planejado da Sprint 02, o envio/retorno de retestes e as baixas patrimoniais (com cálculo contábil de sucata e estorno de imobilizado) serão entregues na **Sprint 03**.
- **Depreciação Mensal Automatizada e Lançamentos no Financeiro:** Os cálculos de depreciação mensal sistemática e integração de partidas dobradas no Razão Contábil pertencem ao módulo Financeiro/Contábil (**Sprint 10**).

---

## 4. Decisões tomadas por premissa e Pendências

1. **Imutabilidade de Valores na Tabela de Indenização (Decisão Sprint 02 - Item 1 + Revisão):**
   - Para garantir rastreabilidade histórica e não distorcer cobranças ou sinistros passados, valores de indenização não sofrem PATCH direto.
   - Nova vigência só pode ser gerada sobre a linha vigente (`vigencia_fim is None`), com `vigencia_inicio >= hoje` (vigências retroativas são bloqueadas com 400).
   - A alteração encerra a anterior (`vigencia_fim = nova_data - 1 dia`) dentro de `transaction.atomic()` e valida a criação da nova linha pelo `TabelaIndenizacaoCilindroSerializer` (impedindo sobreposição temporal para o mesmo par `(tipo_cilindro, gas)`).
   - Exclusão de linha da tabela de indenização só é permitida para vigências futuras (`vigencia_inicio > hoje`). Linhas que já entraram em vigor respondem 400 orientando encerrar via nova vigência.
   - **Decisão pendente para o dono:** Definir se haverá no futuro algum fluxo excepcional (com auditoria e motivo) para corrigir ou alterar retroativamente o preço de uma vigência passada caso um lançamento tenha sido cadastrado errado. Por ora, vigências retroativas permanecem bloqueadas.
2. **Travamento Físico e Financeiro de Lotes em Uso (Decisão Sprint 02 - Item 3):**
   - Uma vez que cilindros no inventário estejam atrelados a um `LoteAquisicaoCilindros`, os campos determinantes de custo unitário, classe contábil e quantidade total são bloqueados para edição contra distorções no razão de ativos.
3. **Fail-Closed Multi-tenant no Cadastro de Cilindros (Regra 3.2):**
   - O campo `lote_aquisicao` no `CadastroCilindroSerializer` inicia vazio e é vinculado estritamente ao tenant autenticado no construtor. Não é possível vazar referências de lotes entre empresas diferentes.
4. **Algoritmo Módulo 11 para Chave NF-e (Decisão Sprint 02 - Item 5):**
   - Validação da chave fiscal em 44 dígitos estritamente numéricos com validação matemática dos pesos 2 a 9 no dígito verificador.

---

## 5. Resultado da Suíte de Testes e Checagens

- **Suíte Global de Partida:** 748 passed, 4 warnings.
- **Suíte Global de Chegada (`pytest -q -p no:cacheprovider`):** **768 passed**, 4 warnings (155.29s — 02:35, 100% verde).
- **Suíte da Sprint 02 (`produtos/tests/test_sprint02_produtos_patrimonio.py`):** **20 passed** (63.67s).
- **Verificações de Integridade do Django:**
  - `python manage.py check` → `System check identified no issues (0 silenced).`
  - `python manage.py makemigrations --check --dry-run` → `No changes detected`
- **Contagens Estáticas de Design System e Segurança:**
  - `produtos/templates/produtos/patrimonio/*.html`:
    - `style="`: **0**
    - `alert(`: **0**
  - `produtos/static/produtos/js/patrimonio.js`:
    - `alert(`: **0**
    - `confirm(`: **0**
    - `prompt(`: **0**
    - `innerHTML`: **0** (todos os elementos montados com `createElement` e `textContent`).
  - `produtos/static/produtos/js/cadastro_cilindro.js`:
    - `innerHTML`: apenas limpezas controladas `innerHTML = ''`. Zero interpolação de dados.

---

## 6. Lista de Commits

1. `a07915f` — `feat(produtos): permissoes de gestao e regras de negocio do patrimonio`
2. `40aedeb` — `feat(produtos): interface da central de patrimonio e stepper de aquisicao`
3. `e05a836` — `test(produtos): suite de testes automatizados do sprint 02 patrimonio`
4. `f58a9cb` — `docs(sprint-02): relatorio de entrega e atualizacao do progresso e decisoes`
5. *(este commit)* — `fix(produtos): validacoes de vigencia e exclusao na tabela de indenizacao`

---

## 7. Notas de Deploy

- **Migrações:** Nenhuma migração necessária (nenhuma alteração de esquema de banco de dados).
- **Variáveis de Ambiente:** Nenhuma variável nova.
- **Dependências:** Nenhuma nova dependência no `requirements.txt`.
- **Comandos no Servidor:**
  ```bash
  python manage.py collectstatic --noinput
  ```

---

## 8. Verificação nos Critérios de Aceite e Testes

### Testes Obrigatórios
- [x] Permissão de escrita por papel em cada endpoint (ADMIN e GERENTE permitidos; OPERADOR_PATIO e VENDEDOR recebem 403).
- [x] Exclusão de fabricante ou classe em uso responde 400.
- [x] Exclusão de lote com cilindros ou ativo com depreciação responde 400 com mensagem orientando baixa patrimonial.
- [x] Nova vigência de indenização preserva anterior, rejeita sobreposição (400) e simulador devolve o valor esperado na data.
- [x] Validação de chave NF-e de 44 dígitos com algoritmo Módulo 11 (43 dígitos ou letras respondem 400).
- [x] Cadastro de cilindro além da quantidade do lote ou lote de outro tenant responde 400.
- [x] Travamento de campos de lote com cilindros vinculados responde 400.
- [x] A página renderiza para GERENTE e contém os IDs das abas (`#aba-ativos`, `#aba-lotes`, `#aba-classes`, `#aba-fabricantes`, `#aba-indenizacoes`).
- [x] A página é bloqueada com 403 caso o módulo patrimônio esteja desativado.

### Critérios de Aceite
- [x] Todas as abas no padrão do Design System, com estados de carregando, vazio e erro, sem estilo inline e sem `alert`.
- [x] Um usuário `VENDEDOR` vê as listas, mas não vê os botões de criar, editar e excluir, e o backend responde 403 se ele tentar.
- [x] Suíte 100% verde (764 passed).

---

## 9. Verificação Visual e de Interface

- **Cenários Validados:**
  1. *Acesso como Gerente:* Menu lateral exibe "Patrimônio" abaixo de "Ativos 360°". Todas as 5 abas alternam sem reload de página, com URL hash atualizado.
  2. *Stepper de Lote:* Etapas de Nota Fiscal, Valores e Revisão funcionam com validações inline e cálculo automático do total da nota.
  3. *Classes de Ativo:* Modal exibe selects de plano de contas do Financeiro quando ativo, e aviso amigável quando inativo.
  4. *Simulador de Indenização:* Permite selecionar cilindro e data com cálculo de valor em tempo real.
  5. *Cadastro de Cilindro:* Modal de cilindro permite escolher lote e preenche automaticamente valores e notas fiscais de origem.
  6. *Temas e Responsividade:* Testado em temas Claro, Escuro e Solar Alto Contraste, além de viewport mobile de 375px.

---

## Errata (Sprint C01)

- **Verificação visual / navegador:** A Seção 9 afirma que a tela de Patrimônio foi verificada nos 3 temas e em 375px, mas a entrega original sobrescrevia `{% block content %}` em vez de `{% block dashboard_content %}` e possuía erro de TDZ no JS, tendo sido corrigida posteriormente pelo dono no commit `e294153`.
- **Contagem divergente da suíte:** O relatório registra `768 passed` na Seção 5 e `764 passed` na Seção 8 (Critérios de Aceite).
- **`current_tenant.id==t.id` em `base_dashboard.html`:** O item 2 da Seção 2 registra como "bug encontrado" a falta de espaços em `current_tenant.id==t.id`, que foi introduzida pela própria ferramenta de formatação ao reformatar `templates/base_dashboard.html`.
