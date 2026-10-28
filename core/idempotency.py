import functools
from collections.abc import Callable
from typing import Any

from django.db import IntegrityError, transaction

from core.context import get_current_tenant
from core.models import IdempotencyKey


def idempotent(escopo: str, chave_fn: Callable[..., Any] | None = None):
    """
    Decorator de Idempotência Estrita por Tenant (Sprint 7A).
    Garante que invocações repetidas com a mesma chave dentro do escopo e tenant
    devolvam o resultado previamente registrado sem re-executar operações colaterais.
    """
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 1. Determina a chave de idempotência
            if callable(chave_fn):
                chave = str(chave_fn(*args, **kwargs))
            elif isinstance(chave_fn, str):
                chave = str(kwargs.get(chave_fn) or (args[0] if args else ''))
            else:
                chave = kwargs.get('chave_idempotencia') or kwargs.get('idempotency_key') or kwargs.get('chave')
                if not chave:
                    if args and hasattr(args[0], 'id'):
                        chave = f"{func.__name__}:{args[0].id}"
                    else:
                        chave = f"{func.__name__}:{args!s}:{sorted(kwargs.items())!s}"

            chave_str = str(chave)

            # 2. Resolve o Tenant
            tenant = kwargs.get('tenant') or get_current_tenant()
            if not tenant and args and hasattr(args[0], 'tenant'):
                tenant = args[0].tenant

            if not tenant:
                # Se não há tenant contextualizado, executa diretamente
                return func(*args, **kwargs)

            # 3. Consulta existência prévia
            registro = IdempotencyKey.unscoped.filter(
                tenant=tenant,
                escopo=escopo,
                chave=chave_str
            ).first()

            if registro:
                if registro.resultado_json is not None:
                    return registro.resultado_json
                return registro.resultado_ref

            # 4. Executa a função e persiste a chave transacionalmente
            with transaction.atomic():
                resultado = func(*args, **kwargs)

                resultado_ref = None
                resultado_json = None
                if isinstance(resultado, (dict, list, str, int, bool)):
                    resultado_json = resultado
                    resultado_ref = str(resultado)[:255]
                elif hasattr(resultado, 'id'):
                    resultado_ref = str(resultado.id)
                else:
                    resultado_ref = str(resultado)[:255]

                try:
                    IdempotencyKey.unscoped.create(
                        tenant=tenant,
                        escopo=escopo,
                        chave=chave_str,
                        resultado_ref=resultado_ref,
                        resultado_json=resultado_json
                    )
                except IntegrityError:
                    # Concorrência: outra thread completou e inseriu a chave simultaneamente
                    registro_concorrente = IdempotencyKey.unscoped.filter(
                        tenant=tenant,
                        escopo=escopo,
                        chave=chave_str
                    ).first()
                    if registro_concorrente:
                        if registro_concorrente.resultado_json is not None:
                            return registro_concorrente.resultado_json
                        return registro_concorrente.resultado_ref

                return resultado

        return wrapper
    return decorator
