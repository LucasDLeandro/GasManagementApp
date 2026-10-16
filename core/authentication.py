from rest_framework_simplejwt.authentication import JWTAuthentication
from django.http import Http404
from core.models import Tenant, Membership

class TenantJWTAuthentication(JWTAuthentication):
    """
    Classe customizada de autenticação JWT para Django REST Framework.
    Além de validar o token JWT, resolve e valida o Membership ativo no Tenant.
    Se o header X-Tenant-ID for informado para um tenant inacessível, lança Http404.
    """
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        
        user, validated_token = result
        tenant_id_header = request.headers.get('X-Tenant-ID') or request.META.get('HTTP_X_TENANT_ID')
        tenant = None
        membership = None

        if tenant_id_header:
            if user.is_superuser:
                tenant = Tenant.objects.filter(id=tenant_id_header, ativo=True).first()
            else:
                membership = Membership.objects.filter(
                    user=user,
                    tenant_id=tenant_id_header,
                    ativo=True,
                    tenant__ativo=True
                ).select_related('tenant').first()
                if membership:
                    tenant = membership.tenant
            
            if not tenant:
                raise Http404("Tenant não encontrado ou inexistente para o usuário.")
        else:
            membership = Membership.objects.filter(
                user=user,
                ativo=True,
                tenant__ativo=True
            ).select_related('tenant').first()
            if membership:
                tenant = membership.tenant
            elif user.is_superuser:
                tenant = Tenant.objects.filter(ativo=True).first()

            if not tenant and not user.is_superuser:
                raise Http404("Nenhum tenant ativo associado ao usuário.")

        request.tenant = tenant
        request.membership = membership
        return (user, validated_token)
