import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from core.tenancy import (
    TenantManager,
    TenantNotSet,
    get_current_tenant,
    reset_current_tenant,
    set_current_tenant,
    tenant_context,
)

__all__ = [
    "TenantManager",
    "TenantNotSet",
    "execution_context",
    "get_current_ip",
    "get_current_request_id",
    "get_current_tenant",
    "get_current_user",
    "reset_current_ip",
    "reset_current_request_id",
    "reset_current_tenant",
    "reset_current_user",
    "set_current_ip",
    "set_current_request_id",
    "set_current_tenant",
    "set_current_user",
    "tenant_context",
]

_current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
_current_user: ContextVar[Any | None] = ContextVar("current_user", default=None)
_current_ip: ContextVar[str | None] = ContextVar("current_ip", default=None)


def get_current_request_id() -> str | None:
    """Retorna o request_id único da requisição atual ou None se fora de contexto HTTP."""
    return _current_request_id.get()


def set_current_request_id(request_id: str | None):
    """Define o request_id da requisição atual."""
    return _current_request_id.set(request_id or str(uuid.uuid4()))


def reset_current_request_id(token):
    if token is not None:
        _current_request_id.reset(token)


def get_current_user() -> Any | None:
    return _current_user.get()


def set_current_user(user: Any | None):
    return _current_user.set(user)


def reset_current_user(token):
    if token is not None:
        _current_user.reset(token)


def get_current_ip() -> str | None:
    return _current_ip.get()


def set_current_ip(ip: str | None):
    return _current_ip.set(ip)


def reset_current_ip(token):
    if token is not None:
        _current_ip.reset(token)


@contextmanager
def execution_context(tenant=None, request_id=None, user=None, ip=None):
    """
    Context manager unificado para jobs, requisições e scripts batch.
    Configura tenant, request_id, usuário e IP simultaneamente de forma segura.
    """
    tokens = []
    if tenant is not None:
        tokens.append(('tenant', set_current_tenant(tenant)))
    if request_id is not None:
        tokens.append(('req_id', set_current_request_id(request_id)))
    if user is not None:
        tokens.append(('user', set_current_user(user)))
    if ip is not None:
        tokens.append(('ip', set_current_ip(ip)))

    try:
        yield
    finally:
        for name, token in reversed(tokens):
            if name == 'tenant':
                reset_current_tenant(token)
            elif name == 'req_id':
                reset_current_request_id(token)
            elif name == 'user':
                reset_current_user(token)
            elif name == 'ip':
                reset_current_ip(token)
