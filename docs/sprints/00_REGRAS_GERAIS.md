# Regras gerais para o agente de codificação (valem para TODAS as sprints)

Leia este arquivo inteiro antes de começar qualquer sprint. Se uma instrução da sprint conflitar com este arquivo, **este arquivo vence**; pare e registre a dúvida no relatório.

## 1. Contexto do projeto
- **Baros**: SaaS B2B multi-tenant (Django 6 + DRF) para envase e distribuição de gases industriais e medicinais.
- Leitura obrigatória antes de codar:
  - `docs/GUIA_MODULOS_BAROS.md`: o que cada módulo faz e seus fluxos.
  - `docs/DESIGN_SYSTEM.md`: regras de interface (layout, stepper, estados, temas, checklist).
  - `docs/PLANO_CORRECAO_E_EVOLUCAO.md`: o plano completo, com o status do que já foi feito.
- **Referências do padrão novo, já prontas:** tela de Clientes (`clientes/templates/clientes/index.html`), aba Catálogo e cadastro de cilindro em Produtos (`produtos/templates/produtos/index/_aba_catalogo.html`, `_modal_cadastro_cilindro.html`, `produtos/static/produtos/js/catalogo.js`, `cadastro_cilindro.js`), Recall (`produtos/templates/produtos/recall_anvisa.html`, `produtos/static/produtos/js/recall.js`) e o backoffice (`templates/baros_admin/`). **Copie o estilo desses arquivos.**

## 2. Git
- Trabalhe em uma branch por sprint: `sprint-XX/<nome-curto>`, criada a partir da branch da sprint anterior. Se for a primeira, crie a partir de `fase-2/produtos`.
- Um commit por tarefa ou grupo pequeno, com mensagem em português no formato `feat(app): ...`, `fix(app): ...`, `refactor(app): ...`, `test(app): ...`, `docs: ...`.
- **Nunca** faça push, merge, rebase de branches existentes, `--force` ou `--no-verify`. O dono do projeto faz isso.
- Nunca versione `db.sqlite3`, `.env`, `media/`, `.coverage`.

## 3. Backend: regras que não podem ser quebradas
1. **Multi-tenant fail-closed.** Todo model novo herda de `TenantAwareModel` (`core/tenancy.py`). ViewSets herdam `TenantViewSetMixin` (`core/mixins.py`). Há um teste (`core/tests/test_cross_tenant_isolation.py`) que exige isso de **todo** ViewSet registrado em router. Objeto de outra empresa responde **404**.
2. **Nada de consulta com escopo de tenant no import do módulo.** Ex.: `queryset=Model.objects.all()` no corpo de uma classe de serializer quebra o projeto inteiro (`TenantNotSet`). Use `Model.unscoped.none()` no campo e restrinja no `__init__` com o tenant da requisição (veja `CadastroCilindroSerializer` em `produtos/serializers.py`).
3. **Rotas públicas** (sem login) não têm tenant: use `.unscoped` filtrando pelo token/UUID e pelo tenant do próprio objeto (veja `logistica/services/rastreio_publico_service.py`).
4. **Ledgers são imutáveis** (`MovimentacaoCilindro`, `LancamentoContabil`/`PartidaContabil`): nunca editar nem apagar; corrigir só por **estorno**.
5. **Dinheiro e quantidades em `Decimal`**, nunca `float` (há teste `tests/test_no_float_money.py`).
6. **Regras de negócio em services** (`<app>/services/...`), não em views. Views só validam entrada, chamam o service e montam a resposta.
7. **Máquinas de estado**: toda mudança de status passa por uma função de transição que valida a origem, o destino e o papel do usuário (exemplos: `vendas/services/status.py`, `core/services/assinatura.py`, `registrar_andamento_item_recall` em `produtos/services/ciclo_cilindro.py`). **Campos de status nunca podem ser gravados por PATCH**: marque-os `read_only` no serializer.
8. **Permissões no backend**, não só escondendo botões. Papel vem de `Membership.papel` (`ADMIN`, `GERENTE`, `OPERADOR_PATIO`, `MOTORISTA`, `VENDEDOR`, `RESPONSAVEL_TECNICO`). Use `core/permissions.py` (`IsTenantMember`, `IsTenantAdminOrGerente`, `RequiresModule...`).
9. **Erros da API** no formato DRF: `{"campo": ["mensagem"]}` para erro de campo, ou `{"detail": "..."}` / `{"error": "..."}` para erro geral. Nunca `except Exception: pass`.
10. **`ATOMIC_REQUESTS=True`**: efeitos "depois do commit" (webhook, e-mail) usam `transaction.on_commit`; não use atalhos como `'test' in sys.argv`.
11. **Migrações**: crie com `makemigrations <app> -n nome_descritivo`; nunca edite migração já commitada (exceto para corrigir efeito colateral óbvio, registrando no relatório).
12. **Não invente regra fiscal, contábil ou sanitária.** Se faltar uma decisão, use a premissa de `docs/DECISOES_PENDENTES.md`; se não houver, pare, registre a dúvida no relatório e implemente o resto.

## 4. Frontend: regras do Design System
1. Use os componentes de `core/static/core/css/components.css` e as funções `window.Baros` de `core/static/core/js/core.js`:
   - `Baros.api(url, {method, body})`: faz CSRF, JWT e `X-Tenant-ID` e lança `Baros.ApiError` com `.mensagem` e `.campos`.
   - `Baros.confirmar({titulo, texto, botao, perigo, motivo})` (com `motivo: 10` exige justificativa), `Baros.sucesso/erro/aviso`, `Baros.carregando(botao, texto)`.
   - `Baros.Stepper(seletor, {validar, aoMudar})`, `Baros.validarCampos(seletor)`, `Baros.mostrarErrosApi(form, erro)`.
   - Parciais: `templates/components/_stepper.html`, `_metric_card.html`, `_empty_state.html`.
2. **Proibido**: `alert()`, `confirm()`, `prompt()`; estilos inline novos (`style="..."`), exceto valor dinâmico de largura de barra de progresso; cores fixas em CSS de módulo (use `var(--color-...)` e `var(--status-...)`); CDN externo (bibliotecas ficam em `static/vendor/`).
3. **Segurança**: dados do cadastro (nomes, endereços, observações) **nunca** vão para `innerHTML` ou template string inserida como HTML. Monte o DOM com `document.createElement` e `textContent` (veja `recall.js`). No template Django, use o autoescape (não use `|safe` em dado de usuário).
4. **Números em campos `<input type="number">`**: o projeto usa localização pt-BR; renderize com `{% load l10n %}` e `|unlocalize`, senão `499,00` deixa o campo vazio.
5. **Exibição** de dinheiro e números em pt-BR: `Baros.moeda(v)`, `Number(v).toLocaleString('pt-BR', ...)`.
6. O atributo `hidden` já vence o `display` das classes (`[hidden]{display:none!important}`); para mostrar/ocultar blocos use `hidden` ou a classe `.ds-hidden`.
7. Cadastros com mais de ~8 campos usam **stepper com etapa final de Revisão**. Edições curtas usam modal com `.modal-section-card`. Ações destrutivas sempre passam por `Baros.confirmar` (com motivo quando for regulatório).
8. Template com mais de ~800 linhas deve ser dividido em parciais (`templates/<app>/<tela>/_parte.html`) ou em páginas separadas.
9. Ao alterar um arquivo estático, atualize o `?v=AAAAMMDD_xx` dele no template que o carrega (cache do navegador).
10. Toda tela precisa funcionar nos temas **claro, escuro e alto contraste solar** e com **375px** de largura.

## 5. Testes
- Rode a suíte completa antes do último commit da sprint: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`. **Ela precisa terminar verde.** Ela leva cerca de 5 minutos.
- Toda regra nova de backend ganha teste (sucesso, erro de validação, papel sem permissão, isolamento entre empresas).
- Toda tela nova ganha ao menos um teste que a renderiza com um usuário do papel certo e confirma os IDs principais e a ausência de `alert(`/`prompt(` no JS (veja `produtos/tests/test_fase2_catalogo_cadastro_cilindro.py`).
- Em testes, consultas fora de requisição usam `tenant_context(tenant)` ou `.unscoped`.
- **Testes não podem escrever em arquivos versionados** (ex.: relatórios em `docs/`). Use `tempfile` + `self.settings(BASE_DIR=...)`.
- Depois de rodar os testes, confira `git status`: nada fora do que você mudou de propósito.

## 6. Banco de desenvolvimento
- Não altere dados do `db.sqlite3` de desenvolvimento, nem para "testar rapidinho". Se precisar de dados, crie-os nos testes. Se precisar verificar no navegador algo que dependa de um módulo desligado, **registre no relatório** em vez de ligar o módulo.

## 7. Entrega de cada sprint
Ao terminar, crie `docs/sprints/relatorios/SPRINT_XX.md` com:
1. O que foi feito (por ID de tarefa).
2. Bugs encontrados e corrigidos no caminho.
3. O que ficou de fora e por quê.
4. Decisões tomadas por premissa (com referência a `DECISOES_PENDENTES.md`).
5. Resultado da suíte (`N passed`).
6. Lista de commits.

Atualize também o bloco "Status" da fase correspondente em `docs/PLANO_CORRECAO_E_EVOLUCAO.md`.
