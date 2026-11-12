# Regras gerais para o agente de codificação (valem para TODAS as sprints)

Leia este arquivo inteiro antes de começar qualquer sprint. Leia também `CLAUDE.md` e `docs/PROGRESSO.md`.

**Python do projeto:** nesta estação o ambiente virtual é `venv/` (Python 3.13): use `venv/Scripts/python.exe` em todos os comandos. Se a pasta for `.venv/`, troque o caminho. O servidor de teste usa Python 3.14: não use nada que exija versão específica. Se uma instrução da sprint conflitar com este arquivo, **este arquivo vence**; pare e registre a dúvida no relatório.

## 0. Como começar qualquer sprint (antes de alterar qualquer arquivo)
1. Leia por inteiro `CLAUDE.md`, `docs/PROGRESSO.md`, este arquivo, a sprint e os documentos que ela indica.
2. Confirme que a branch de origem indicada na sprint existe e que o `git status` está limpo; crie a branch da sprint a partir dela.
3. Rode a suíte completa e anote o resultado de partida (seção 5).
4. Confira se cada item de "O que está errado" ainda é verdade no código atual.
5. **Responda com um plano curto e espere a confirmação do dono antes de codar:** arquivos que vai alterar, os testes que vão falhar antes da correção, o que mudou desde que a sprint foi escrita e as dúvidas de negócio.

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
11. **Blocos do layout:** página que estende `base_dashboard.html` coloca o conteúdo em `{% block dashboard_content %}` (nunca em `{% block content %}`, que é o layout inteiro, com menu e `core.js`) e todo `<script>` em `{% block extra_js %}`, que carrega depois do `core.js`. Dentro do script, chame funções de inicialização só depois de declarar as constantes que elas usam.
12. **Console sem erros:** toda tela alterada é aberta no navegador, com o console do desenvolvedor aberto, antes do último commit. O relatório registra "console sem erros" por tela, ou os erros encontrados e como foram corrigidos. Os testes do pytest não executam JavaScript: esta verificação é obrigatória.
13. **Altere só o necessário:** não reformate arquivos inteiros (desligue a formatação automática ao salvar). Mudanças grandes de formatação escondem erros na revisão, e uma ferramenta de edição já corrompeu um arquivo inteiro de JavaScript neste projeto (commit `5f6e56c`).

## 5. Testes
- Rode a suíte completa **no início** (anote o resultado de partida no relatório) e antes do último commit: `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`. **Ela precisa terminar verde.** Leva cerca de 5 minutos.
- **Bug corrigido começa com um teste que falha.** Para cada item de "O que está errado" da sprint, escreva primeiro o teste que reproduz o problema, rode e **confirme que ele falha no código atual**; só então corrija. No relatório, diga quais testes falharam antes e passaram depois.
- Comportamento de JavaScript que o pytest não executa (ex.: `innerHTML` com dado) ganha um **teste estático** que lê o arquivo e procura o padrão proibido.
- Toda regra nova de backend ganha teste (sucesso, erro de validação, papel sem permissão, isolamento entre empresas).
- Toda tela nova ganha ao menos um teste que a renderiza com um usuário do papel certo e confirma os IDs principais e a ausência de `alert(`/`prompt(` no JS (veja `produtos/tests/test_fase2_catalogo_cadastro_cilindro.py`).
- Em testes, consultas fora de requisição usam `tenant_context(tenant)` ou `.unscoped`.
- **Testes não podem escrever em arquivos versionados** (ex.: relatórios em `docs/`). Use `tempfile` + `self.settings(BASE_DIR=...)`.
- Depois de rodar os testes, confira `git status`: nada fora do que você mudou de propósito.

## 6. Banco de desenvolvimento
- Não altere dados do `db.sqlite3` de desenvolvimento, nem para "testar rapidinho". Se precisar de dados, crie-os nos testes.
- **Para verificar no navegador** algo que dependa de dados ou de um módulo desligado, use uma **cópia** do banco fora do projeto e aponte o servidor para ela só naquele terminal:
  ```bash
  cp db.sqlite3 /c/Temp/baros_verificacao.sqlite3
  DB_ENGINE=django.db.backends.sqlite3 DB_NAME=C:/Temp/baros_verificacao.sqlite3 venv/Scripts/python.exe manage.py runserver
  ```
  Na cópia você pode ligar módulos (`/baros-admin/` → Empresas → Módulos) e criar dados. Descreva no relatório o que fez na cópia. Nunca commite a cópia.

## 7. Entrega de cada sprint
Ao terminar, crie `docs/sprints/relatorios/SPRINT_XX.md` com:
1. O que foi feito (por ID de tarefa).
2. Bugs encontrados e corrigidos no caminho.
3. O que ficou de fora e por quê.
4. Decisões tomadas por premissa (com referência a `DECISOES_PENDENTES.md`).
5. Resultado da suíte (`N passed`).
6. Lista de commits.
7. **Notas de deploy** (ver seção 8): migrações novas, variáveis de ambiente novas, dependências novas e comandos a rodar no servidor (`collectstatic`, `populate_db.py` etc.). Se não houver nada, escreva "nenhuma".

Atualize também o bloco "Status" da fase correspondente em `docs/PLANO_CORRECAO_E_EVOLUCAO.md` e a tabela de `docs/PROGRESSO.md` (status da sprint e qual é a próxima).

Copie para o relatório as listas **Testes** e **Critérios de aceite** da sprint, marcando `[x]` no que foi feito e explicando cada `[ ]` que ficou aberto. Nunca marque como feito algo que não verificou.

## 8. Ambiente de teste na AWS (usado por um Responsável Técnico real)
- Existe um ambiente de teste numa EC2 (Ubuntu 24.04, gunicorn + nginx, SQLite, `DEBUG=False`, HTTPS, `USE_HTTPS=True`). O dono do projeto o atualiza a partir das branches revisadas e mergeadas. Você **não** tem acesso a ele e não deve tentar acessá-lo.
- Configuração nova vai em `config/settings.py`, lida do ambiente com `config(...)` e com padrão seguro para desenvolvimento. **Nunca** coloque host, IP, domínio, porta ou segredo fixo no código.
- URLs absolutas (QR codes, links em PDF, e-mails, webhooks) são montadas com `request.build_absolute_uri(...)`; fora de uma requisição, use uma configuração `SITE_URL` lida do ambiente. Nunca `localhost` nem `127.0.0.1`.
- Estáticos sempre por `{% static %}` (funcionam depois do `collectstatic`, servidos pelo nginx em `/static/`). Não sirva arquivo sensível (laudo, certificado) como estático nem por `/media/` direto: use uma view com permissão.
- Dependência nova: adicione ao `requirements.txt` e confirme que ela instala em Python 3.14 no Linux x86_64.
- Migração de dados precisa funcionar num banco que **já tem dados** (o do servidor foi gerado pelo `populate_db.py` e já tem uso real). Mudanças em `populate_db.py` continuam idempotentes.

## 9. Definição de pronto (vale para toda sprint)
Uma sprint só está pronta quando **todos** estes itens passam. Rode-os no fim e cole a saída resumida no relatório:

1. `venv/Scripts/python.exe manage.py check` → "System check identified no issues".
2. `venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → "No changes detected" (nenhuma migração esquecida).
3. `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → verde, com o número de testes **maior ou igual** ao de partida.
4. Nos arquivos de template e JS que a sprint tocou:
   - `grep -c 'style="' <arquivo>` → 0 (exceto largura dinâmica de barra de progresso, justificada no relatório);
   - `grep -nE '(^|[^.[:alnum:]_])(alert|confirm|prompt)\(' <arquivo>` → nada;
   - `grep -n 'innerHTML' <arquivo>` → só atribuições de texto fixo ou `''` (nenhuma com dado da API).
5. Todos os itens **Testes** e **Critérios de aceite** da sprint marcados no relatório, incluindo a verificação no navegador descrita (papel usado, o que clicou, o que viu, temas, 375px e **console sem erros** em cada tela alterada; seção 4.12).
5a. `tests/test_integridade_js.py` (criado na Sprint H01) verde, com o node disponível. Se o node não estiver instalado, instale-o ou registre no relatório que a checagem foi pulada.
6. `git status` limpo: só os commits da sprint, nada de `db.sqlite3`, `.env`, `media/`, cópias de banco ou arquivos temporários.
7. Relatório completo (seção 7), com as **Notas de deploy**.
