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


from rest_framework.exceptions import PermissionDenied
from core.modulos import is_modulo_ativo


def make_module_permission(codigo: str):
    """Fábrica de permissões DRF por módulo com código MODULO_INATIVO (Sprint 7B)."""
    class ModulePermission(BasePermission):
        modulo_codigo = codigo
        message = f"MODULO_INATIVO: O módulo '{codigo}' não está ativo no plano do Tenant."

        def has_permission(self, request, view):
            if not (request.user and request.user.is_authenticated):
                return False
            if request.user.is_superuser:
                return True
            tenant = getattr(request, 'tenant', None) or get_current_tenant()
            if not tenant:
                membership = resolve_request_membership(request)
                tenant = membership.tenant if membership else None
            if not tenant:
                return False
            if not is_modulo_ativo(tenant, self.modulo_codigo):
                raise PermissionDenied({
                    "code": "MODULO_INATIVO",
                    "detail": f"O módulo '{self.modulo_codigo}' não está ativo no plano da empresa contratante.",
                    "modulo": self.modulo_codigo
                })
            return True

    ModulePermission.__name__ = f"RequiresModule{codigo.capitalize()}"
    return ModulePermission


RequiresModulePatrimonio = make_module_permission('patrimonio')
RequiresModuleEnvase = make_module_permission('envase')
RequiresModuleComercial = make_module_permission('comercial')
RequiresModuleVendas = make_module_permission('vendas')
RequiresModuleLogistica = make_module_permission('logistica')
RequiresModuleFinanceiro = make_module_permission('financeiro')
RequiresModuleFiscal = make_module_permission('fiscal')
RequiresModuleB2B = make_module_permission('b2b')
RequiresModuleAnalytics = make_module_permission('analytics')
# Alias de retrocompatibilidade para integrações legadas (Sprint 13 - Tarefa 8)
RequiresModuleDistribuicao = RequiresModuleLogistica


class IsTenantSubscriptionActive(BasePermission):
    """
    Bloqueia requisições de escrita (POST, PUT, PATCH, DELETE) se a assinatura do Tenant
    estiver com status 'SUSPENSO' ou 'CANCELADO', respondendo 403 com código ASSINATURA_INATIVA.
    Operações de leitura (GET/HEAD/OPTIONS) são permitidas para auditoria e exportação.
    """
    message = "ASSINATURA_INATIVA: A assinatura da empresa está suspensa ou cancelada."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True

        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True

        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not tenant:
            membership = resolve_request_membership(request)
            tenant = membership.tenant if membership else None

        if not tenant:
            return False

        status = getattr(tenant, 'status_assinatura', 'TRIAL')
        if status in ('SUSPENSO', 'CANCELADO') or not getattr(tenant, 'ativo', True):
            raise PermissionDenied({
                "code": "ASSINATURA_INATIVA",
                "detail": f"Operações de escrita bloqueadas. Status da assinatura: {status}.",
                "status_assinatura": status,
                "motivo": getattr(tenant, 'motivo_suspensao', '')
            })

        return True


class IsSuperUserStrict(BasePermission):
    """Exige que o usuário seja autenticado e superusuário estrito."""
    message = "Acesso restrito exclusivamente aos administradores globais do SaaS Baros."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsClientB2B(BasePermission):
    """
    Permissão exclusiva para usuários do Portal B2B do Cliente (Autoatendimento).
    Fail-Closed estrito:
    - Nega por padrão se o usuário não estiver autenticado;
    - Exige hasattr(request.user, 'usuarioclienteb2b') e perfil ativo;
    - Garante isolamento estrito de Tenant e de Cliente;
    - has_object_permission valida escopo exclusivo do cliente B2B autenticado.
    """
    message = "Acesso restrito ao Portal B2B do Cliente (Autoatendimento)."

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return False

        if not hasattr(user, 'usuarioclienteb2b'):
            return False

        b2b_profile = user.usuarioclienteb2b
        if not b2b_profile or not getattr(b2b_profile, 'ativo', False):
            return False

        if not getattr(b2b_profile, 'cliente_id', None):
            return False

        # Validação estrita de Tenant
        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if tenant and b2b_profile.tenant_id and b2b_profile.tenant_id != tenant.id:
            return False

        # Injeta o tenant na requisição se ainda não configurado
        if not getattr(request, 'tenant', None) and b2b_profile.tenant:
            request.tenant = b2b_profile.tenant

        return True

    def has_object_permission(self, request, view, obj):
        if not self.has_permission(request, view):
            return False

        cliente_b2b = request.user.usuarioclienteb2b.cliente

        # 1. Atributo direto 'cliente' (ex: Venda, FaturaCobranca com cliente)
        if hasattr(obj, 'cliente') and obj.cliente is not None:
            return obj.cliente == cliente_b2b

        # 2. Atributo 'cliente_posse_atual' (ex: Cilindro em comodato)
        if hasattr(obj, 'cliente_posse_atual') and obj.cliente_posse_atual is not None:
            return obj.cliente_posse_atual == cliente_b2b

        # 3. Cilindro proprietário
        if hasattr(obj, 'cliente_proprietario') and obj.cliente_proprietario is not None:
            return obj.cliente_proprietario == cliente_b2b

        # 4. Relação indireta por Venda ou Estadia em Faturas
        if hasattr(obj, 'venda') and obj.venda and getattr(obj.venda, 'cliente', None):
            if obj.venda.cliente == cliente_b2b:
                return True

        if hasattr(obj, 'estadia') and obj.estadia and getattr(obj.estadia, 'cliente', None):
            if obj.estadia.cliente == cliente_b2b:
                return True

        return False


class CanViewDRE(BasePermission):
    """
    Permissão granular para visualização de DRE, Balancete e Relatórios Gerenciais (Sprint 10C / Sprint 7A).
    Autorizados:
    - Superusuário
    - Usuário com permissão 'financeiro.ver_dre'
    - Usuário em grupos FIN_APROVADOR, FIN_AUDITOR, FIN_ADMIN
    - Usuário com papel ADMIN ou GERENTE no Membership ativo do Tenant.
    """
    message = "Acesso negado: visualização de relatórios financeiros gerenciais exige permissão 'financeiro.ver_dre' ou perfil administrativo."

    def has_permission(self, request, view):
        return user_has_ver_dre(request)


def user_has_ver_dre(request) -> bool:
    """Verifica se o usuário da requisição possui autorização para ver relatórios financeiros executivos."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    if user.has_perm('financeiro.ver_dre'):
        return True
    if user.groups.filter(name__in=['FIN_APROVADOR', 'FIN_AUDITOR', 'FIN_ADMIN']).exists():
        return True
    membership = resolve_request_membership(request)
    if membership and membership.ativo and membership.papel in ('ADMIN', 'GERENTE'):
        return True
    return False



