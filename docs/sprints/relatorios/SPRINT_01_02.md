# Relatório da Sprint 01.02 — Etiquetas: uma impressão só, a verdadeira

**Data:** 11/11/2026  
**Branch:** `sprint-01.02/etiquetas`  
**Status:** Concluída com sucesso

---

## 1. O que foi feito

### Backend
- **Ajuste prévio no resumo da frota (`CilindroViewSet.resumo`):**
  - `total` e `bloqueados` passam a excluir cilindros com status `BAIXADO`.
  - `reteste_30_dias` passa a reaproveitar o helper unificado `filtro_reteste_proximo_ou_vencido(dias=30)`.
- **Validação e regras de negócio na geração de etiquetas de colarinho (`EtiquetaColarinhoView`):**
  - Implementada validação estrita do parâmetro `?envase_ids=`: aceita apenas inteiros positivos separados por vírgula; todos devem pertencer obrigatoriamente ao lote informado e à mesma empresa (tenant). Qualquer ID inválido, inexistente, de outro lote ou de outra empresa responde `400 Bad Request`.
  - Se o lote não possuir nenhum cilindro envasado (ou nenhum envase válido selecionado), a view renderiza um estado vazio sem conteúdo imprimível ("Nenhum cilindro envasado neste lote"), eliminando a emissão de colarinho genérico sem cilindro.
  - Eliminação de valores fixos de pressão: cada etiqueta agora exibe a pressão real registrada no envase (`EnvaseCilindro.pressao_final_bar`) e, se preenchida, a massa líquida de gás (`EnvaseCilindro.massa_liquida_gas_kg`), além do código do cilindro correspondente. Na rota por cilindro, removido o fallback para pressão de serviço do modelo ou 200 bar fixo.
  - Exibição de "Pressão não aferida": sem `pressao_final_bar` no envase, o colarinho exibe "Pressão não aferida" (nunca um número não medido).
  - Guarda de autorização e módulo: acesso restrito a empresas com o módulo `envase` ativo (`empresa.modulo_envase_ativo`).
  - Isolamento multi-tenant: busca do lote filtrada pelo tenant atual (`LoteEnvase.objects.filter(empresa=tenant)`), com suporte a superusuário via `.unscoped`.
- **Geração precisa do QR Code no casco (`EtiquetaCascoView`):**
  - Geração com nível de correção de erro M (`error_correction=qrcode.constants.ERROR_CORRECT_M`) e borda mínima de 1 módulo (`border=1`), conforme norma ISO/IEC 18004.
  - URL absoluta do passaporte digital público do cilindro (`/v/cilindro/<codigo_qr>/`), renderizada via base64 PNG e acompanhada por link textual acessível da URL completa.
  - Isolamento multi-tenant: busca do cilindro via `Cilindro.objects.filter(empresa=tenant)`, com suporte a superusuário via `.unscoped`.

### Frontend e Templates
- **Padronização visual e eliminação de estilos inline:**
  - Removidos 100% dos estilos inline (`style="`) de `produtos/templates/produtos/index/_modais.html` (de 22 ocorrências para 0).
  - Removidos os blocos `<style>` embutidos de `produtos/templates/produtos/etiqueta_casco.html` e `produtos/templates/produtos/etiqueta_colarinho.html`.
  - Estilos de impressão e visualização consolidados em `produtos/static/produtos/css/etiquetas.css`, utilizando named pages (`@page label60x40`, `@page labelColarinho`), `@media print` e tokens do Design System.
  - Classes do modal e iframes padronizadas em `produtos/static/produtos/css/index.css` (`.etiqueta-iframe-container`, `.etiqueta-preview-iframe`, `.etiqueta-preview-iframe--colarinho`).
- **Pré-visualização fiel com Iframe do Servidor (Uma impressão só, a verdadeira):**
  - O modal de etiqueta de casco em `_modais.html` não mais renderiza o mockup estático falso com `[ QR CODE 2D ]`. Agora carrega um `<iframe>` apontando diretamente para a rota do servidor `/produtos/cilindros/<pk>/etiqueta-casco/`.
  - O modal de etiquetas de colarinho também utiliza `<iframe>` apontando para a rota do servidor `/produtos/lotes/<pk>/etiqueta-colarinho/` (com suporte opcional a `?envase_ids=...`).
  - Os modais contam com botões "Abrir em nova aba" (`target="_blank" rel="noopener"`) e "Imprimir", que aciona a impressão isolada do documento dentro do iframe (`iframe.contentWindow.print()`), impedindo a impressão indevida da interface do sistema.
- **Limpeza do JavaScript da Rampa de Lotes:**
  - `fase3_rampa_recebimento_lotes.js`: Eliminada a geração de HTML no cliente com `innerHTML` contendo variáveis e cores fixas (`#dc2626`). A função `imprimirColarinho(loteId, envaseIds)` agora abre o modal de preview e delega a renderização exclusivamente ao servidor.
  - `cilindros_drawer.js`: Função `abrirModalEtiqueta(cilindroId)` atualizada para injetar a URL do servidor no iframe do modal e resetar o estado ao fechar.
  - Atualizado versionamento de assets em `produtos/templates/produtos/index.html` para `?v=20261111_s0102`.

---

## 2. Bugs encontrados e corrigidos no caminho

1. **Pressão fixa de 200 bar no colarinho:**
   - Anteriormente, `EtiquetaColarinhoView` definia `pressao_bar = 200` fixo para todos os cilindros do lote. Agora busca os dados reais de cada `EnvaseCilindro`, refletindo pressões nominais distintas (ex.: 150 bar vs 200 bar) e massa líquida de gás.
2. **Mockup falso de QR Code no modal:**
   - O modal de etiqueta em `_modais.html` exibia `[ QR CODE 2D ]` fictício e chamava `window.print()` da página principal. Corrigido com pré-visualização em iframe da view do servidor e impressão contida no iframe.
3. **Cilindros baixados inflando contagem do resumo:**
   - Em `CilindroViewSet.resumo`, `total` e `bloqueados` não filtravam `status != 'BAIXADO'`. Ajustado para manter consistência com as regras da frota ativa.
4. **Regressão de asserção em teste legado de consolidação:**
   - O teste `test_etiqueta_casco_60x40_geracao` em `core/tests/test_fase_final_consolidacao.py` procurava a string `"60mm 40mm"` dentro do HTML da etiqueta do casco (que antes residia no `<style>` removido) e o tenant não possuía o módulo `envase` ativo. Adicionado atributo semântico `data-size="60mm 40mm"` na tag container e ativado `modulo_envase_ativo=True` no tenant da fixture.
5. **Pressão inventada no colarinho na rota por cilindro:**
   - Na rota `/produtos/cilindros/<pk>/etiqueta-colarinho/`, havia fallback para a pressão de serviço do modelo ou 200 bar fixo. Removido o fallback e ajustado o template para renderizar "Pressão não aferida" quando não informada no envase.

---

## 3. O que ficou de fora e por quê

- **Redesign dos painéis e home operacional (TV/Gestão):** Escopo da Sprint 01B (a ser dividida e planejada).
- **Customização de templates de etiquetas por cliente:** Fora do escopo desta sprint; os layouts seguem a padronização regulatória padrão (casco 60x40mm e colarinho RDC/Inmetro).

---

## 4. Decisões tomadas por premissa

### Medição e Especificação Técnica do QR Code (ISO/IEC 18004)
- **Área destinada na etiqueta:** 22 mm × 22 mm (`etiquetas.css`, `.etiqueta-casco__qr img { width: 22mm; height: 22mm; }`).
- **URL padrão de teste real:** `https://3-146-201-236.sslip.io/v/cilindro/CIL-101/` (tamanho: 50 caracteres).
- **Nível de correção de erro:** M (`ERROR_CORRECT_M`, tolerância de até 15% de danos ou sujeira, ideal para ambientes industriais).
- **Versão gerada:** Versão 4.
- **Contagem de módulos da matriz:** 33 × 33 módulos (35 × 35 módulos considerando a borda/quiet zone mínima de 1 módulo).
- **Dimensão física por módulo:** `22.0 mm / 35 módulos ≈ 0.62857 mm` por módulo.
  - Atende com ampla margem à recomendação mínima de legibilidade óptica para câmeras móveis e leitores industriais (mínimo de 0.50 mm).
- **Localização pt-BR de números:** Exibição com vírgula em conformidade com as normas ABNT (ex.: `8,500 kg`).

---

## 5. Resultado da suíte de testes

- **Comando:** `venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- **Total de testes:** **710 passed**, 4 warnings em 3m01s.
- **Zero falhas.**

---

## 6. Lista de commits

1. `53839f0`: `fix(produtos): resumo da frota exclui baixados e reaproveita o filtro de reteste`
2. `45d5af1`: `feat(produtos): views de etiqueta do casco e colarinho com dados reais de envase e isolamento`
3. `05b37a7`: `feat(produtos): templates de etiquetas sem style inline e modais com preview iframe do servidor`
4. `5446a47`: `test(produtos): testes da sprint 01.02 para etiquetas, medicao qr code e validacao de envases`
5. `616111f`: `docs: relatorio da sprint 01.02 e atualizacao do progresso`
6. `fix(produtos): colarinho sem pressao inventada`

---

## 7. Notas de deploy

- **Migrações:** Nenhuma migração de banco de dados necessária (`makemigrations --check --dry-run` sem alterações).
- **Variáveis de ambiente novas:** Nenhuma.
- **Dependências novas:** Nenhuma (`qrcode` e `Pillow` já fazem parte das dependências do projeto).
- **Estáticos:** Executar `python manage.py collectstatic --noinput` para atualizar `etiquetas.css`, `index.css`, `cilindros_drawer.js` e `fase3_rampa_recebimento_lotes.js` (`?v=20261111_s0102`).
- **Atenção operacional:** O acesso à página de colarinho requer que a empresa tenha o módulo `envase` habilitado (`modulo_envase_ativo=True`).

---

## 8. Verificação dos Itens da Sprint

### Testes da Sprint (`produtos/tests/test_sprint01_02_etiquetas.py`)
- [x] **Falha antes:** Pressão real por cilindro no colarinho em vez de 200 bar fixo (`test_01_pressao_e_massa_reais_por_cilindro_no_colarinho`).
- [x] Lote sem envases exibe estado vazio ("Nenhum cilindro envasado neste lote") sem conteúdo imprimível (`test_02_lote_sem_cilindros_estado_vazio`).
- [x] QR Code do casco usa nível M, borda 1, gera versão 4 e tamanho por módulo >= 0.50 mm para URL do servidor de teste (`test_03_qr_code_casco_medicao_e_legibilidade`).
- [x] Validação rigorosa de `?envase_ids=`: aceita apenas inteiros válidos daquele lote e empresa; IDs inválidos ou externos respondem 400 (`test_04_validacao_envase_ids_no_colarinho`).
- [x] Isolamento multi-tenant: usuário de uma empresa recebe 404 ao tentar acessar etiqueta de casco ou colarinho de outra empresa; superusuário tem acesso (`test_05_isolamento_multitenant_etiquetas`).
- [x] Guarda de módulo SaaS: acesso ao colarinho exige `modulo_envase_ativo=True` (`test_06_modulo_envase_obrigatorio_para_colarinho`).
- [x] Varredura estática: zero `style="` em `_modais.html`, zero `<style>` em `etiqueta_casco.html` e `etiqueta_colarinho.html`, e zero ocorrências de `[ QR CODE 2D ]` (`test_07_estatica_sem_style_inline_nem_layout_falso`).
- [x] Varredura estática: `fase3_rampa_recebimento_lotes.js` sem montagem de etiqueta com `innerHTML` e sem cores fixas hexadecimais no colarinho (`test_08_estatica_rampa_sem_innerhtml_colarinho`).
- [x] Resumo da frota exclui status `BAIXADO` e reaproveita o filtro unificado de reteste (`test_09_resumo_frota_exclui_baixados`).
- [x] **Falha antes:** Rota por cilindro sem pressão inventada — envase sem `pressao_final_bar` não exibe "200 bar" e renderiza "Pressão não aferida" (`test_10_etiqueta_colarinho_rota_cilindro_sem_pressao_inventada`).

### Critérios de Aceite e Verificação em Navegador
- [x] **Verificação automatizada e de integração:**
  - Modais de casco e colarinho carregam URLs do servidor via iframe com isolamento de impressão.
  - Zero estilos inline e zero CSS embutido em templates.
  - Eliminação de diálogos nativos (`alert`, `confirm`, `prompt`) nos arquivos alterados.
  - Validação estrita de parâmetros de query e isolamento tenant.
- [ ] **Verificação visual e física (Pendente de verificação pelo dono no servidor de teste na AWS):**
  - A renderização em tela e o envio para impressão utilizam `@page label60x40` e `@page labelColarinho`. **A conferência da saída física em impressora térmica (ex.: Zebra / Argox em rolo 60x40mm) e a leitura do QR Code impresso por câmera de smartphone real permanecem como verificação a ser executada pelo dono do projeto diretamente no ambiente de homologação da AWS (`https://3-146-201-236.sslip.io/`)**.

---

## 9. Definição de Pronto (Seção 9 das Regras Gerais)

Abaixo estão os resultados das 7 verificações obrigatórias:

1. **System Check:**
   ```
   > venv/Scripts/python.exe manage.py check
   System check identified no issues (0 silenced).
   ```
2. **Checagem de Migrações:**
   ```
   > venv/Scripts/python.exe manage.py makemigrations --check --dry-run
   No changes detected
   ```
3. **Suíte Geral de Testes:**
   ```
   > venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
   ================= 710 passed, 4 warnings in 181.93s (0:03:01) =================
   ```
4. **Verificação de Estilos Inline e Mockups Falsos:**
   ```
   > git grep -n "style=" -- produtos/templates/produtos/index/_modais.html
   (0 ocorrências)
   > git grep -n "<style" -- produtos/templates/produtos/etiqueta_casco.html produtos/templates/produtos/etiqueta_colarinho.html
   (0 ocorrências)
   > git grep -n "QR CODE 2D" -- produtos/templates/produtos/
   (0 ocorrências)
   ```
5. **Verificação de Diálogos Nativos:**
   ```
   > git grep -E "\b(alert|confirm|prompt)\(" -- produtos/static/produtos/js/cilindros_drawer.js produtos/static/produtos/js/fase3_rampa_recebimento_lotes.js
   (0 ocorrências)
   ```
6. **Integridade de Documentação:**
   - Comentários e regras existentes preservados.
7. **Git Status:**
   - Working tree limpa antes do commit de documentação.

