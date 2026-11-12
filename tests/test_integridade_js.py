"""
Verificação estática de integridade JavaScript e estrutura de layout.

Garante que:
1. Todos os arquivos `.js` de `*/static/*/js/` (exceto `static/vendor/`) e todos os
   blocos `<script>` inline em templates `.html` passam no `node --check` (quando
   `node` está disponível no PATH).
2. Nenhum template que estende `base_dashboard.html` sobrescreve `{% block content %}`
   ou declara `<script>` fora de `{% block extra_js %}`.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent

IGNORED_DIRS = {"venv", ".venv", "node_modules", ".git", "__pycache__", "staticfiles"}

SCRIPT_TAG_RE = re.compile(
    r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
SRC_ATTR_RE = re.compile(r"\bsrc\s*=", re.IGNORECASE)
DJANGO_VAR_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
DJANGO_TAG_RE = re.compile(r"\{%.*?%\}", re.DOTALL)
DJANGO_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)

EXTENDS_DASHBOARD_RE = re.compile(
    r"""\{%\s*extends\s+['"]base_dashboard\.html['"]\s*%\}"""
)
BLOCK_CONTENT_RE = re.compile(r"\{%\s*block\s+content\s*%\}")
BLOCK_EXTRA_JS_RE = re.compile(r"\{%\s*block\s+extra_js\s*%\}")


def _is_ignored(path: Path) -> bool:
    parts = set(path.parts)
    if parts & IGNORED_DIRS:
        return True
    if "static" in path.parts and "vendor" in path.parts:
        return True
    return False


def _coletar_arquivos_js() -> list[Path]:
    arquivos = []
    for path in sorted(BASE_DIR.glob("*/static/*/js/**/*.js")):
        if not _is_ignored(path):
            arquivos.append(path)
    return arquivos


def _coletar_templates_html() -> list[Path]:
    templates = []
    for path in sorted(BASE_DIR.rglob("*.html")):
        if not _is_ignored(path):
            templates.append(path)
    return templates


DJANGO_IF_ELSE_RE = re.compile(
    r"\{%\s*else\s*%\}.*?\{%\s*endif\s*%\}",
    re.DOTALL,
)


def _sanitizar_django_js(codigo: str) -> str:
    """Substitui tags e variáveis Django por literais/comentários válidos em JS."""
    limpo = DJANGO_COMMENT_RE.sub(" ", codigo)
    # Em blocos simples {% if ... %} A {% else %} B {% endif %}, mantém apenas o ramo A.
    limpo = DJANGO_IF_ELSE_RE.sub(" ", limpo)
    limpo = DJANGO_TAG_RE.sub(" ", limpo)
    limpo = DJANGO_VAR_RE.sub("null", limpo)
    return limpo


def _extrair_scripts_inline(html_path: Path) -> list[tuple[int, str]]:
    conteudo = html_path.read_text(encoding="utf-8", errors="replace")
    scripts = []
    for match in SCRIPT_TAG_RE.finditer(conteudo):
        attrs = match.group("attrs") or ""
        if SRC_ATTR_RE.search(attrs):
            continue
        body = match.group("body")
        if not body.strip():
            continue
        linha_inicio = conteudo[: match.start()].count("\n") + 1
        scripts.append((linha_inicio, _sanitizar_django_js(body)))
    return scripts


def _checar_com_node(node_bin: str, codigo: str, origem: str) -> str | None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(codigo)
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [node_bin, "--check", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return f"{origem}: {err}"
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


def test_integridade_js_arquivos_estaticos():
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js não encontrado no PATH; checagem de sintaxe JS pulada.")

    erros = []
    for js_path in _coletar_arquivos_js():
        rel = js_path.relative_to(BASE_DIR).as_posix()
        codigo = js_path.read_text(encoding="utf-8", errors="replace")
        erro = _checar_com_node(node_bin, codigo, rel)
        if erro:
            erros.append(erro)

    assert not erros, "Erros de sintaxe JS em arquivos estáticos:\n" + "\n".join(erros)


def test_integridade_js_scripts_inline_templates():
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js não encontrado no PATH; checagem de sintaxe JS pulada.")

    erros = []
    for html_path in _coletar_templates_html():
        rel = html_path.relative_to(BASE_DIR).as_posix()
        for linha, codigo in _extrair_scripts_inline(html_path):
            erro = _checar_com_node(node_bin, codigo, f"{rel}:{linha}")
            if erro:
                erros.append(erro)

    assert not erros, "Erros de sintaxe JS em <script> inline:\n" + "\n".join(erros)


def test_layout_base_dashboard_blocos():
    """
    Templates que estendem base_dashboard.html não podem sobrescrever `block content`
    (devem usar `dashboard_content`) e todo `<script>` deve ficar em `block extra_js`.
    """
    violacoes_content = []
    violacoes_script = []

    for html_path in _coletar_templates_html():
        conteudo = html_path.read_text(encoding="utf-8", errors="replace")
        if not EXTENDS_DASHBOARD_RE.search(conteudo):
            continue

        rel = html_path.relative_to(BASE_DIR).as_posix()
        if BLOCK_CONTENT_RE.search(conteudo):
            violacoes_content.append(rel)

        extra_js_match = BLOCK_EXTRA_JS_RE.search(conteudo)
        for match in SCRIPT_TAG_RE.finditer(conteudo):
            if not extra_js_match or match.start() < extra_js_match.start():
                linha = conteudo[: match.start()].count("\n") + 1
                violacoes_script.append(f"{rel}:{linha}")

    assert not violacoes_content, (
        "Templates estendendo base_dashboard.html sobrescrevem `block content`: "
        + ", ".join(violacoes_content)
    )
    assert not violacoes_script, (
        "Templates estendendo base_dashboard.html com <script> fora de `block extra_js`: "
        + ", ".join(violacoes_script)
    )
