"""
Testes estáticos da Sprint U01 — Interface: largura única, abas, rolagem e textos.
"""
from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parent.parent

IGNORED_DIRS = {"venv", ".venv", "node_modules", ".git", "__pycache__", "staticfiles"}

DEV_LABELS_RE = re.compile(r"\((Sprint\b|D7\)|D8\)|D9\))", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
DJANGO_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF]"
)

# Telas com barra de abas principal no escopo da U01
TELAS_COM_ABAS = [
    "clientes/templates/clientes/index.html",
    "vendas/templates/vendas/index.html",
    "logistica/templates/logistica/index.html",
    "produtos/templates/produtos/patrimonio/index.html",
    "produtos/templates/produtos/recall_anvisa.html",
    "templates/core/integracoes.html",
    "templates/financeiro/dashboard.html",
]

# Todas as 12 telas no escopo da U01
TELAS_ESPECIFICADAS = [
    "core/templates/core/home.html",
    "clientes/templates/clientes/index.html",
    "vendas/templates/vendas/index.html",
    "logistica/templates/logistica/index.html",
    "produtos/templates/produtos/index.html",
    "produtos/templates/produtos/patrimonio/index.html",
    "produtos/templates/produtos/recall_anvisa.html",
    "templates/core/integracoes.html",
    "templates/core/perfil_regulatorio.html",
    "accounts/templates/accounts/index.html",
    "templates/financeiro/dashboard.html",
    "templates/fiscal/index.html",
]

CSS_PAGINAS = [
    "core/static/core/css/dashboard.css",
    "core/static/core/css/integracoes.css",
    "core/static/core/css/perfil_regulatorio.css",
    "clientes/static/clientes/css/index.css",
    "vendas/static/vendas/css/index.css",
    "logistica/static/logistica/css/index.css",
    "produtos/static/produtos/css/index.css",
    "produtos/static/produtos/css/recall.css",
    "accounts/static/accounts/css/index.css",
]

# Seletores de página que não podem definir max-width próprio fora de .ds-page
PAGE_CONTAINER_MAX_WIDTH_RE = re.compile(
    r"(?:^|\n)\s*\.(?:integracoes-container|perfil-regulatorio-container|fin-container|fiscal-container|page-container|ds-container)[^{]*\{[^}]*max-width\s*:",
    re.DOTALL,
)


def _limpar_comentarios(html: str) -> str:
    sem_django = DJANGO_COMMENT_RE.sub("", html)
    return HTML_COMMENT_RE.sub("", sem_django)


def test_sem_rotulos_internos_em_texto_visivel_templates():
    """Templates não podem exibir (Sprint ...), (D7), (D8) ou (D9) ao usuário."""
    ocorrencias = []
    for path in sorted(BASE_DIR.rglob("*.html")):
        if set(path.parts) & IGNORED_DIRS:
            continue
        visivel = _limpar_comentarios(path.read_text(encoding="utf-8", errors="replace"))
        for idx, linha in enumerate(visivel.splitlines(), start=1):
            if DEV_LABELS_RE.search(linha):
                rel = path.relative_to(BASE_DIR).as_posix()
                ocorrencias.append(f"{rel}:{idx}: {linha.strip()}")

    assert not ocorrencias, (
        "Rótulos internos de desenvolvimento visíveis em templates:\n"
        + "\n".join(ocorrencias)
    )


def test_telas_com_abas_usam_tabs_nav_sem_emoji():
    """Telas com abas usam .tabs-nav, role='tablist'/'tab' e sem emojis nos botões."""
    erros = []
    for rel in TELAS_COM_ABAS:
        txt = (BASE_DIR / rel).read_text(encoding="utf-8", errors="replace")
        if "tabs-nav" not in txt:
            erros.append(f"{rel}: ausente classe .tabs-nav")
            continue
        if 'role="tablist"' not in txt:
            erros.append(f"{rel}: ausente role=\"tablist\"")
        if 'role="tab"' not in txt:
            erros.append(f"{rel}: ausente role=\"tab\"")

        # Extrai o primeiro bloco <nav ...tabs-nav...>...</nav> ou <div ...tabs-nav...>
        bloco_match = re.search(
            r'<(?:nav|div)[^>]*class="[^"]*tabs-nav[^"]*"[^>]*>(.*?)</(?:nav|div)>',
            txt,
            re.DOTALL,
        )
        if bloco_match:
            botoes = re.findall(
                r"<button[^>]*>(.*?)</button>", bloco_match.group(1), re.DOTALL
            )
            for b in botoes:
                texto_btn = re.sub(r"<[^>]+>", "", b).strip()
                if EMOJI_RE.search(texto_btn):
                    erros.append(f"{rel}: emoji em aba ({texto_btn})")

    assert not erros, "Inconformidades nas abas:\n" + "\n".join(erros)


def test_telas_usam_ds_page_e_sem_max_width_de_pagina():
    """As 12 telas usam .ds-page e seus CSS não impõem max-width próprio de página."""
    sem_ds_page = []
    for rel in TELAS_ESPECIFICADAS:
        txt = (BASE_DIR / rel).read_text(encoding="utf-8", errors="replace")
        if "ds-page" not in txt:
            sem_ds_page.append(rel)

    assert not sem_ds_page, (
        "Telas sem container .ds-page: " + ", ".join(sem_ds_page)
    )

    erros_css = []
    for rel in CSS_PAGINAS:
        css_path = BASE_DIR / rel
        if not css_path.exists():
            continue
        css_txt = css_path.read_text(encoding="utf-8", errors="replace")
        if PAGE_CONTAINER_MAX_WIDTH_RE.search(css_txt):
            erros_css.append(rel)

    assert not erros_css, (
        "CSS com max-width próprio de página fora de .ds-page: " + ", ".join(erros_css)
    )

