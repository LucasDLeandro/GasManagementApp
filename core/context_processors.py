from django.utils import timezone


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

    tem_modulo_envase = bool(tenant.modulo_envase_ativo) if tenant else False
    tem_modulo_distribuicao = bool(tenant.modulo_logistica_ativo) if tenant else True
    modo_operacao = tenant.modo_operacao if tenant else 'MISTO'

    return {
        'current_tenant': tenant,
        'current_membership': membership,
        'user_papel': papel,
        'user_tenants': user_tenants,
        'has_multiple_tenants': has_multiple_tenants,
        'can_switch_tenant': can_switch_tenant,
        'tem_modulo_envase': tem_modulo_envase,
        'tem_modulo_distribuicao': tem_modulo_distribuicao,
        'modo_operacao': modo_operacao,
        'is_admin': papel == 'ADMIN' or is_super,
        'is_gerente': papel in ('ADMIN', 'GERENTE') or is_super,
        'is_responsavel_tecnico': papel == 'RESPONSAVEL_TECNICO' or is_super,
        'is_operador_patio': papel in ('OPERADOR_PATIO', 'RESPONSAVEL_TECNICO', 'ADMIN') or is_super,
        'is_motorista': papel in ('MOTORISTA', 'ADMIN') or is_super,
        'is_vendedor': papel in ('VENDEDOR', 'GERENTE', 'ADMIN') or is_super,
    }


def modulos_ativos(request):
    """
    Context Processor que injeta os flags de módulos SaaS e estado da assinatura (Sprint 7B).
    Garante degradação graciosa da UI e suporte a Break-Glass.
    """
    tenant = getattr(request, 'tenant', None)
    from core.modulos import MODULOS_REGISTRO, is_modulo_ativo

    modulos_dict = {
        cod: is_modulo_ativo(tenant, cod)
        for cod in MODULOS_REGISTRO
    }

    status_assinatura = getattr(tenant, 'status_assinatura', 'TRIAL')
    is_writable = bool(tenant and tenant.is_tenant_writable) if tenant else True

    break_glass_ativo = False
    break_glass_obj = None
    if request.user and request.user.is_authenticated and request.user.is_superuser and tenant:
        from core.models import AcessoSuporte
        agora = timezone.now()
        break_glass_obj = AcessoSuporte.objects.filter(
            superadmin=request.user,
            tenant=tenant,
            encerrado_em__isnull=True,
            inicio__lte=agora,
            expira_em__gte=agora
        ).first()
        break_glass_ativo = break_glass_obj is not None

    return {
        'modulos_ativos': modulos_dict,
        'status_assinatura': status_assinatura,
        'is_tenant_writable': is_writable,
        'break_glass_ativo': break_glass_ativo,
        'break_glass_obj': break_glass_obj,
    }

