from rest_framework.permissions import BasePermission
from core.models import Membership
from core.tenancy import get_current_tenant


def resolve_request_membership(request):
    """
    Resolve o Membership ativo do usuário para a requisição corrente.
    Utiliza o cache em request.membership ou consulta o banco com base no tenant ativo.
    """
    membership = getattr(request, 'membership', None)
    if membership and membership.ativo:
        return membership

    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return None

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        tenant = get_current_tenant()

    if tenant:
        membership = Membership.objects.filter(
            user=user,
            tenant=tenant,
            ativo=True,
            tenant__ativo=True
        ).select_related('tenant').first()
        if membership:
            request.membership = membership
            request.tenant = tenant
            return membership

    membership = Membership.objects.filter(
        user=user,
        ativo=True,
        tenant__ativo=True
    ).select_related('tenant').first()
    if membership:
        request.membership = membership
        request.tenant = membership.tenant
        return membership

    return None


class IsTenantMember(BasePermission):
    """
    Exige que o usuário esteja autenticado e possua um Membership ativo no tenant atual.
    Superusuários do Django mantêm acesso global.
    """
    message = "Acesso negado: você não possui vínculo ativo com esta empresa (Tenant)."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo)


class IsTenantAdmin(BasePermission):
    """
    Permissão exclusiva para o papel ADMINISTRADOR do tenant.
    """
    message = "Acesso restrito a Administradores da empresa."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel == 'ADMIN')


class IsTenantAdminOrGerente(BasePermission):
    """
    Permissão para Administradores ou Gerentes do tenant.
    """
    message = "Acesso restrito à gestão da empresa (Administrador ou Gerente)."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel in ('ADMIN', 'GERENTE'))


class IsResponsavelTecnico(BasePermission):
    """
    Permissão exclusiva para o Responsável Técnico (CRF/CRQ).
    """
    message = "Acesso restrito ao Responsável Técnico (Farmacêutico ou Químico)."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel == 'RESPONSAVEL_TECNICO')


class CanOperateRampaEnvase(BasePermission):
    """
    Permissão para operação de rampa de envase, triagem física e recebimento de cilindros.
    Autorizados: OPERADOR_PATIO, RESPONSAVEL_TECNICO e ADMIN.
    """
    message = "Apenas Operadores de Pátio, Responsáveis Técnicos e Administradores podem operar a rampa de envase e triagem."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(
            membership and membership.ativo and
            membership.papel in ('OPERADOR_PATIO', 'RESPONSAVEL_TECNICO', 'ADMIN')
        )


class CanApproveLoteOuMedicinal(BasePermission):
    """
    Permissão para homologação sanitária, liberação de lote e reclassificação medicinal.
    Autorizados: RESPONSAVEL_TECNICO (e superusuário do sistema).
    """
    message = "Apenas o Responsável Técnico habilitado perante o conselho de classe pode homologar lotes ou reclassificações medicinais."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(
            membership and membership.ativo and
            membership.papel in ('RESPONSAVEL_TECNICO', 'ADMIN')
        )


class IsMotorista(BasePermission):
    """
    Permissão para motoristas e logística em trânsito.
    """
    message = "Acesso restrito à equipe de logística e transporte."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel in ('MOTORISTA', 'ADMIN'))


class IsVendedor(BasePermission):
    """
    Permissão para equipe comercial / vendas.
    """
    message = "Acesso restrito à equipe comercial e vendas."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel in ('VENDEDOR', 'GERENTE', 'ADMIN'))


class IsMotoristaOrAdmin(BasePermission):
    """
    Permissão estrita para conclusão de romaneio e sincronização offline (D6).
    Autorizados: MOTORISTA e ADMIN.
    """
    message = "Acesso restrito a Motoristas e Administradores da empresa."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        return bool(membership and membership.ativo and membership.papel in ('MOTORISTA', 'ADMIN'))

