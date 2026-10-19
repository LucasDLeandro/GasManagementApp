def tenant_membership_context(request):
    """
    Context Processor que injeta os dados do Tenant e o papel do Membership atual
    nos templates, unificando o controle de acesso e eliminando a dependência de User.tipo_usuario.
    """
    membership = getattr(request, 'membership', None)
    tenant = getattr(request, 'tenant', None)
    papel = membership.papel if (membership and membership.ativo) else None

    is_super = bool(request.user and request.user.is_authenticated and request.user.is_superuser)

    user_tenants = []
    if request.user and request.user.is_authenticated:
        if is_super:
            from core.models import Tenant
            user_tenants = list(Tenant.objects.filter(ativo=True).order_by('nome_fantasia'))
        else:
            user_tenants = [m.tenant for m in request.user.memberships.filter(ativo=True, tenant__ativo=True).select_related('tenant').order_by('tenant__nome_fantasia')]

    has_multiple_tenants = len(user_tenants) > 1
    can_switch_tenant = bool(is_super and len(user_tenants) > 1)

    return {
        'current_tenant': tenant,
        'current_membership': membership,
        'user_papel': papel,
        'user_tenants': user_tenants,
        'has_multiple_tenants': has_multiple_tenants,
        'can_switch_tenant': can_switch_tenant,
        'is_admin': papel == 'ADMIN' or is_super,
        'is_gerente': papel in ('ADMIN', 'GERENTE') or is_super,
        'is_responsavel_tecnico': papel == 'RESPONSAVEL_TECNICO' or is_super,
        'is_operador_patio': papel in ('OPERADOR_PATIO', 'RESPONSAVEL_TECNICO', 'ADMIN') or is_super,
        'is_motorista': papel in ('MOTORISTA', 'ADMIN') or is_super,
        'is_vendedor': papel in ('VENDEDOR', 'GERENTE', 'ADMIN') or is_super,
    }
