from django.contrib.auth.backends import ModelBackend
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.http import Http404
from core.models import Tenant, Membership


class InternalModelBackend(ModelBackend):
    """
    Backend de autenticação do sistema INTERNO (Sprint 12B - identidade separada do Portal B2B).

    Usuários do Portal B2B (que possuem UsuarioClienteB2B e nenhum Membership, não sendo
    superusuários nem staff) jamais autenticam no sistema interno — nem por sessão web,
    nem por JWT. Eles usam exclusivamente portal_b2b.auth.PortalB2BBackend.
    """

    def user_can_authenticate(self, user):
        if not super().user_can_authenticate(user):
            return False
        if user.is_superuser or user.is_staff:
            return True
        if user.vinculo_b2b is not None and not Membership.objects.filter(user=user).exists():
            return False
        return True


class TenantJWTAuthentication(JWTAuthentication):
    """
    Classe customizada de autenticação JWT para Django REST Framework.
    Além de validar o token JWT, resolve e valida o Membership ativo no Tenant.
    Se o header X-Tenant-ID for informado para um tenant inacessível, lança Http404.
    """
    def authenticate(self, request):
        try:
            result = super().authenticate(request)
        except Exception:
            # Se o token JWT for inválido ou expirado, mas o usuário possui sessão web ativa (cookies),
            # permite que a autenticação prossiga para SessionAuthentication em vez de barrar com 401
            raw_req = getattr(request, '_request', request)
            user = getattr(raw_req, 'user', None)
            if user and user.is_authenticated:
                return None
            raise

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
            session_tenant_id = None
            if hasattr(request, 'session'):
                session_tenant_id = request.session.get('active_tenant_id')
            elif hasattr(request, '_request') and hasattr(request._request, 'session'):
                session_tenant_id = request._request.session.get('active_tenant_id')

            if session_tenant_id:
                if user.is_superuser:
                    tenant = Tenant.objects.filter(id=session_tenant_id, ativo=True).first()
                else:
                    membership = Membership.objects.filter(
                        user=user,
                        tenant_id=session_tenant_id,
                        ativo=True,
                        tenant__ativo=True
                    ).select_related('tenant').first()
                    if membership:
                        tenant = membership.tenant

            if not tenant:
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
