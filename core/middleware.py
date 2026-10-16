from django.http import Http404
from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant

class TenantMiddleware:
    """
    Middleware responsável por identificar a empresa (Tenant) ativa da requisição
    e configurar o ContextVar correspondente para isolamento Fail-Closed.
    
    Garante o ciclo de vida estrito através de bloco try ... finally no __call__,
    eliminando duplo reset entre process_exception e process_response.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Suporte a autenticação prévia via JWT para APIs caso presente no header Authorization
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            force_user = getattr(request, '_force_auth_user', None)
            if force_user and force_user.is_authenticated:
                request.user = force_user
            else:
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if auth_header.startswith('Bearer '):
                    try:
                        from rest_framework_simplejwt.authentication import JWTAuthentication
                        jwt_auth = JWTAuthentication()
                        validated_token = jwt_auth.get_validated_token(auth_header.split(' ')[1])
                        user = jwt_auth.get_user(validated_token)
                        if user:
                            request.user = user
                    except Exception:
                        pass

        tenant = None
        membership = None
        user = getattr(request, 'user', None)

        if user and user.is_authenticated:
            tenant_id_header = request.headers.get('X-Tenant-ID') or request.META.get('HTTP_X_TENANT_ID')
            session_tenant_id = request.session.get('active_tenant_id') if hasattr(request, 'session') else None

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

                # Se passou X-Tenant-ID explicitamente mas não tem acesso ou não existe -> 404
                if not tenant:
                    raise Http404("Tenant não encontrado ou inexistente para o usuário.")
            elif session_tenant_id:
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

        request.tenant = tenant
        request.membership = membership
        token = set_current_tenant(tenant)
        try:
            response = self.get_response(request)
            return response
        finally:
            reset_current_tenant(token)
