import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from core.context import tenant_context

logger = logging.getLogger(__name__)

_seeds_por_modulo: dict[str, list[Callable[[Any], Any]]] = defaultdict(list)


def registrar_seed(modulo: str, fn: Callable[[Any], Any]) -> None:
    """Registra uma função de seed idempotente para um módulo específico."""
    if fn not in _seeds_por_modulo[modulo]:
        _seeds_por_modulo[modulo].append(fn)


def executar_seeds(tenant: Any, modulo: str | None = None) -> list[tuple[str, str, Any]]:
    """
    Executa os seeds idempotentes registrados para os módulos ativos do Tenant.
    Se um módulo específico for informado, executa apenas os seeds daquele módulo.
    Garante execução estritamente sob tenant_context(tenant).
    """
    from core.modulos import MODULOS_REGISTRO, is_modulo_ativo

    if modulo:
        modulos_alvo = [modulo]
    else:
        modulos_alvo = [m for m in MODULOS_REGISTRO if is_modulo_ativo(tenant, m)]

    resultados = []
    with tenant_context(tenant):
        for mod in modulos_alvo:
            seeds = _seeds_por_modulo.get(mod, [])
            for fn in seeds:
                try:
                    res = fn(tenant)
                    resultados.append((mod, getattr(fn, '__name__', str(fn)), res))
                except Exception:
                    logger.exception(
                        f"[Seeds] Erro ao executar seed '{getattr(fn, '__name__', str(fn))}' "
                        f"no módulo '{mod}' para tenant '{tenant.nome}'"
                    )
                    raise

    return resultados


# ==============================================================================
# SEEDS PADRÃO DOS MÓDULOS (Idempotentes)
# ==============================================================================

def seed_patrimonio_defaults(tenant: Any) -> dict[str, Any]:
    """Seed de configurações operacionais padrão para gestão patrimonial."""
    return {'status': 'PATRIMONIO_SEEDED', 'tenant': tenant.nome}


def seed_financeiro_rbac(tenant: Any) -> dict[str, Any]:
    """Seed das permissões e grupos financeiros (Sprint 7A / 7B)."""
    from core.rbac import seed_rbac_financeiro
    seed_rbac_financeiro()
    return {'status': 'FINANCEIRO_RBAC_SEEDED', 'tenant': tenant.nome}


registrar_seed('patrimonio', seed_patrimonio_defaults)
registrar_seed('financeiro', seed_financeiro_rbac)
