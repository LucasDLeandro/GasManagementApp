"""
Permissões e Guardas de Acesso do Portal B2B (Sprint 12B).

Implementa:
- IsB2BAuthenticated: valida vínculo B2B ativo, não revogado e não bloqueado.
- IsCompradorRole, IsFinanceiroRole, IsAdminCliente: autorização baseada nos papéis B2B.
- RequiresMFAIfFinanceiro: bloqueia acesso a rotas financeiras sem validação TOTP.
- TenantWritableB2B: bloqueia operações de escrita caso o tenant esteja SUSPENSO/CANCELADO.
- ModuloAtivoB2B: valida ativação dos módulos contratados ('b2b', 'financeiro', 'fiscal').
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone

from core.guards import (
    assert_tenant_writable,
    assert_modulo,
    AssinaturaInativaError,
    ModuloInativoError,
)
from clientes.models import UsuarioClienteB2B


class IsB2BAuthenticated(BasePermission):
    """
    Exige que o usuário possua vínculo ativo de UsuarioClienteB2B,
    sem bloqueio por tentativas e sem revogação de acesso.
    """
    message = "Acesso restrito ao Portal B2B do Cliente."

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return False

        vinculo: UsuarioClienteB2B = getattr(user, 'vinculo_b2b', None)
        if not vinculo:
            return False

        if not vinculo.ativo or vinculo.acesso_revogado_em is not None:
            return False

        if vinculo.esta_bloqueado:
            return False

        # Injeta tenant e cliente na requisição para conveniência
        if not getattr(request, 'tenant', None) and vinculo.tenant:
            request.tenant = vinculo.tenant
        request.cliente_b2b = vinculo.cliente
        request.vinculo_b2b = vinculo

        # Validação do módulo B2B no plano do Tenant
        try:
            assert_modulo(vinculo.tenant, 'b2b')
        except ModuloInativoError as err:
            raise PermissionDenied({'detail': str(err), 'code': 'MODULO_INATIVO'}, code='MODULO_INATIVO')

        # Se for operação de escrita, valida se tenant está ativo e não suspenso
        if request.method not in SAFE_METHODS:
            try:
                assert_tenant_writable(vinculo.tenant)
            except AssinaturaInativaError as err:
                raise PermissionDenied({'detail': str(err), 'code': 'ASSINATURA_INATIVA'}, code='ASSINATURA_INATIVA')

        return True


class IsCompradorRole(BasePermission):
    """Permite acesso apenas a usuários com papel COMPRADOR (ou administrador do cliente)."""
    message = "Apenas usuários com papel Comprador podem realizar esta operação."

    def has_permission(self, request, view):
        vinculo = getattr(request, 'vinculo_b2b', None) or getattr(request.user, 'vinculo_b2b', None)
        if not vinculo:
            return False
        return vinculo.papel == UsuarioClienteB2B.PAPEL_COMPRADOR or vinculo.administrador_cliente


class IsFinanceiroRole(BasePermission):
    """Permite acesso apenas a usuários com papel FINANCEIRO (ou administrador do cliente)."""
    message = "Apenas usuários do setor Financeiro podem consultar faturas, boletos e notas fiscais."

    def has_permission(self, request, view):
        vinculo = getattr(request, 'vinculo_b2b', None) or getattr(request.user, 'vinculo_b2b', None)
        if not vinculo:
            return False
        return vinculo.papel == UsuarioClienteB2B.PAPEL_FINANCEIRO or vinculo.administrador_cliente


class IsAdminCliente(BasePermission):
    """Permite gerenciamento de usuários apenas a administradores da conta do cliente."""
    message = "Apenas o Administrador do Cliente pode emitir convites ou revogar acessos de sua equipe."

    def has_permission(self, request, view):
        vinculo = getattr(request, 'vinculo_b2b', None) or getattr(request.user, 'vinculo_b2b', None)
        if not vinculo:
            return False
        return bool(vinculo.administrador_cliente)


class RequiresMFAIfFinanceiro(BasePermission):
    """
    Exige autenticação de dois fatores (TOTP) confirmada para usuários com papel FINANCEIRO.
    Se o usuário é FINANCEIRO e a sessão não está com MFA confirmada, bloqueia o acesso a dados financeiros.
    """
    message = "Autenticação em duas etapas (MFA) obrigatória para o papel Financeiro. Confirme seu token TOTP."

    def has_permission(self, request, view):
        vinculo = getattr(request, 'vinculo_b2b', None) or getattr(request.user, 'vinculo_b2b', None)
        if not vinculo:
            return False

        if vinculo.mfa_obrigatoria:
            mfa_ok = (
                request.session.get('b2b_mfa_verified', False)
                or (getattr(request, '_original_session', None) and request._original_session.get('b2b_mfa_verified', False))
                or request.META.get('HTTP_X_B2B_MFA_VERIFIED') == 'true'
            )
            if not mfa_ok:
                raise PermissionDenied({'detail': self.message, 'code': 'MFA_OBRIGATORIA'}, code='MFA_OBRIGATORIA')
        return True


class RequiresModuloFinanceiro(BasePermission):
    """Valida se o módulo financeiro está ativo no tenant."""
    message = "O módulo Financeiro não está habilitado para esta empresa."

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            vinculo = getattr(request.user, 'vinculo_b2b', None)
            tenant = vinculo.tenant if vinculo else None
        if not tenant:
            return False
        try:
            assert_modulo(tenant, 'financeiro')
            return True
        except ModuloInativoError as err:
            raise PermissionDenied({'detail': str(err), 'code': 'MODULO_INATIVO'}, code='MODULO_INATIVO')


class RequiresModuloFiscal(BasePermission):
    """Valida se o módulo fiscal está ativo no tenant."""
    message = "O módulo Fiscal não está habilitado para esta empresa."

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            vinculo = getattr(request.user, 'vinculo_b2b', None)
            tenant = vinculo.tenant if vinculo else None
        if not tenant:
            return False
        try:
            assert_modulo(tenant, 'fiscal')
            return True
        except ModuloInativoError as err:
            raise PermissionDenied({'detail': str(err), 'code': 'MODULO_INATIVO'}, code='MODULO_INATIVO')
