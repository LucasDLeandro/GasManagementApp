from rest_framework.permissions import BasePermission
from core.permissions import RequiresModuleFiscal, resolve_request_membership


def _user_has_fiscal_action(request, perm_code: str) -> bool:
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    if user.has_perm(f"fiscal.{perm_code}"):
        return True
    membership = resolve_request_membership(request)
    if membership and membership.ativo and membership.papel in ('ADMIN', 'GERENTE'):
        return True
    return False


class CanEmitirFiscal(BasePermission):
    """Permissão granular para emitir NF-e / documentos fiscais (Task 8)."""
    message = "Acesso negado: permissão 'fiscal.emitir' necessária para emitir documentos fiscais."

    def has_permission(self, request, view):
        return _user_has_fiscal_action(request, 'emitir')


class CanCancelarFiscal(BasePermission):
    """Permissão granular para cancelar documentos fiscais (Task 8)."""
    message = "Acesso negado: permissão 'fiscal.cancelar' necessária para cancelar documentos fiscais."

    def has_permission(self, request, view):
        return _user_has_fiscal_action(request, 'cancelar')


class CanInutilizarFiscal(BasePermission):
    """Permissão granular para inutilizar numeração fiscal (Task 8)."""
    message = "Acesso negado: permissão 'fiscal.inutilizar' necessária para inutilizar faixas de numeração."

    def has_permission(self, request, view):
        return _user_has_fiscal_action(request, 'inutilizar')
